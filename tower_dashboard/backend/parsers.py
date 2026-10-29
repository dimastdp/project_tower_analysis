"""Pure parsers: bytes/text in, plain Python structures out. Never touches the DB."""
from pathlib import Path
import math
import re
import struct

import pandas as pd

NUM = r"[+-]?\d+\.\d+E[+-]\d+"
# Note: Fortran fixed-width E12.5 in .mst files often has NO space before a negative sign
NODE_PATTERN = re.compile(
    rf"^\s*(\d+)\s*({NUM})\s*({NUM})\s*({NUM})\s+(\d{{6}})\s+([+-]?\d+)"
)
MEMBER_PATTERN = re.compile(
    r"^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+\.\d+)"
)
SECTION_PATTERN = re.compile(
    rf"^\s*(\d+)\s*({NUM})\s*({NUM})\s*({NUM})\s*({NUM})\s*({NUM})\s*({NUM})\s*({NUM})\s*([A-Za-z0-9_+.-]+)"
)
DIM_FROM_NAME = re.compile(r"(\d+(?:\.\d+)?)\s*[Xx]\s*(\d+(?:\.\d+)?)\s*[Xx]\s*(\d+(?:\.\d+)?)")


def is_structural(node: dict) -> bool:
    """Skip helper or dummy reference nodes (flag == -1 or coordinate > 1e5)."""
    return (
        node["flag"] != -1
        and abs(node["x"]) <= 1e5
        and abs(node["y"]) <= 1e5
        and abs(node["z"]) <= 1e5
    )


def parse_section_dimensions(sec_name: str, a_m2: float, iy_m4: float) -> dict:
    """Derive b_mm, t_mm, r_min_mm from section name (e.g. EA70X70X7, STA70X70X7) and A, I."""
    a_mm2 = max(a_m2 * 1e6, 1.0)
    i_mm4 = max(iy_m4 * 1e12, 1.0)
    rx_mm = (i_mm4 / a_mm2) ** 0.5
    m = DIM_FROM_NAME.search(sec_name or "")
    if m:
        b_mm = float(m.group(1))
        t_mm = float(m.group(3))
    else:
        b_mm = max((a_mm2 * 3.5) ** 0.5, 40.0)
        t_mm = max(a_mm2 / (2.0 * b_mm), 4.0)
    # For equal angles (EA), minimum radius of gyration r_v ≈ 0.195 * b (or 0.64 * rx)
    r_min_mm = round(min(rx_mm, 0.195 * b_mm), 2) if "EA" in (sec_name or "").upper() else round(rx_mm * 0.78, 2)
    return {
        "ag_mm2": round(a_mm2, 1),
        "b_mm": round(b_mm, 1),
        "t_mm": round(t_mm, 1),
        "rx_mm": round(rx_mm, 2),
        "r_min_mm": max(r_min_mm, 5.0),
    }


def parse_mst_content(raw_bytes: bytes):
    """Extract the ASCII DAT~ block of a .mst file: node coordinates, members, and sections."""
    content = raw_bytes.decode("latin1")
    start_idx = content.find("DAT~")
    if start_idx == -1:
        raise ValueError("ASCII DAT~ block not found in the .mst file.")
    end_idx = content.find("AL4~", start_idx)
    dat_block = content[start_idx:end_idx] if end_idx != -1 else content[start_idx:]
    lines = [ln.strip() for ln in dat_block.splitlines() if ln.strip()]

    nodes: dict[int, dict] = {}
    members: list[dict] = []
    sections: dict[int, dict] = {}
    seq = 1
    for line in lines:
        m_node = NODE_PATTERN.match(line)
        if m_node:
            nodes[seq] = {
                "label": int(m_node.group(1)),
                "x": float(m_node.group(2)),
                "y": float(m_node.group(3)),
                "z": float(m_node.group(4)),
                "restraint": m_node.group(5),
                "flag": int(m_node.group(6)),
            }
            seq += 1
            continue

        m_memb = MEMBER_PATTERN.match(line)
        if m_memb:
            members.append(
                {
                    "id": int(m_memb.group(1)),
                    "ni": int(m_memb.group(2)),
                    "nj": int(m_memb.group(3)),
                    "sec_id": int(m_memb.group(5)),
                    "length": float(m_memb.group(8)),
                }
            )
            continue

        m_sec = SECTION_PATTERN.match(line)
        if m_sec:
            sid = int(m_sec.group(1))
            j_m4 = float(m_sec.group(2))
            iy_m4 = float(m_sec.group(3))
            iz_m4 = float(m_sec.group(4))
            a_m2 = float(m_sec.group(5))
            name = m_sec.group(9).strip()
            dims = parse_section_dimensions(name, a_m2, iy_m4)
            sections[sid] = {
                "sec_id": sid,
                "sec_name": name,
                "j_m4": j_m4,
                "iy_m4": iy_m4,
                "iz_m4": iz_m4,
                "a_m2": a_m2,
                **dims,
            }

    # Normalize structural node Z so the tower base sits at Z = 0.0 m
    struct_z = [n["z"] for n in nodes.values() if is_structural(n)]
    if struct_z:
        z_min = min(struct_z)
        if abs(z_min) > 1e-6:
            for n in nodes.values():
                if is_structural(n):
                    n["z"] = round(n["z"] - z_min, 5)

    for m in members:
        sec = sections.get(m["sec_id"])
        if sec:
            m["sec_name"] = sec["sec_name"]
            m["a_m2"] = sec["a_m2"]
            m["iy_m4"] = sec["iy_m4"]
            m["iz_m4"] = sec["iz_m4"]
            m["j_m4"] = sec["j_m4"]

    return nodes, members


