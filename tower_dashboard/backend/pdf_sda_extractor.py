"""PDF SDA Extractor & MS-Tower Native File Reconstructor.

Extracts native MS-Tower (.td, .twr, .rpt, .p1) files, structural analysis resume,
and device inventories from telecom tower SDA (Structural Design Analysis) PDF reports.
Supports multi-scenario reports: EXISTING, PROPOSED, and STRENGTHENING.
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

# Regex patterns for MS-Tower native statements
LARGE_DEVICE_RE = re.compile(
    r"^(?P<commented>\$\s*)?(?P<id>[A-Za-z0-9_-]+)\s+XA\s+(?P<xa>[-\d.]+)\s+YA\s+(?P<ya>[-\d.]+)\s+"
    r"ZA\s+(?P<za>[-\d.]+)\s+LIB\s+(?P<lib>\S+)\s+ANG\s+(?P<ang>[-\d.]+)\s+AMASS\s+(?P<mass>[-\d.]+)"
    r"(?:\s*\$(?P<note>.*))?$",
    re.I,
)

LINEAR_DEVICE_RE = re.compile(
    r"^(?P<commented>\$\s*)?(?P<id>[A-Za-z0-9_-]+)\s+XB\s+(?P<xb>[-\d.]+)\s+YB\s+(?P<yb>[-\d.]+)\s+"
    r"ZB\s+(?P<zb>[-\d.]+)\s+XT\s+(?P<xt>[-\d.]+)\s+YT\s+(?P<yt>[-\d.]+)\s+ZT\s+(?P<zt>[-\d.]+)\s+"
    r"LIB\s+(?P<lib>\S+).*?(?:\$(?P<note>.*))?$",
    re.I,
)

FOOTER_FILEPATH_RE = re.compile(
    r"([A-Za-z0-9_.\-\s\\/:]+?\.(td|twr|rpt|p1))\b",
    re.I,
)

PAGE_NUM_RE = re.compile(r"Page\s*[:#]?\s*(\d+)\s*(of|\/)\s*(\d+)", re.I)


def decode_pua_text(text: str) -> str:
    """Decode MS-Tower font Unicode Private Use Area (PUA \uF000-\uF0FF) to standard ASCII."""
    out = []
    for ch in text:
        code = ord(ch)
        if 0xF020 <= code <= 0xF07E:
            out.append(chr(code - 0xF000))
        elif code in (0xF0A0, 0x00A0):
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def _classify_scenario_from_text(text: str) -> str:
    """Infer scenario (EXISTING, PROPOSED, STRENGTHENING) from text hints."""
    u = text.upper()
    if "_STR" in u or "STRENGTHEN" in u or "PERKUATAN" in u:
        return "STRENGTHENING"
    if "_PROP" in u or "PROPOSED" in u or "TOWER PROPOSED" in u or "RENCANA" in u:
        return "PROPOSED"
    if "_EXT" in u or "EXISTING" in u or "TOWER EXISTING" in u or "EKSISTING" in u:
        return "EXISTING"
    return "PROPOSED"


def _clean_mst_lines(lines: list[str]) -> list[str]:
    """Strip repeating page headers and footers from printed MS-Tower output."""
    cleaned = []
    for raw in lines:
        line = raw.rstrip()
        u = line.upper().strip()
        if not u:
            cleaned.append("")
            continue

        # Common headers
        if "PAGE " in u and (" OF " in u or "/" in u):
            continue
        if re.search(r"^\s*Job\s*:\s*", line, re.I) and ("Date:" in line or "Page" in line):
            continue
        if re.search(r"^\s*Date\s*:\s*\d{1,2}[-\s][A-Za-z]{3}[-\s]\d{2,4}", line, re.I):
            continue
        if "MSTOWER [" in u or "MSTOWER V6" in u and ("PAGE" in u or "TIME:" in u):
            continue
        # Company / consultant banner line with page or date
        if any(c in u for c in ("PT. DWIRAY", "LEFTER", "KOMITEL", "SOLUSINDO")) and ("PAGE" in u or len(line) < 40):
            continue
        # Filepath footer with MStower watermark
        if FOOTER_FILEPATH_RE.search(line) and ("MSTOWER" in u or "\\" in line or "/" in line):
            continue

        cleaned.append(line)

    # Trim leading & trailing empty lines
    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()
    return cleaned


class SDAPdfExtractor:
    """Extracts MS-Tower native models, summary analysis, and inventories from PDF SDA reports."""

    def __init__(self):
        if fitz is None:
            raise RuntimeError("PyMuPDF is required for SDAPdfExtractor. Run 'pip install pymupdf'.")

    def extract_from_bytes(self, pdf_bytes: bytes, filename: str = "report.pdf") -> dict[str, Any]:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        total_pages = len(doc)

        site_metadata = self._extract_metadata(doc, filename)
        pages_by_type: dict[str, dict[str, list[str]]] = {
            "EXISTING": {"td": [], "twr": [], "rpt": [], "p1": []},
            "PROPOSED": {"td": [], "twr": [], "rpt": [], "p1": []},
            "STRENGTHENING": {"td": [], "twr": [], "rpt": [], "p1": []},
        }

        narrative_text_by_page: list[str] = []

        for pno in range(total_pages):
            page = doc.load_page(pno)
            raw_text = page.get_text("text")
            decoded = decode_pua_text(raw_text)
            lines = decoded.splitlines()

            # Detect if page belongs to native MS-Tower printout
            ftype, sc = self._detect_page_type_and_scenario(lines, decoded)
            if ftype and sc in pages_by_type:
                pages_by_type[sc][ftype].extend(lines)
            else:
                narrative_text_by_page.append(decoded)

        # Assemble cleaned native file text
        scenarios: dict[str, Any] = {}
        for sc in ("EXISTING", "PROPOSED", "STRENGTHENING"):
            ft_dict = pages_by_type[sc]
            td_raw = _clean_mst_lines(ft_dict["td"])
            twr_raw = _clean_mst_lines(ft_dict["twr"])
            rpt_raw = _clean_mst_lines(ft_dict["rpt"])
            p1_raw = _clean_mst_lines(ft_dict["p1"])

            td_text = "\n".join(td_raw)
            twr_text = "\n".join(twr_raw)
            rpt_text = "\n".join(rpt_raw)
            p1_text = "\n".join(p1_raw)

            has_files = bool(td_text or twr_text or rpt_text or p1_text)
            if not has_files and sc == "STRENGTHENING":
                # Only include STRENGTHENING if present
                continue

            # Parse device inventory from .twr
            devices = self._parse_devices_from_twr(twr_text, sc)

            # Parse structural results from .rpt, .p1, and narrative pages
            summary, member_checks = self._parse_structural_summary(
                rpt_text=rpt_text,
                p1_text=p1_text,
                scenario=sc,
                narrative_pages=narrative_text_by_page,
                default_height=site_metadata["tower_height_m"],
            )

            scenarios[sc] = {
                "scenario": sc,
                "has_mst_files": has_files,
                "mst_files": {
                    "td": td_text,
                    "twr": twr_text,
                    "rpt": rpt_text,
                    "p1": p1_text,
                },
                "devices": devices,
                "summary": summary,
                "member_checks": member_checks,
            }

        # If no scenario had distinct files, synthesize PROPOSED with whatever narrative summary found
        if not scenarios:
            summary, member_checks = self._parse_structural_summary(
                rpt_text="", p1_text="", scenario="PROPOSED", narrative_pages=narrative_text_by_page,
                default_height=site_metadata["tower_height_m"],
            )
            scenarios["PROPOSED"] = {
                "scenario": "PROPOSED",
                "has_mst_files": False,
                "mst_files": {"td": "", "twr": "", "rpt": "", "p1": ""},
                "devices": {"antennas": [], "linear": []},
                "summary": summary,
                "member_checks": member_checks,
            }

        return {
            "filename": filename,
            "site_metadata": site_metadata,
            "scenarios": scenarios,
        }

    def _extract_metadata(self, doc: fitz.Document, filename: str) -> dict[str, Any]:
        """Extract tower site metadata from first few pages and filename."""
        first_pages_text = "\n".join(
            decode_pua_text(doc.load_page(i).get_text("text")) for i in range(min(5, len(doc)))
        )

        site_id = ""
        site_name = ""
        project_id = ""
        regional = ""
        lat, lon = None, None
        tower_type = "4-Leg Lattice SST"
        tower_height_m = 42.0
        building_height_m = 0.0
        wind_design_kph = 120.0
        wind_oper_kph = 84.0

        # Site ID & Name
        m_id = re.search(r"(?:Site\s*ID|ID\s*Site)\s*[:=]\s*([A-Za-z0-9_\-]+)", first_pages_text, re.I)
        if m_id:
            site_id = m_id.group(1).strip()

        m_name = re.search(r"(?:Site\s*Name|Nama\s*Site)\s*[:=]\s*([^\n\r]+)", first_pages_text, re.I)
        if m_name:
            site_name = m_name.group(1).strip()

        # Fallback to filename if site_id is empty
        if not site_id:
            base = Path(filename).stem
            # e.g. SDA SITE_RAWASIMPRUG_42M
            parts = [p for p in re.split(r"[_\s\-]+", base) if p.upper() not in ("SDA", "SITE", "LAPORAN", "FINAL")]
            site_id = parts[0].upper() if parts else "SITE_SDA"
            if not site_name:
                site_name = " ".join(parts) if parts else site_id

        # Tower Type
        u_text = first_pages_text.upper()
        if any(k in u_text for k in ("2-POLE", "2 POLE", "TWIN POLE", "2POLE", "TWO POLE")):
            tower_type = "2-Pole Tower"
        elif "ROOFTOP POLE" in u_text or "RT POLE" in u_text or "RT-POLE" in u_text or "RT-" in u_text:
            tower_type = "Rooftop Pole"
        elif "MONOPOLE" in u_text:
            tower_type = "Monopole"
        elif "3-LEG" in u_text or "3 LEG" in u_text:
            tower_type = "3-Leg Lattice SST"
        elif "4-LEG" in u_text or "4 LEG" in u_text or "SST" in u_text:
            tower_type = "4-Leg Lattice SST"

        # Heights
        m_th = re.search(r"(?:Tinggi\s*Menara|Tower\s*Height)\s*[:=]?\s*([\d.]+)\s*m", first_pages_text, re.I)
        if m_th:
            tower_height_m = float(m_th.group(1))
        else:
            m_fn_h = re.search(r"(\d{2,3})\s*[Mm]\b", filename)
            if m_fn_h:
                tower_height_m = float(m_fn_h.group(1))

        m_bh = re.search(r"(?:Tinggi\s*Gedung|Building\s*Height)\s*[:=]?\s*([\d.]+)\s*m", first_pages_text, re.I)
        if m_bh:
            building_height_m = float(m_bh.group(1))

        # Coordinates
        m_lat = re.search(r"(?:Latitude|Lintang|LAT)\s*[:=]?\s*([+-]?\d+\.?\d*)", first_pages_text, re.I)
        if m_lat:
            try:
                lat = float(m_lat.group(1))
            except ValueError:
                pass

        m_lon = re.search(r"(?:Longitude|Bujur|LONG|LON)\s*[:=]?\s*([+-]?\d+\.?\d*)", first_pages_text, re.I)
        if m_lon:
            try:
                lon = float(m_lon.group(1))
            except ValueError:
                pass

        # Regional / Project ID
        m_reg = re.search(r"(?:Regional|Region)\s*[:=]?\s*([^\n\r]+)", first_pages_text, re.I)
        if m_reg:
            regional = m_reg.group(1).strip()
        m_proj = re.search(r"(?:Project\s*ID|PID)\s*[:=]?\s*([A-Za-z0-9_\-]+)", first_pages_text, re.I)
        if m_proj:
            project_id = m_proj.group(1).strip()

        # Wind speed
        m_wdes = re.search(r"(?:Kecepatan\s*Angin\s*Desain|Design\s*Wind\s*Speed)\s*[:=]?\s*([\d.]+)\s*(?:km/h|kph|m/s)?", first_pages_text, re.I)
        if m_wdes:
            w_val = float(m_wdes.group(1))
            wind_design_kph = w_val if w_val > 45.0 else w_val * 3.6

        return {
            "site_id": site_id,
            "site_name": site_name or site_id,
            "project_id": project_id,
            "regional": regional,
            "lat": lat,
            "lon": lon,
            "tower_type": tower_type,
            "tower_height_m": tower_height_m,
            "building_height_m": building_height_m,
            "wind_design_kph": round(wind_design_kph, 1),
            "wind_oper_kph": round(wind_oper_kph, 1),
        }

    def _detect_page_type_and_scenario(self, lines: list[str], full_page_text: str) -> tuple[str | None, str]:
        """Detect file extension (.td, .twr, .rpt, .p1) and scenario of an MS-Tower page."""
        u = full_page_text.upper()

        # 1) Check footer or header lines for exact filename pattern
        ftype = None
        sc = "PROPOSED"

        for line in reversed(lines[-8:]):  # usually footer
            m = FOOTER_FILEPATH_RE.search(line)
            if m:
                path_match = m.group(1)
                ftype = m.group(2).lower()
                sc = _classify_scenario_from_text(path_match)
                break

        if not ftype:
            for line in lines[:8]:  # sometimes header
                m = FOOTER_FILEPATH_RE.search(line)
                if m:
                    path_match = m.group(1)
                    ftype = m.group(2).lower()
                    sc = _classify_scenario_from_text(path_match)
                    break

        # 2) Fallback detection from page content keywords
        if not ftype:
            if "MEMBER CHECKING TO TIA-222-G" in u or "ENVELOPE OF TOWER ROTATIONS" in u:
                ftype = "rpt"
            elif "NODE DISPLACEMENTS" in u and ("LOAD CASE" in u or "TRANSLATION" in u):
                ftype = "p1"
            elif "ANCILLARIES" in u and "LIB" in u and ("ANG" in u or "AMASS" in u):
                ftype = "twr"
            elif "PARAMETERS" in u and ("TCAT" in u or "VB" in u or "KZT" in u):
                ftype = "twr"
            elif ("COORDINATES" in u or "GRID" in u or "PANELS" in u) and ("NODE" in u or "MEMBER" in u):
                ftype = "td"
            elif "TYPE: SPACE FRAME" in u or "TYPE: CANTILEVERED POLE" in u:
                ftype = "td"

            if ftype:
                sc = _classify_scenario_from_text(full_page_text)

        return ftype, sc

    def _parse_devices_from_twr(self, twr_text: str, scenario: str) -> dict[str, list[dict]]:
        """Parse antenna (LARGE) and linear feeder/ladder items from .twr text."""
        antennas: list[dict] = []
        linear: list[dict] = []

        if not twr_text:
            return {"antennas": antennas, "linear": linear}

        for line in twr_text.splitlines():
            line_str = line.strip()
            if not line_str:
                continue

            # Antenna (LARGE)
            m_ant = LARGE_DEVICE_RE.match(line_str)
            if m_ant:
                d = m_ant.groupdict()
                commented = bool(d.get("commented"))
                tag = d["id"].strip()
                xa = float(d["xa"])
                ya = float(d["ya"])
                za = float(d["za"])
                lib = d["lib"].strip()
                ang = float(d["ang"])
                mass = float(d["mass"])
                note = (d.get("note") or "").strip()

                # Status determination
                is_prop = commented or tag.upper().startswith(("RFP", "RRUP", "CBNP", "FLTP", "P_")) or scenario == "PROPOSED"
                status = "PROPOSED" if is_prop else "EXISTING"

                # Leg determination from note or coordinates
                note_u = note.upper()
                m_leg = re.search(r"\bLEG\s*([ABCD])\b", note_u)
                if m_leg:
                    leg = m_leg.group(1)
                elif xa >= 0 and ya >= 0:
                    leg = "A"
                elif xa >= 0 and ya < 0:
                    leg = "B"
                elif xa < 0 and ya < 0:
                    leg = "C"
                else:
                    leg = "D"

                # Tenant
                if any(k in note_u for k in ("TSEL", "TELKOMSEL")):
                    tenant = "TELKOMSEL"
                elif any(k in note_u for k in ("XL", "AXIS", "SMART")):
                    tenant = "XLSMART"
                elif any(k in note_u for k in ("IOH", "ISAT", "INDOSAT")):
                    tenant = "IOH"
                elif "SURGE" in note_u:
                    tenant = "SURGE"
                else:
                    tenant = "EXISTING" if status == "EXISTING" else "PROPOSED"

                antennas.append({
                    "tag": tag,
                    "id": tag,
                    "status": status,
                    "tenant": tenant,
                    "leg": leg,
                    "face": leg,
                    "elev_z_m": za,
                    "elevation_m": za,
                    "xa": xa,
                    "ya": ya,
                    "lib_name": lib,
                    "lib": lib,
                    "azimuth_deg": ang,
                    "mass_kg": mass,
                    "note": note,
                })
                continue

            # Linear item
            m_lin = LINEAR_DEVICE_RE.match(line_str)
            if m_lin:
                d = m_lin.groupdict()
                commented = bool(d.get("commented"))
                tag = d["id"].strip()
                xb, yb, zb = float(d["xb"]), float(d["yb"]), float(d["zb"])
                xt, yt, zt = float(d["xt"]), float(d["yt"]), float(d["zt"])
                lib = d["lib"].strip()
                note = (d.get("note") or "").strip()

                is_prop = commented or tag.upper().startswith("P") or scenario == "PROPOSED"
                status = "PROPOSED" if is_prop else "EXISTING"

                linear.append({
                    "tag": tag,
                    "id": tag,
                    "status": status,
                    "lib_name": lib,
                    "lib": lib,
                    "zb_m": zb,
                    "zt_m": zt,
                    "elevation_m": zt,
                    "xb": xb,
                    "yb": yb,
                    "xt": xt,
                    "yt": yt,
                    "note": note,
                })

        return {"antennas": antennas, "linear": linear}

    def _parse_structural_summary(
        self,
        rpt_text: str,
        p1_text: str,
        scenario: str,
        narrative_pages: list[str],
        default_height: float = 42.0,
    ) -> tuple[dict[str, Any], list[dict]]:
        """Extract stress ratios, slenderness, deformations, and reaction summaries."""
        member_checks: list[dict] = []
        stress_ratios: dict[str, float] = {}
        slenderness: dict[str, float] = {}
        total_mass_kg = 0.0

        max_sway_deg = 0.0
        max_twist_deg = 0.0
        max_displacement_m = 0.0
        pu_max_kn = 0.0
        tu_max_kn = 0.0
        vu_max_kn = 0.0

        anchor_interaction = 0.0
        anchor_tension = 0.0
        baseplate_ratio = 0.0
        anchor_status = "AMAN"
        baseplate_status = "AMAN"

        # 1) Parse member checks from .rpt text if available
        if rpt_text:
            lines = rpt_text.splitlines()
            in_mbr = False
            for line in lines:
                u = line.upper()
                if "MEMBER CHECKING TO TIA-222-G" in u:
                    in_mbr = True
                    continue
                if in_mbr:
                    if any(stop in u for stop in ("SUPPORT REACTIONS", "ENVELOPE OF", "ROTATIONS", "MASS SUMMARY")):
                        in_mbr = False
                        continue
                    # Match row format: Pnl Members Typ Size fy nb Case Pu Curve KL/r phiPn Pu/phiPn ...
                    m = re.match(
                        r"^\s*(\d+)\s+(\d+(?:-\d+)?)\s+([A-Za-z]+)\s+([A-Za-z0-9X]+)\s+(\d+)\s+(\d+)?\s+"
                        r"(\S+)\s+([\d.]+)\s+(\S+)\s+([\d.]+v?y?z?)\s+([\d.]+)\s+([\d.]+)",
                        line,
                    )
                    if m:
                        pnl = int(m.group(1))
                        m_id = m.group(2)
                        typ = m.group(3).upper()
                        size = m.group(4).upper()
                        klr_s = m.group(10)
                        klr = float(re.sub(r"[^\d.]", "", klr_s) or 50.0)
                        c_pn = float(m.group(11))
                        c_sr = float(m.group(12))

                        member_checks.append({
                            "pnl": pnl,
                            "members": m_id,
                            "typ": typ,
                            "size": size,
                            "kl_r": klr,
                            "phi_pn_mst_kn": c_pn,
                            "sr_mst": c_sr,
                            "status_mst": "AMAN (OK)" if c_sr <= 1.0 else "OVERSTRESS",
                        })

                        # Track category maximums
                        cat = "leg" if "LEG" in typ else "bracing" if any(b in typ for b in ("BR", "XBR", "DBR")) else "horizontal" if "HOR" in typ else "redundant"
                        stress_ratios[cat] = max(stress_ratios.get(cat, 0.0), c_sr)
                        slenderness[cat] = max(slenderness.get(cat, 0.0), klr)

            # Also parse Shaft Members table (Pole / Cantilever / 2-Pole)
            in_shaft = False
            for line in rpt_text.splitlines():
                u_sh = line.upper()
                if "SHAFT MEMBERS" in u_sh:
                    in_shaft = True
                    continue
                if in_shaft:
                    if not line.strip() or "ENVELOPE" in u_sh or "LOAD CASES" in u_sh or "ROTATIONS" in u_sh:
                        in_shaft = False
                        continue
                    m_sh = re.search(
                        r"^\s*(\d+)\s+([\d.]+)\s+(\d+)\s+([\d.]+)\s+(\d+)\s+(\d+)\s+(\d+)\s+([+-]?[\d.]+)\s+([+-]?[\d.]+)\s+([+-]?[\d.]+)\s+([+-]?[\d.]+)\s+([+-]?[\d.]+)\s+([+-]?[\d.]+)\s+([+-]?[\d.]+)\s+([+-]?[\d.]+)\s+([+-]?[\d.]+)",
                        line,
                    )
                    if m_sh:
                        mid = m_sh.group(1)
                        ht = float(m_sh.group(2))
                        d_val = float(m_sh.group(3))
                        t_val = float(m_sh.group(4))
                        nu = float(m_sh.group(8))
                        phi_nn = float(m_sh.group(13))
                        phi_mn = float(m_sh.group(14))
                        sh_sr = float(m_sh.group(16))
                        size_name = f"CHS{int(d_val)}X{t_val:g}"
                        member_checks.append({
                            "pnl": 1,
                            "members": mid,
                            "typ": "SHAFT",
                            "size": size_name,
                            "kl_r": round(ht * 1000.0 / (d_val / 4.0), 1) if d_val > 0 else 50.0,
                            "phi_pn_mst_kn": phi_nn,
                            "sr_mst": sh_sr,
                            "status_mst": "AMAN (OK)" if sh_sr <= 1.0 else "OVERSTRESS",
                        })
                        stress_ratios["leg"] = max(stress_ratios.get("leg", 0.0), sh_sr)
                        stress_ratios["pole"] = max(stress_ratios.get("pole", 0.0), sh_sr)

            # Mass summary from .rpt
            m_mass = re.search(r"TOTAL\s+MASS\s*[:=]?\s*([\d.]+)\s*kg", rpt_text, re.I)
            if m_mass:
                total_mass_kg = float(m_mass.group(1))

            # Rotations (sway & twist)
            rot_matches = re.findall(
                r"^\s*\d+\s+[\d.]+\s+\d+\s+([+-]?[\d.]+)\s+\d+\s+([+-]?[\d.]+)\s+\d+\s+([+-]?[\d.]+)",
                rpt_text,
                re.M,
            )
            for x_r, y_r, z_r in rot_matches:
                sway = max(abs(float(x_r)), abs(float(y_r)))
                twist = abs(float(z_r))
                if sway > max_sway_deg:
                    max_sway_deg = sway
                if twist > max_twist_deg:
                    max_twist_deg = twist

        # 2) Parse .p1 for displacements and reactions
        if p1_text:
            disp_matches = re.findall(
                r"^\s*\d+\s+([+-]?[\d.]+)\s+([+-]?[\d.]+)\s+([+-]?[\d.]+)",
                p1_text,
                re.M,
            )
            for dx, dy, _dz in disp_matches:
                try:
                    d_h = (float(dx) ** 2 + float(dy) ** 2) ** 0.5
                    if d_h > max_displacement_m:
                        max_displacement_m = d_h
                except ValueError:
                    pass

            rx_matches = re.findall(
                r"^\s*\d+\s+([+-]?[\d.]+)\s+([+-]?[\d.]+)\s+([+-]?[\d.]+)",
                p1_text,
                re.M,
            )
            for fx, fy, fz in rx_matches:
                try:
                    fz_val = float(fz)
                    shear = (float(fx) ** 2 + float(fy) ** 2) ** 0.5
                    if fz_val > pu_max_kn:
                        pu_max_kn = fz_val
                    if fz_val < 0 and abs(fz_val) > tu_max_kn:
                        tu_max_kn = abs(fz_val)
                    if shear > vu_max_kn:
                        vu_max_kn = shear
                except ValueError:
                    pass

        # 3) Fallback / Enhance from Narrative Pages (Resume Analisa Struktur & Anchor Bolt Lampiran)
        narrative_full = "\n".join(narrative_pages)

        # Stress ratios from summary table
        if not stress_ratios:
            m_leg_sr = re.search(r"Leg\s*[:=\|]?\s*([\d.]+)%?", narrative_full, re.I)
            if m_leg_sr:
                v = float(m_leg_sr.group(1))
                stress_ratios["leg"] = v / 100.0 if v > 1.5 else v

            m_brc_sr = re.search(r"(?:Bracing|Diagonal)\s*[:=\|]?\s*([\d.]+)%?", narrative_full, re.I)
            if m_brc_sr:
                v = float(m_brc_sr.group(1))
                stress_ratios["bracing"] = v / 100.0 if v > 1.5 else v

            m_hor_sr = re.search(r"Horizontal\s*[:=\|]?\s*([\d.]+)%?", narrative_full, re.I)
            if m_hor_sr:
                v = float(m_hor_sr.group(1))
                stress_ratios["horizontal"] = v / 100.0 if v > 1.5 else v

        # Max governing SR
        gov_sr = max(stress_ratios.values()) if stress_ratios else 0.0
        stress_ratios["overall"] = gov_sr
        stress_ratios["max_ratio"] = gov_sr

        gov_klr = max(slenderness.values()) if slenderness else 0.0
        slenderness["overall"] = gov_klr
        slenderness["max_klr"] = gov_klr

        # Deformations fallback
        if max_sway_deg == 0.0:
            m_sway = re.search(r"(?:Sway|Kemiringan)\s*[:=\|]?\s*([\d.]+)\s*(?:deg|°)?", narrative_full, re.I)
            if m_sway:
                max_sway_deg = float(m_sway.group(1))

        if max_twist_deg == 0.0:
            m_twist = re.search(r"(?:Twist|Puntir)\s*[:=\|]?\s*([\d.]+)\s*(?:deg|°)?", narrative_full, re.I)
            if m_twist:
                max_twist_deg = float(m_twist.group(1))

        if max_displacement_m == 0.0:
            m_disp = re.search(r"(?:Displacement|Defleksi)\s*[:=\|]?\s*([\d.]+)\s*(?:mm|m)?", narrative_full, re.I)
            if m_disp:
                d_val = float(m_disp.group(1))
                max_displacement_m = d_val / 1000.0 if d_val > 1.0 else d_val

        # Anchor Bolt & Baseplate from Anchor Bolt Analysis page
        m_anc = re.search(r"(?:Anchor\s*Bolt\s*Interaction|Interaction\s*Ratio|T\s*/\s*phi_?t\s*R_?n)\s*[:=\|]?\s*([\d.]+)", narrative_full, re.I)
        if m_anc:
            anchor_interaction = float(m_anc.group(1))
            anchor_tension = anchor_interaction

        m_bp = re.search(r"(?:Base\s*Plate\s*Ratio|t_?req\s*/\s*t_?ext)\s*[:=\|]?\s*([\d.]+)", narrative_full, re.I)
        if m_bp:
            baseplate_ratio = float(m_bp.group(1))

        # Overall Status
        is_safe = gov_sr <= 1.0 and anchor_interaction <= 1.0 and baseplate_ratio <= 1.0
        status_label = "NO NEED STRENGTHENING" if is_safe else "NEED STRENGTHENING"

        summary = {
            "stress_ratios": {k: round(v, 3) for k, v in stress_ratios.items()},
            "slenderness": {k: round(v, 1) for k, v in slenderness.items()},
            "max_sr": round(gov_sr, 3),
            "displacement_m": round(max_displacement_m, 4),
            "displacement_mm": round(max_displacement_m * 1000.0, 1),
            "twist_deg": round(max_twist_deg, 4),
            "sway_deg": round(max_sway_deg, 4),
            "total_mass_kg": round(total_mass_kg, 1),
            "reactions": {
                "pu_max_kn": round(pu_max_kn, 2),
                "tu_max_kn": round(tu_max_kn, 2),
                "vu_max_kn": round(vu_max_kn, 2),
                "max_comp_kn": round(pu_max_kn, 2),
                "max_uplift_kn": round(tu_max_kn, 2),
                "max_shear_kn": round(vu_max_kn, 2),
            },
            "anchor_baseplate": {
                "anchor_interaction_ratio": round(anchor_interaction, 3),
                "anchor_tension_ratio": round(anchor_tension, 3),
                "baseplate_ratio": round(baseplate_ratio, 3),
                "anchor_status": "AMAN" if anchor_interaction <= 1.0 else "OVERSTRESS",
                "baseplate_status": "AMAN" if baseplate_ratio <= 1.0 else "OVERSTRESS",
            },
            "status": status_label,
        }

        return summary, member_checks

    @staticmethod
    def build_zip_archive(extracted_data: dict[str, Any]) -> bytes:
        """Package clean .td, .twr, .rpt, .p1 and summaries into an organized in-memory zip archive."""
        buf = io.BytesIO()
        site_meta = extracted_data.get("site_metadata") or {}
        site_id = site_meta.get("site_id") or "SITE"
        scenarios = extracted_data.get("scenarios") or {}

        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            # 1. Metadata JSON
            meta_json = json.dumps(extracted_data, indent=2, ensure_ascii=False)
            zf.writestr("summary_metadata.json", meta_json)

            # 2. Device Inventory CSV
            dev_csv_io = io.StringIO()
            writer = csv.writer(dev_csv_io)
            writer.writerow(["Scenario", "Type", "Tag", "Status", "Tenant", "Leg", "Elev_Z_m", "Lib_Name", "Azimuth_deg", "Mass_kg", "Note"])

            for sc_name, sc_data in scenarios.items():
                devs = sc_data.get("devices") or {}
                for ant in devs.get("antennas", []):
                    writer.writerow([
                        sc_name, "ANTENNA", ant.get("tag", ""), ant.get("status", ""),
                        ant.get("tenant", ""), ant.get("leg", ""), ant.get("elev_z_m", 0),
                        ant.get("lib_name", ""), ant.get("azimuth_deg", 0), ant.get("mass_kg", 0),
                        ant.get("note", ""),
                    ])
                for lin in devs.get("linear", []):
                    writer.writerow([
                        sc_name, "LINEAR", lin.get("tag", ""), lin.get("status", ""),
                        "-", "-", lin.get("zt_m", 0), lin.get("lib_name", ""), "-", "-", lin.get("note", ""),
                    ])

                # 3. Clean MS-Tower text files
                mst_files = sc_data.get("mst_files") or {}
                for ext in ("td", "twr", "rpt", "p1"):
                    content = mst_files.get(ext) or ""
                    if content.strip():
                        fname = f"{sc_name}/{site_id}_{sc_name}.{ext}"
                        zf.writestr(fname, content.encode("cp437", errors="replace"))

            zf.writestr("device_inventory.csv", dev_csv_io.getvalue())

        return buf.getvalue()