def parse_mst_twr_block(raw_bytes: bytes) -> dict:
    """Extract embedded TWR~ parameters, ANCILLARIES inventory, LINEAR items, and inline $LIBRARY definitions."""
    content = raw_bytes.decode("latin1", errors="ignore")
    idx = content.find("TWR~")
    if idx == -1:
        return {"vb_ms": None, "exposure": "C", "ancillaries": [], "linear_ancillaries": [], "inline_devices": []}
    end_idx = content.find("OUT~", idx)
    twr_text = content[idx:end_idx] if end_idx != -1 else content[idx:idx + 30000]

    vb_ms = None
    m_vb = re.search(r"^\s*VB\s+([0-9.]+)", twr_text, re.M)
    if m_vb:
        vb_ms = float(m_vb.group(1))

    exposure = "C"
    m_tcat = re.search(r"\bTCAT\s+([1234])", twr_text)
    if m_tcat:
        tcat_map = {"1": "B", "2": "B", "3": "C", "4": "D"}
        exposure = tcat_map.get(m_tcat.group(1), "C")

    in_anc = False
    in_linear = False
    in_inline_lib = False
    in_inline_lin_lib = False
    status = "EXISTING"
    grouped: dict[tuple[str, str, str, str, float], int] = {}
    linear_ancillaries: list[dict] = []
    inline_lib_lines: list[str] = []
    inline_lin_lib_names: set[str] = set()

    for raw_ln in twr_text.splitlines():
        ln = raw_ln.strip()
        if not ln:
            continue
        u_ln = ln.upper()
        if u_ln.startswith("ANCILLARIES"):
            in_anc = True
            in_linear = False
            in_inline_lib = False
            continue
        if u_ln.startswith("LINEAR"):
            in_anc = False
            in_linear = True
            status = "EXISTING"
            continue
        if (in_anc or in_linear) and u_ln.startswith("END"):
            in_anc = False
            in_linear = False
        if "$LIBRARY" in u_ln and "ANTENNA" in u_ln:
            in_anc = False
            in_linear = False
            in_inline_lib = True
            in_inline_lin_lib = False
            continue
        if u_ln.startswith("$LIBRARY TANGGA"):
            in_inline_lib = False
            in_inline_lin_lib = True
            continue
        if in_inline_lin_lib:
            if u_ln.startswith("END"):
                in_inline_lin_lib = False
            elif ln.startswith("$"):
                toks = ln.lstrip("$").strip().split()
                if len(toks) >= 4:
                    inline_lin_lib_names.add(toks[0].upper())
            continue
        if in_inline_lib:
            if u_ln.startswith("END"):
                in_inline_lib = False
            elif ln.startswith("$"):
                uncommented = ln.lstrip("$").strip()
                if uncommented:
                    inline_lib_lines.append(uncommented)
            continue

        if in_linear:
            if ln.startswith("$"):
                if "PROPOSED" in u_ln:
                    status = "PROPOSED"
                elif "EXISTING" in u_ln:
                    status = "EXISTING"
                continue
            m_lin = re.match(
                r"^(\S+)\s+XB\s+[+-]?[\d.]+\s+YB\s+[+-]?[\d.]+\s+ZB\s+([+-]?[\d.]+)\s+"
                r"XT\s+[+-]?[\d.]+\s+YT\s+[+-]?[\d.]+\s+ZT\s+([+-]?[\d.]+)\s+LIB\s+(\S+)(.*)$",
                ln,
                re.I,
            )
            if m_lin:
                ltag, zb_s, zt_s, llib, lrest = m_lin.groups()
                linear_ancillaries.append(
                    {
                        "tag": ltag,
                        "status": status,
                        "lib_name": llib,
                        "zb_m": float(zb_s),
                        "zt_m": float(zt_s),
                        "in_inline_lib": llib.upper() in inline_lin_lib_names,
                        "comment": lrest.split("$", 1)[1].strip() if "$" in lrest else "",
                    }
                )
            continue

        if not in_anc:
            continue
        if ln.startswith("$"):
            u = ln.upper()
            if "PROPOSED" in u:
                status = "PROPOSED"
            elif "EXISTING" in u:
                status = "EXISTING"
            continue

        m = re.match(
            r"^(\S+)\s+XA\s+([+-]?[\d.]+)\s+YA\s+([+-]?[\d.]+)\s+ZA\s+([+-]?[\d.]+)\s+LIB\s+(\S+)(.*)$",
            ln,
            re.I,
        )
        if m:
            tag, xa_str, ya_str, za_str, lib_name, rest = m.groups()
            xa = round(float(xa_str), 2)
            ya = round(float(ya_str), 2)
            za = round(float(za_str), 2)
            m_ang = re.search(r"\bANG\s+([+-]?[\d.]+)", rest, re.I)
            ang = round(float(m_ang.group(1)), 1) if m_ang else 0.0
            comment = rest.split("$", 1)[1].strip() if "$" in rest else ""
            row_status = "PROPOSED" if (status == "PROPOSED" or tag.upper().startswith("P")) else "EXISTING"

            # Derive tenant and face/leg from comment or XA/YA quadrant
            c_up = comment.upper()
            if "TSEL" in c_up or "TELKOMSEL" in c_up:
                tenant = "TELKOMSEL"
            elif "XL" in c_up or "SMART" in c_up:
                tenant = "XLSMART"
            elif "IOH" in c_up or "ISAT" in c_up or "INDOSAT" in c_up:
                tenant = "IOH"
            elif "SURGE" in c_up:
                tenant = "SURGE"
            else:
                tenant = "EXISTING" if row_status == "EXISTING" else "PROPOSED"

            m_leg = re.search(r"LEG\s*([ABCD])", c_up)
            if m_leg:
                face = m_leg.group(1)
            elif xa >= 0 and ya >= 0:
                face = "A"
            elif xa >= 0 and ya < 0:
                face = "B"
            elif xa < 0 and ya < 0:
                face = "C"
            else:
                face = "D"

            note = comment if comment else tag
            mounting = f"LEG {face} [{xa:+.2f},{ya:+.2f},{ang:.0f}°] {note}"
            key = (row_status, tenant, lib_name, mounting, za)
            grouped[key] = grouped.get(key, 0) + 1

    ancillaries = [
        {
            "status": st,
            "tenant": ten,
            "device_name": dev,
            "mounting_name": mnt,
            "elev_z_m": za,
            "qty": qty,
        }
        for (st, ten, dev, mnt, za), qty in grouped.items()
    ]

    inline_df = parse_ancillary_lib("\n".join(inline_lib_lines)) if inline_lib_lines else pd.DataFrame()
    inline_devices = inline_df.to_dict("records") if not inline_df.empty else []
    # Also normalize GSM-2.50 -> GSM2.5 alias if referenced without hyphen
    extra_aliases = []
    for d in inline_devices:
        no_hyph = d["device_name"].replace("-", "")
        if no_hyph != d["device_name"]:
            extra_aliases.append({**d, "device_name": no_hyph})
    inline_devices.extend(extra_aliases)

    for la in linear_ancillaries:
        la["in_inline_lib"] = la["lib_name"].upper() in inline_lin_lib_names

    return {
        "vb_ms": vb_ms,
        "exposure": exposure,
        "ancillaries": ancillaries,
        "linear_ancillaries": linear_ancillaries,
        "inline_devices": inline_devices,
    }


def parse_mst_embedded_results(raw_bytes: bytes) -> dict:
    """Extract ground-to-base elevation z_base_m, RPT~ member capacity table, Twist/Sway/Displacement, and Support Reactions."""
    content = raw_bytes.decode("latin1", errors="ignore")

    # 1) Ground-to-base rooftop elevation z_base_m from raw DAT~ coordinates before normalization
    z_base_m = 0.0
    idx_dat = content.find("DAT~")
    if idx_dat != -1:
        end_dat = content.find("AL4~", idx_dat)
        dat_slice = content[idx_dat:end_dat] if end_dat != -1 else content[idx_dat:idx_dat + 40000]
        raw_zs = []
        for line in dat_slice.splitlines():
            m = NODE_PATTERN.match(line.strip())
            if m:
                z_val = float(m.group(4))
                flag_val = int(m.group(6))
                if flag_val != -1 and abs(z_val) <= 1e5:
                    raw_zs.append(z_val)
        if raw_zs:
            z_base_m = round(min(raw_zs), 3)

    # 2) Parse RPT~ member check table, Twist/Sway/Displacement, and Support Reactions
    rpt_by_member: dict[int, dict] = {}
    sr_summary: dict[str, dict] = {}
    twist_sway_disp = {
        "sway_x_deg": 0.0,
        "sway_y_deg": 0.0,
        "sway_max_deg": 0.0,
        "twist_z_deg": 0.0,
        "disp_x_mm": 0.0,
        "disp_y_mm": 0.0,
        "disp_h_mm": 0.0,
        "disp_z_mm": 0.0,
    }
    mst_reactions = {
        "pu_max_kn": 0.0,
        "tu_max_kn": 0.0,
        "vu_max_kn": 0.0,
        "dead_1_2d_kn": 0.0,
        "by_node": {},
    }

    idx_rpt = content.find("RPT~")
    if idx_rpt != -1:
        rpt_text = content[idx_rpt:]
        pat = re.compile(
            r"^\s*(\d+)\s+(\d+)(?:-\s*(\d+))?\s+([A-Z0-9]+)\s+(\S+)\s+(\d+)\s+(\d+)\s+"
            r"(\S+)\s+(\d+)\s+(\S+)\s+(\d+[vyx]?)\s+(\d+)\s+(\d+\.\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)",
            re.M,
        )
        for (
            pnl, m1, m2, typ, sec, _fy, _nb, _c_case, c_pu, curve, klr, c_pn, c_sr,
            _t_case, t_pu, t_pn, t_sr
        ) in pat.findall(rpt_text):
            sr_c = float(c_sr)
            sr_t = float(t_sr) if t_sr != "-" else 0.0
            gov_c = sr_c >= sr_t
            sr = max(sr_c, sr_t)
            pu_val = float(c_pu) if gov_c else (float(t_pu) if t_pu != "-" else 0.0)
            pn_val = float(c_pn) if gov_c else (float(t_pn) if t_pn != "-" else 1.0)
            klr_num = float(re.sub(r"[^0-9.]", "", klr) or 0.0)
            i1 = int(m1)
            i2 = int(m2) if m2 else i1
            for mid in range(i1, i2 + 1):
                prev = rpt_by_member.get(mid)
                if prev is None or sr > prev["stress_ratio"]:
                    rpt_by_member[mid] = {
                        "id": mid,
                        "pnl": int(pnl),
                        "typ": typ,
                        "sec_name": sec,
                        "pu_kn": pu_val,
                        "phi_pn_kn": pn_val,
                        "kl_over_r": klr_num,
                        "curve": curve,
                        "stress_ratio": round(sr, 3),
                    }

        # Summarize governing SR per category (LEG, BRACING, HORIZONTAL, OVERALL)
        for mid, info in rpt_by_member.items():
            t = info["typ"].upper()
            if t == "LEG":
                cat_key = "leg"
            elif t in ("BRC", "KBR", "XBR", "DBR", "MBR"):
                cat_key = "bracing"
            elif t in ("HOR", "RED", "PBR", "PB", "HBR"):
                cat_key = "horizontal"
            else:
                cat_key = "other"
            if cat_key not in sr_summary or info["stress_ratio"] > sr_summary[cat_key]["stress_ratio"]:
                sr_summary[cat_key] = dict(info)
            if "overall" not in sr_summary or info["stress_ratio"] > sr_summary["overall"]["stress_ratio"]:
                sr_summary["overall"] = dict(info)

        # Parse ENVELOPE OF TOWER ROTATIONS (Degrees about global axes, 3 node plane)
        rot_m = re.search(
            r"ENVELOPE OF TOWER ROTATIONS \(Degrees about global axes,\s*3 node plane\)(.*?)(?:ENVELOPE|ROTATIONS OF ANCILLARY|--|\Z)",
            rpt_text,
            re.S,
        )
        if rot_m:
            sx, sy, tz = 0.0, 0.0, 0.0
            for ln in rot_m.group(1).splitlines():
                m_rot = re.match(r"^\s*\d+\s+([\d.]+)\s+\d+\s+([\d.]+)\s+\d+\s+([\d.]+)\s+\d+\s+([\d.]+)", ln)
                if m_rot:
                    sx = max(sx, float(m_rot.group(2)))
                    sy = max(sy, float(m_rot.group(3)))
                    tz = max(tz, float(m_rot.group(4)))
            twist_sway_disp["sway_x_deg"] = round(sx, 4)
            twist_sway_disp["sway_y_deg"] = round(sy, 4)
            twist_sway_disp["sway_max_deg"] = round(max(sx, sy), 4)
            twist_sway_disp["twist_z_deg"] = round(tz, 4)

        # Parse -- N O D E   D I S P L A C E M E N T S --
        disp_idx = rpt_text.find("N O D E   D I S P L A C E M E N T S")
        if disp_idx != -1:
            dx_max, dy_max, dh_max, dz_max = 0.0, 0.0, 0.0, 0.0
            for ln in rpt_text[disp_idx:].splitlines():
                nums = re.findall(r"[+-]?\d+\.\d+", ln)
                if len(nums) == 6:
                    dx = abs(float(nums[0]))
                    dy = abs(float(nums[1]))
                    dz = abs(float(nums[2]))
                    dx_max = max(dx_max, dx)
                    dy_max = max(dy_max, dy)
                    dh_max = max(dh_max, math.hypot(dx, dy))
                    dz_max = max(dz_max, dz)
            twist_sway_disp["disp_x_mm"] = round(dx_max * 1000.0, 2)
            twist_sway_disp["disp_y_mm"] = round(dy_max * 1000.0, 2)
            twist_sway_disp["disp_h_mm"] = round(dh_max * 1000.0, 2)
            twist_sway_disp["disp_z_mm"] = round(dz_max * 1000.0, 2)

        # Parse SUPPORT REACTIONS (Applied to tower) from RPT~
        sr_idx = rpt_text.find("SUPPORT REACTIONS (Applied to tower)")
        if sr_idx != -1:
            sr_end = rpt_text.find("SUPPORT REACTIONS (Along Leg)", sr_idx)
            if sr_end == -1:
                sr_end = rpt_text.find("Mstower V6 Ancillary", sr_idx)
            sr_block = rpt_text[sr_idx:sr_end] if sr_end != -1 else rpt_text[sr_idx:sr_idx + 18000]
            curr_case = 0
            by_node: dict[int, dict[str, float]] = {}
            pu_500_660 = 0.0
            tu_500_660 = 0.0
            vu_500_660 = 0.0
            pu_all = 0.0
            tu_all = 0.0
            vu_all = 0.0
            dead_1_2d = 0.0
            for ln in sr_block.splitlines():
                m_res = re.match(r"^\s*Resultant\s+([+-]?\d+\.\d+)\s+([+-]?\d+\.\d+)\s+([+-]?\d+\.\d+)", ln)
                if m_res and curr_case == 500:
                    dead_1_2d = round(abs(float(m_res.group(3))), 2)
                    continue
                m_row = re.match(
                    r"^\s*(?:(\d+)\s+)?(\d+)\s+([+-]?\d+\.\d+)\s+([+-]?\d+\.\d+)\s+([+-]?\d+\.\d+)\s+([+-]?\d+\.\d+)\s+([+-]?\d+\.\d+)\s+([+-]?\d+\.\d+)",
                    ln,
                )
                if m_row:
                    if m_row.group(1):
                        curr_case = int(m_row.group(1))
                    n_lbl = int(m_row.group(2))
                    fx = float(m_row.group(3))
                    fy = float(m_row.group(4))
                    fz = float(m_row.group(5))
                    pu = max(0.0, fz)
                    tu = max(0.0, -fz)
                    vu = math.hypot(fx, fy)
                    if 500 <= curr_case < 3000:
                        pu_all = max(pu_all, pu)
                        tu_all = max(tu_all, tu)
                        vu_all = max(vu_all, vu)
                    if 500 <= curr_case <= 660:
                        pu_500_660 = max(pu_500_660, pu)
                        tu_500_660 = max(tu_500_660, tu)
                        vu_500_660 = max(vu_500_660, vu)
                        nd_rec = by_node.setdefault(n_lbl, {"pu_kn": 0.0, "tu_kn": 0.0, "vu_kn": 0.0})
                        nd_rec["pu_kn"] = round(max(nd_rec["pu_kn"], pu), 2)
                        nd_rec["tu_kn"] = round(max(nd_rec["tu_kn"], tu), 2)
                        nd_rec["vu_kn"] = round(max(nd_rec["vu_kn"], vu), 2)
            mst_reactions["pu_max_kn"] = round(pu_500_660 or pu_all, 2)
            mst_reactions["tu_max_kn"] = round(tu_500_660 or tu_all, 2)
            mst_reactions["vu_max_kn"] = round(vu_500_660 or vu_all, 2)
            mst_reactions["dead_1_2d_kn"] = dead_1_2d
            mst_reactions["by_node"] = by_node

    # 3) Fallback to binary RCT01 block in RCT~ if RPT~ did not contain SUPPORT REACTIONS
    if mst_reactions["pu_max_kn"] == 0.0:
        idx_rct = raw_bytes.find(b"RCT~")
        idx_rct_end = raw_bytes.find(b"0AN~", idx_rct) if idx_rct != -1 else -1
        if idx_rct != -1 and idx_rct_end != -1:
            chunk = raw_bytes[idx_rct:idx_rct_end]
            p_rct = chunk.find(b"RCT01")
            if p_rct != -1:
                sub = chunk[p_rct:]
                nsup = 0
                while 48 + (nsup + 1) * 4 <= len(sub):
                    val = struct.unpack("<i", sub[48 + nsup * 4:48 + (nsup + 1) * 4])[0]
                    if 1 <= val <= 100000:
                        nsup += 1
                    else:
                        break
                if nsup > 0:
                    pos = 96 + 6 * nsup
                    rec_len = (1 + nsup) * 24 + 24
                    ncases = (len(sub) - pos) // rec_len
                    max_pu, max_tu, max_vu = 0.0, 0.0, 0.0
                    for ic in range(ncases):
                        base = pos + ic * rec_len
                        for s in range(nsup):
                            s_off = base + 24 * (1 + s)
                            if s_off + 24 <= len(sub):
                                fx, fy, fz, _mx, _my, _mz = struct.unpack("<6f", sub[s_off:s_off + 24])
                                if all(abs(x) < 5000.0 for x in (fx, fy, fz)):
                                    max_pu = max(max_pu, fz)
                                    max_tu = max(max_tu, -fz)
                                    max_vu = max(max_vu, math.hypot(fx, fy))
                    mst_reactions["pu_max_kn"] = round(max_pu, 2)
                    mst_reactions["tu_max_kn"] = round(max_tu, 2)
                    mst_reactions["vu_max_kn"] = round(max_vu, 2)

    return {
        "z_base_m": z_base_m,
        "rpt_by_member": rpt_by_member,
        "sr_summary": sr_summary,
        "twist_sway_disp": twist_sway_disp,
        "mst_reactions": mst_reactions,
    }


_RPT_F = r"[+-]?\d+\.\d+"
_RPT_MEMBER_HEAD = re.compile(r"^\s*(\d+)\s+(\d+)(?:-\s*(\d+))?\s+([A-Z]{2,4})\s+(\S+)\s+(.*)$")
_RPT_REACT_ROW = re.compile(
    rf"^\s*(?:(\d+)\s+)?(\d+)\s+({_RPT_F})\s+({_RPT_F})\s+({_RPT_F})\s+({_RPT_F})\s+({_RPT_F})\s+({_RPT_F})\s*$"
)
_RPT_RESULTANT = re.compile(
    rf"^\s*Resultant\s+({_RPT_F})\s+({_RPT_F})\s+({_RPT_F})\s+({_RPT_F})\s+({_RPT_F})\s+({_RPT_F})"
)
_RPT_ENV_ROW = re.compile(
    r"^\s*(\d+)\s+([\d.]+)\s+(\d+)\s+([\d.]+)\s+(\d+)\s+([\d.]+)\s+(\d+)\s+([\d.]+)\s*$"
)
_RPT_ANC_HEAD = re.compile(
    rf"^\s(\S.{{0,16}}?)\s+({_RPT_F})\s+({_RPT_F})\s+(\d+)\s+({_RPT_F})\s+({_RPT_F})\s+({_RPT_F})\s*$"
)
_RPT_ANC_CONT = re.compile(rf"^\s{{20,}}(\d+)\s+({_RPT_F})\s+({_RPT_F})\s+({_RPT_F})\s*$")
_RPT_DISP_ROW = re.compile(
    rf"^\s*(\d+)\s+({_RPT_F})\s+({_RPT_F})\s+({_RPT_F})\s+({_RPT_F})\s+({_RPT_F})\s+({_RPT_F})\s*$"
)
_RPT_NODE_CASE_ROW = re.compile(
    rf"^\s*(?:(\d+)\s+)?(\d+)\s+({_RPT_F})\s+({_RPT_F})\s+({_RPT_F})\s+({_RPT_F})\s+({_RPT_F})\s+({_RPT_F})\s*$"
)


def _rpt_text(raw_bytes: bytes) -> str:
    """Return the RPT~ block as clean text (DOS cp437 so 'φ' renders correctly)."""
    idx = raw_bytes.find(b"RPT~")
    if idx == -1:
        return ""
    end = raw_bytes.find(b"EOF~", idx)
    chunk = raw_bytes[idx:end if end != -1 else len(raw_bytes)]
    text = chunk.decode("cp437", errors="replace")
    return "".join(ch if (ch >= " " or ch in "\r\n\t") else " " for ch in text).replace("\r\n", "\n")


def _rpt_load_cases(lines: list[str], start: int) -> tuple[list[dict], int]:
    cases = []
    i = start
    while i < len(lines):
        m = re.match(r"^\s*(\d+)\s+([YN])\s+(.*?)\s*$", lines[i])
        if m:
            cases.append({"case": int(m.group(1)), "used": m.group(2), "title": m.group(3)})
        elif cases and lines[i].strip() == "":
            break
        i += 1
    return cases, i


def parse_mst_report(raw_bytes: bytes) -> dict:
    """Parse the complete MS Tower V6 report embedded in RPT~ into row-level tables.

    Sections: member checking (TIA-222-G), mass summary, support reactions (applied to
    tower & along leg), envelope of tower rotations, ancillary rotations, node displacements.
    """
    text = _rpt_text(raw_bytes)
    out: dict = {
        "available": bool(text),
        "header": {"program": "", "job": "", "title": [], "date": ""},
        "check_cases": [],
        "reaction_cases": [],
        "rotation_cases": [],
        "member_rows": [],
        "mass_summary": [],
        "mass_total_kg": 0.0,
        "centroid": None,
        "reactions": [],
        "reactions_leg": [],
        "rot_env_3node": [],
        "rot_env_leg": [],
        "ancillary_rot": [],
        "displacements": [],
        "raw_text": text,
    }
    if not text:
        return out

    lines = text.split("\n")
    hdr = out["header"]
    m_prog = re.search(r"(MSTOWER V6 Member checking[^\n]*)", text)
    hdr["program"] = m_prog.group(1).strip() if m_prog else "MSTOWER V6"

    section = "check"
    i = 0
    cur_case = None
    cur_disp = None
    cur_anc = None
    cur_node = 0
    disp_by_case: dict[int, dict] = {}
    react_by_case: dict[int, dict] = {}
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()

        # --- header / section switches -------------------------------------------------
        if s.startswith("Job:") and not hdr["job"]:
            hdr["job"] = s.split(":", 1)[1].strip()
        elif s.startswith("Title:") and not hdr["title"]:
            hdr["title"].append(s.split(":", 1)[1].strip())
            if i + 1 < len(lines) and lines[i + 1].startswith("   ") and lines[i + 1].strip() and ":" not in lines[i + 1]:
                hdr["title"].append(lines[i + 1].strip())
        elif s.startswith("Date:") and not hdr["date"]:
            hdr["date"] = s.split(":", 1)[1].strip()
        elif s.startswith("Mstower V6 Reactions"):
            section = "reactions"
        elif s.startswith("Mstower V6 Ancillary"):
            section = "rotations"
        elif s.startswith("SUPPORT REACTIONS (Applied"):
            section, cur_case = ("react" if not out["reactions"] else "skip"), None
        elif s.startswith("SUPPORT REACTIONS (Along"):
            section, cur_case = ("react_leg" if not out["reactions_leg"] else "skip"), None
        elif s.startswith("-- S U P P O R T   R E A C T I O N S --"):
            section = "an_react" if not out["reactions"] else "skip"
        elif s.startswith("-- S U M   O F") or s.startswith("-- R E S I D U A L S"):
            section = "skip"
        elif s.startswith("-- N O D E   D I S P L A C E M E N T S --"):
            section = "analysis"
        elif s.startswith("ENVELOPE OF TOWER ROTATIONS") and "3 node" in s:
            section = "env3"
        elif s.startswith("ENVELOPE OF TOWER ROTATIONS"):
            section = "envleg"
        elif s.startswith("ROTATIONS OF ANCILLARY"):
            section = "anc"
        elif s.startswith("-- I N P U T / A N A L Y S I S"):
            section = "analysis"
        elif s.startswith("Mass Summary"):
            section = "mass"
        elif s.startswith("-- L O A D   C A S E S --"):
            cases, j = _rpt_load_cases(lines, i + 2)
            key = {"check": "check_cases", "reactions": "reaction_cases", "rotations": "rotation_cases"}.get(section)
            if key and not out[key]:
                out[key] = cases
            i = j
            continue
        elif s.startswith("Centroid of supports:"):
            nums = re.findall(_RPT_F, s)
            if len(nums) == 3:
                out["centroid"] = [float(x) for x in nums]

        # --- section bodies ------------------------------------------------------------
        elif section == "check":
            m = _RPT_MEMBER_HEAD.match(ln)
            if m:
                toks = m.group(6).split()
                if len(toks) >= 19 and toks[0].isdigit():
                    out["member_rows"].append({
                        "pnl": int(m.group(1)), "m1": int(m.group(2)),
                        "m2": int(m.group(3)) if m.group(3) else None,
                        "typ": m.group(4), "size": m.group(5),
                        "fy": toks[0], "nb": toks[1],
                        "c_case": toks[2], "c_pu": toks[3], "curve": toks[4], "klr": toks[5],
                        "c_pn": toks[6], "c_sr": toks[7],
                        "t_case": toks[8], "t_pu": toks[9], "t_pn": toks[10], "t_sr": toks[11],
                        "j_case": toks[12], "j_pu": toks[13], "j_dia": toks[14], "j_grade": toks[15],
                        "j_type": toks[16], "j_pn": toks[17], "j_sr": toks[18],
                        "flags": "".join(toks[19:]),
                    })
        elif section == "mass":
            m = re.match(r"^\s*(\d+)\s+(\S+)\s+([YN])\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s*$", ln)
            if m:
                out["mass_summary"].append({
                    "sect": int(m.group(1)), "size": m.group(2), "flag": m.group(3),
                    "fy": int(m.group(4)), "length_m": float(m.group(5)), "mass_kg": float(m.group(6)),
                })
            elif re.match(r"^\s+[\d.]+\s*$", ln) and out["mass_summary"]:
                out["mass_total_kg"] = float(s)
        elif section in ("react", "react_leg"):
            key = "reactions" if section == "react" else "reactions_leg"
            m_res = _RPT_RESULTANT.match(ln)
            m_row = _RPT_REACT_ROW.match(ln)
            if m_res and cur_case is not None:
                cur_case["resultant"] = [float(m_res.group(k)) for k in range(1, 7)]
            elif m_row:
                if m_row.group(1):
                    cur_case = {"case": int(m_row.group(1)), "rows": [], "resultant": None}
                    out[key].append(cur_case)
                if cur_case is not None:
                    cur_case["rows"].append({
                        "id": int(m_row.group(2)),
                        "f": [float(m_row.group(k)) for k in range(3, 9)],
                    })
        elif section in ("env3", "envleg"):
            m = _RPT_ENV_ROW.match(ln)
            if m:
                (out["rot_env_3node"] if section == "env3" else out["rot_env_leg"]).append({
                    "pt": int(m.group(1)), "height": float(m.group(2)),
                    "lc_x": int(m.group(3)), "x_rot": float(m.group(4)),
                    "lc_y": int(m.group(5)), "y_rot": float(m.group(6)),
                    "lc_z": int(m.group(7)), "z_rot": float(m.group(8)),
                })
        elif section == "anc":
            m_h = _RPT_ANC_HEAD.match(ln)
            m_c = _RPT_ANC_CONT.match(ln)
            if m_c and cur_anc is not None:
                cur_anc["rows"].append({"case": int(m_c.group(1)), "rot": [float(m_c.group(k)) for k in (2, 3, 4)]})
            elif m_h:
                cur_anc = {
                    "name": m_h.group(1).strip(), "height": float(m_h.group(2)), "bearing": float(m_h.group(3)),
                    "rows": [{"case": int(m_h.group(4)), "rot": [float(m_h.group(k)) for k in (5, 6, 7)]}],
                }
                out["ancillary_rot"].append(cur_anc)
        elif section == "analysis":
            m_case = re.match(r"^\s*CASE\s+(\d+):\s*(.*?)\s*$", ln)
            m_d = _RPT_DISP_ROW.match(ln)
            m_nc = _RPT_NODE_CASE_ROW.match(ln)
            if m_case:
                cur_disp = {"case": int(m_case.group(1)), "title": m_case.group(2), "rows": []}
                out["displacements"].append(cur_disp)
            elif m_d and cur_disp is not None:
                cur_disp["rows"].append({"node": int(m_d.group(1)), "d": [float(m_d.group(k)) for k in range(2, 8)]})
            elif m_nc:
                # node-major layout: "Node Case X-Disp ..." -> regroup per case
                if m_nc.group(1):
                    cur_node = int(m_nc.group(1))
                case_no = int(m_nc.group(2))
                bucket = disp_by_case.get(case_no)
                if bucket is None:
                    bucket = {"case": case_no, "title": "", "rows": []}
                    disp_by_case[case_no] = bucket
                    out["displacements"].append(bucket)
                bucket["rows"].append({"node": cur_node, "d": [float(m_nc.group(k)) for k in range(3, 9)]})
        elif section == "an_react":
            m_nc = _RPT_NODE_CASE_ROW.match(ln)
            if m_nc:
                if m_nc.group(1):
                    cur_node = int(m_nc.group(1))
                case_no = int(m_nc.group(2))
                bucket = react_by_case.get(case_no)
                if bucket is None:
                    bucket = {"case": case_no, "rows": [], "resultant": None}
                    react_by_case[case_no] = bucket
                bucket["rows"].append({"id": cur_node, "f": [float(m_nc.group(k)) for k in range(3, 9)]})
        i += 1

    if react_by_case and not out["reactions"]:
        for case_no in sorted(react_by_case):
            b = react_by_case[case_no]
            b["resultant"] = [round(sum(r["f"][k] for r in b["rows"]), 3) for k in range(3)] + [0.0, 0.0, 0.0]
            b["resultant_partial"] = True
            out["reactions"].append(b)
    for case_list in (out["reactions"],):
        known = {c["case"] for c in out["reaction_cases"]}
        for c in case_list:
            if c["case"] not in known:
                out["reaction_cases"].append({"case": c["case"], "used": "Y", "title": ""})
                known.add(c["case"])

    return out


def summarize_geometry(nodes: dict[int, dict]) -> dict:
    """Height and top/bottom widths computed from the structural nodes."""
    pts = [n for n in nodes.values() if is_structural(n)]
    if not pts:
        return {"height_m": 0.0, "top_width_m": 0.0, "bot_width_m": 0.0}
    z_min = min(n["z"] for n in pts)
    z_max = max(n["z"] for n in pts)

    def width_at(z: float) -> float:
        level = [n for n in pts if abs(n["z"] - z) < 0.05]
        xs = [n["x"] for n in level]
        ys = [n["y"] for n in level]
        wx = (max(xs) - min(xs)) if xs else 0.0
        wy = (max(ys) - min(ys)) if ys else 0.0
        return round(max(wx, wy), 3)

    return {
        "height_m": round(z_max - z_min, 3),
        "top_width_m": width_at(z_max),
        "bot_width_m": width_at(z_min),
    }


CA_MAP = {"BOX": 1.4, "CYL": 1.2, "SH1": 1.26, "SHIELDED": 1.26, "UNITY": 1.0, "GRID": 0.6, "STD": 1.51, "RAD": 0.89}
CATEGORY_KEYWORDS = [
    "SMARTFREN", "TELKOMSEL", "H3I", "INDOSAT", "IOH", "XL", "SURGE", "MW", "MOUNTING", "MITRATEL"
]


def compute_tia_ca(shape_type: str, dim_m: float, af_m2: float) -> float:
    """Compute TIA-222-G Table 2-8 drag factor Ca (with MS Tower shape fallback)."""
    st = (shape_type or "BOX").upper()
    if st in ("SH1", "SHIELDED", "STD", "RAD", "UNITY", "GRID"):
        return CA_MAP.get(st, 1.2)
    return CA_MAP.get(st, 1.2)


def parse_ancillary_lib(lib_text: str) -> pd.DataFrame:
    """Extract the antenna and device catalog from ANCILLARY.lib / MTEL.lib."""
    devices = []
    current_category = "GENERAL"
    anc_section = lib_text.split("COEFFICIENTS")[0]

    for raw_line in anc_section.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("$"):
            clean = re.sub(r"[\$\=\-]+", " ", line).strip()
            if any(k in clean.upper() for k in CATEGORY_KEYWORDS):
                current_category = clean
            continue

        parts = line.split("$", 1)
        tokens = parts[0].strip().split()
        remark = parts[1].strip() if len(parts) > 1 else ""
        if len(tokens) < 6:
            continue
        try:
            dev_type = tokens[1].upper()
            dim_m = float(tokens[2])
            mass_kg = float(tokens[3])
            af_m2 = float(tokens[4])
            asf_m2 = float(tokens[5])
            ca_factor = compute_tia_ca(dev_type, dim_m, af_m2)
            devices.append(
                {
                    "category": current_category,
                    "device_name": tokens[0],
                    "shape_type": dev_type,
                    "dim_m": dim_m,
                    "mass_kg": mass_kg,
                    "af_m2": af_m2,
                    "asf_m2": asf_m2,
                    "ca_factor": ca_factor,
                    "epa_m2": round(af_m2 * ca_factor, 4),
                    "remark": remark,
                }
            )
        except ValueError:
            continue
    return pd.DataFrame(devices)


def format_lib_line(dev: dict) -> str:
    """Format a single device dict as a valid MS Tower ANCILLARY.lib line."""
    name = str(dev["device_name"]).strip()
    shape = str(dev.get("shape_type") or "BOX").strip().upper()
    dim_m = float(dev.get("dim_m") or 0.0)
    mass_kg = float(dev.get("mass_kg") or 0.0)
    af_m2 = float(dev.get("af_m2") or 0.0)
    asf_m2 = float(dev.get("asf_m2") or 0.0)
    remark = str(dev.get("remark") or "").strip()
    dx = round(af_m2 / dim_m, 3) if dim_m > 0 else 0.200
    dy = round(asf_m2 / dim_m, 3) if dim_m > 0 else 0.150
    dz = round(dim_m, 3)
    icon = 3 if shape in ("SH1", "SHIELDED", "STD", "RAD") else 14
    base = (
        f"{name:<13s} {shape:<8s} {dim_m:<6.3f} {mass_kg:<6.1f} "
        f"{af_m2:<8.4f} {asf_m2:<8.4f} 0    0    0    0     1    1    1    {icon:<3d}  "
        f"{dx:<6.3f} {dy:<6.3f} {dz:<6.3f}"
    )
    return f"{base} $ {remark}" if remark else base


def upsert_device_in_lib_file(lib_path: Path, dev: dict) -> None:
    """Insert or update a device row inside an MS Tower .lib file (before COEFFICIENTS/END)."""
    new_line = format_lib_line(dev)
    dev_name = str(dev["device_name"]).strip()
    category = str(dev.get("category") or "CUSTOM").strip()

    if not lib_path.exists():
        content = (
            "ANCILLARY\n"
            f"$=============================={category}==================================================\n"
            f"{new_line}\n"
            "END\nEOF\n"
        )
        lib_path.write_text(content, encoding="latin1")
        return

    raw_text = lib_path.read_text(encoding="latin1")
    lines = raw_text.splitlines()
    coeff_idx = next((i for i, l in enumerate(lines) if l.strip().upper().startswith("COEFFICIENTS")), len(lines))

    # 1) Check if device_name already exists in the ancillary section; if so, replace in place.
    for i in range(coeff_idx):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("$"):
            continue
        first_tok = stripped.split()[0]
        if first_tok.upper() == dev_name.upper():
            lines[i] = new_line
            lib_path.write_text("\n".join(lines) + "\n", encoding="latin1")
            return

    # 2) Otherwise insert before the first END preceding COEFFICIENTS.
    insert_at = coeff_idx
    for i in range(coeff_idx - 1, -1, -1):
        if lines[i].strip().upper() == "END":
            insert_at = i
            break

    lines.insert(insert_at, f"$--------------------------------------------------{category}---------------------------------------------")
    lines.insert(insert_at + 1, new_line)
    lib_path.write_text("\n".join(lines) + "\n", encoding="latin1")


def export_devices_as_lib(devices: list[dict], source_lib_path: Path | None = None) -> str:
    """Produce a complete MS Tower ANCILLARY .lib text from catalog_devices (preserving COEFFICIENTS tail if available)."""
    out = [
        "ANCILLARY",
        "$ Exported from Tower Dashboard",
        "$ name        type     Dim    mass   af       asf      aice zre  xcg  xicg  fcx  fcy  fzm  icon dx     dy     dz",
        "",
    ]
    by_cat: dict[str, list[dict]] = {}
    for d in devices:
        cat = (d.get("category") or "GENERAL").strip()
        by_cat.setdefault(cat, []).append(d)

    for cat, items in by_cat.items():
        out.append(f"$--------------------------------------------------{cat}---------------------------------------------")
        for d in items:
            out.append(format_lib_line(d))
        out.append("")

    out.append("END")

    if source_lib_path and source_lib_path.exists():
        raw = source_lib_path.read_text(encoding="latin1")
        if "COEFFICIENTS" in raw:
            tail = raw[raw.index("COEFFICIENTS"):]
            out.append("")
            out.append(tail.rstrip())
            return "\n".join(out) + "\n"

    out.append("EOF")
    return "\n".join(out) + "\n"


def _extract_prefix_and_dim(name: str) -> tuple[str, float | None]:
    up = (name or "").strip().upper()
    m_num = re.search(r"(\d+\.\d+|\d+)", up)
    num = float(m_num.group(1)) if m_num else None
    m_pre = re.match(r"^([A-Z]+)", up)
    prefix = m_pre.group(1) if m_pre else up
    return prefix, num


def compute_device_dimensions(dev: dict | None, fallback_name: str = "") -> dict:
    """Return physical 3D dimensions (length_m=height/diameter, width_m, depth_m, shape_type) from .lib row."""
    if dev and dev.get("dim_m"):
        shape = str(dev.get("shape_type") or "BOX").upper()
        dim_m = max(float(dev.get("dim_m") or 0.5), 0.15)
        af = float(dev.get("af_m2") or 0.0)
        asf = float(dev.get("asf_m2") or 0.0)
        if shape in ("SH1", "SHIELDED", "STD", "RAD"):
            return {
                "shape_type": shape,
                "length_m": round(dim_m, 3),
                "width_m": round(dim_m, 3),
                "depth_m": round(max(0.22, dim_m * 0.38), 3),
            }
        w = (af / dim_m) if (dim_m > 0 and af > 0) else 0.30
        d = (asf / dim_m) if (dim_m > 0 and asf > 0) else 0.18
        return {
            "shape_type": shape,
            "length_m": round(dim_m, 3),
            "width_m": round(min(max(w, 0.12), 1.20), 3),
            "depth_m": round(min(max(d, 0.10), 0.90), 3),
        }

    prefix, num = _extract_prefix_and_dim(fallback_name)
    dim_m = num if (num and 0.1 <= num <= 6.0) else 0.60
    shape = "SHIELDED" if prefix in ("MW", "SH", "DISH") else ("CYL" if prefix == "GSM" else "BOX")
    return {
        "shape_type": shape,
        "length_m": round(dim_m, 3),
        "width_m": round(0.35 if dim_m >= 1.0 else 0.28, 3),
        "depth_m": round(0.20 if dim_m >= 1.0 else 0.16, 3),
    }


def infer_device_placement(
    mounting_name: str | None,
    elev_z_m: float,
    height_m: float,
    top_w: float,
    bot_w: float,
    row_idx: int = 0,
) -> dict:
    """Resolve tower face ('A'|'B'|'C'|'D'), 3D coordinates (x_m, y_m, z_m), and azimuth from mounting_name."""
    mnt = (mounting_name or "").upper()
    face = None
    m_leg = re.search(r"LEG\s*([ABCD])", mnt)
    if m_leg:
        face = m_leg.group(1)
    elif "FACE A" in mnt or "UTARA" in mnt or "NORTH" in mnt:
        face = "A"
    elif "FACE B" in mnt or "TIMUR" in mnt or "EAST" in mnt:
        face = "B"
    elif "FACE C" in mnt or "SELATAN" in mnt or "SOUTH" in mnt:
        face = "C"
    elif "FACE D" in mnt or "BARAT" in mnt or "WEST" in mnt:
        face = "D"

    xa_raw, ya_raw, ang_raw = None, None, None
    m_coords = re.search(r"\[([+-]?\d+(?:\.\d+)?),([+-]?\d+(?:\.\d+)?),([+-]?\d+(?:\.\d+)?)°?\]", mnt)
    if m_coords:
        xa_raw = float(m_coords.group(1))
        ya_raw = float(m_coords.group(2))
        ang_raw = float(m_coords.group(3))

    if face is None:
        if xa_raw is not None and ya_raw is not None:
            if xa_raw >= 0 and ya_raw >= 0:
                face = "A"
            elif xa_raw >= 0 and ya_raw < 0:
                face = "B"
            elif xa_raw < 0 and ya_raw < 0:
                face = "C"
            else:
                face = "D"
        else:
            face = ("A", "B", "C", "D")[row_idx % 4]

    h_safe = max(height_m, 1.0)
    ratio = min(max(elev_z_m / h_safe, 0.0), 1.0)
    half_w = 0.5 * (bot_w - (bot_w - top_w) * ratio) if bot_w > 0 else 0.8

    quad_signs = {"A": (1.0, 1.0), "B": (1.0, -1.0), "C": (-1.0, -1.0), "D": (-1.0, 1.0)}
    sx, sy = quad_signs.get(face, (1.0, 1.0))
    spread = ((row_idx % 3) - 1) * 0.22
    standoff = 0.22 + (0.12 if xa_raw and abs(xa_raw) > 1.5 else 0.0)
    x_m = round(sx * (half_w + standoff) + (sy * spread * 0.5), 3)
    y_m = round(sy * (half_w + standoff) - (sx * spread * 0.5), 3)
    default_ang = {"A": 45.0, "B": 135.0, "C": 225.0, "D": 315.0}[face]
    return {
        "face": face,
        "x_m": x_m,
        "y_m": y_m,
        "azimuth_deg": round(ang_raw if ang_raw is not None else default_ang, 1),
    }


def suggest_similar_devices(missing_name: str, catalog_devices: list[dict], top_k: int = 3) -> list[dict]:
    """Rank catalog_devices by prefix/type affinity and dimension proximity to suggest replacements for missing .lib items."""
    if not catalog_devices:
        return []
    target_pre, target_dim = _extract_prefix_and_dim(missing_name)
    rf_family = {"RF", "SEC", "GSM", "IBS", "PANEL", "AAU", "AIR"}
    rru_family = {"RRU", "FILT", "FILTER", "BOX", "COMB"}
    mw_family = {"MW", "SH", "DISH", "STD", "RAD"}

    scored = []
    for d in catalog_devices:
        cand_name = str(d.get("device_name") or "")
        cand_pre, cand_dim = _extract_prefix_and_dim(cand_name)
        dim_val = float(d.get("dim_m") or cand_dim or 0.0)

        score = 0.0
        reasons = []
        if cand_pre == target_pre:
            score += 52.0
            reasons.append(f"Tipe {cand_pre} sama")
        elif target_pre in rf_family and cand_pre in rf_family:
            score += 36.0
            reasons.append(f"Keluarga antena RF/Sector ({cand_pre})")
        elif target_pre in rru_family and cand_pre in rru_family:
            score += 38.0
            reasons.append(f"Keluarga RRU/Radio ({cand_pre})")
        elif target_pre in mw_family and cand_pre in mw_family:
            score += 38.0
            reasons.append(f"Keluarga Microwave ({cand_pre})")

        if target_dim is not None and dim_val > 0:
            diff = abs(target_dim - dim_val)
            rel = diff / max(target_dim, 0.3)
            dim_score = max(0.0, 45.0 * (1.0 - min(rel, 1.0)))
            score += dim_score
            if diff <= 0.15:
                reasons.append(f"Dimensi sangat dekat ({dim_val:.3f}m vs {target_dim:.3f}m)")
            elif diff <= 0.45:
                reasons.append(f"Dimensi mendekati ({dim_val:.2f}m)")

        if score <= 5.0:
            continue
        pct = min(99, max(40, int(round(score))))
        scored.append(
            {
                "device_name": cand_name,
                "category": d.get("category") or "GENERAL",
                "shape_type": d.get("shape_type") or "BOX",
                "dim_m": round(dim_val, 3),
                "mass_kg": round(float(d.get("mass_kg") or 0.0), 2),
                "af_m2": round(float(d.get("af_m2") or 0.0), 4),
                "asf_m2": round(float(d.get("asf_m2") or 0.0), 4),
                "epa_m2": round(float(d.get("epa_m2") or 0.0), 4),
                "similarity_pct": pct,
                "reason": " · ".join(reasons) if reasons else "Kandidat terdekat di .lib",
            }
        )

    scored.sort(key=lambda x: (-x["similarity_pct"], abs((target_dim or 1.0) - x["dim_m"])))
    # Deduplicate by device_name
    seen = set()
    unique = []
    for item in scored:
        if item["device_name"] not in seen:
            seen.add(item["device_name"])
            unique.append(item)
        if len(unique) >= top_k:
            break
    return unique

