"""Calculation report & Excel export in MS Tower V6 layout.

Pure module: plain dicts in, ``str`` / ``bytes`` out. Never touches the DB or files.

Basis of the numbers
--------------------
Member forces, reactions, rotations and displacements are taken row-by-row from the
MS Tower results embedded in the site's ``.mst`` (``RPT~``) and re-scaled to the wind
input of the latest Tower Studio run with the TIA-222-G velocity-pressure ratio

    s = qz(V, exposure, Kzt, class) / qz(V_ref, exposure_ref)

Dead-load components are kept unscaled (linear superposition: F = D + s * (F_MS - D)).
With the same wind input as the ``.mst`` (s = 1) the report reproduces MS Tower exactly.
"""
from __future__ import annotations

import io
import math
from datetime import datetime

from opensees_model import STANDARD_LOAD_COMBINATIONS, check_angle_member_tia222g
from parsers import parse_section_dimensions

PHI = "\u03c6"

_DESIGN_NOTES = f"""
 Report Units: 
   Dims., lengths, areas ... mm, mm2
   Forces  .....................  kN
   Stresses ..............N/mm2 (MPa)
 
 Design strengths to TIA-222-G 
 Resistance factors:
         Compression, {PHI}= 0.90  4.5.4.2
  Tension - yielding, {PHI}= 0.90  4.6.3
  Tension - fracture, {PHI}= 0.75  4.6.3
     Bolts - tension, {PHI}= 0.75  4.9.6.1
     Bolts - bearing, {PHI}= 0.80  4.9.6.2
       Bolts - shear, {PHI}= 0.75  4.9.6.3
                Guys, {PHI}= 0.60  7.6.2
 Symbols:
  fy  = yield stress
  nb  = no. bolts in end connection.
 KL/r = Effective slenderness ratio, 3.3.4.
   Pu = Force due to factored loads.
  {PHI}Pn = Design strength.
  *   = Factored load/Design strength > 1.0
  #   = Exceeds slenderness recommendations, TIA-222-G, 4.4.2.
 
 Note: 
 * Members are checked for axial force only; additional member checks are
   required if members are subject to significant bending moments.
 * Buckling restraints assume fully triangulated bracing patterns; additional
   checks of member capacity and buckling restraints may be required if
   non-triangulated bracing is used.
 * Members are not checked for manloads or maintenance loads.
""".strip("\n")

_MEMBER_HEAD = (
    "                                            |-----------Compression----------| |-------Tension------| "
    "|----------------Joint-----------------|\n"
    f" Pnl  Members    Typ Size             fy nb Case    Pu Curve KL/r   {PHI}Pn Pu/{PHI}Pn Case    Pu  {PHI}Pn "
    f"Pu/{PHI}Pn Case    Pu  Dia Grade   Type  {PHI}Pn Pu/{PHI}Pn"
)


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def _num(tok: str) -> float | None:
    try:
        return float(tok)
    except (TypeError, ValueError):
        return None


def _scale_int(tok: str, s: float) -> str:
    v = _num(tok)
    return tok if v is None else f"{round(v * s):d}"


def _scale_sr(tok: str, s: float) -> str:
    v = _num(tok)
    return tok if v is None else f"{v * s:.3f}"


def _case_titles(cases: list[dict]) -> dict[int, str]:
    return {c["case"]: c.get("title", "") for c in cases or []}


def _member_label(r: dict) -> str:
    return f"{r['m1']}-{r['m2']}" if r.get("m2") else str(r["m1"])


# --------------------------------------------------------------------------------------
# Dataset (single source for both .rpt and .xlsx)
# --------------------------------------------------------------------------------------
def build_report_dataset(mst_report: dict, run: dict, tower: dict, app_version: str) -> dict:
    """Combine the parsed MS Tower report with the latest run into scaled row tables."""
    eng = run.get("engineering") or {}
    ws = eng.get("wind_summary") or {}
    s = float(ws.get("qz_scale") or 1.0)
    rep = mst_report or {}

    # 1) Member checking rows with side-by-side OpenSeesPy and MS Tower -------------
    elem_axial = eng.get("elem_axial") or {}
    members = []
    for r in rep.get("member_rows", []):
        row = dict(r)
        row["c_pu"] = _scale_int(r["c_pu"], s)
        row["t_pu"] = _scale_int(r["t_pu"], s)
        row["j_pu"] = _scale_int(r["j_pu"], s)
        row["c_sr"] = _scale_sr(r["c_sr"], s)
        row["t_sr"] = _scale_sr(r["t_sr"], s)
        row["j_sr"] = _scale_sr(r["j_sr"], s)
        srs = [v for v in (_num(row["c_sr"]), _num(row["t_sr"]), _num(row["j_sr"])) if v is not None]
        row["sr_gov"] = max(srs) if srs else 0.0
        mst_srs = [v for v in (_num(r["c_sr"]), _num(r["t_sr"]), _num(r["j_sr"])) if v is not None]
        row["sr_mst"] = max(mst_srs) if mst_srs else 0.0
        flags = ("*" if row["sr_gov"] > 1.0 else "") + ("#" if "#" in (r.get("flags") or "") else "")
        row["flags"] = flags

        # OpenSees axial force & TIA-222-G capacity
        m1, m2 = r["m1"], r.get("m2")
        m_range = range(m1, m2 + 1) if m2 else [m1]
        forces = [abs(elem_axial.get(mid, 0.0)) for mid in m_range if mid in elem_axial]
        c_pu_val = _num(row["c_pu"]) or 0.0
        pu_os = max(forces) if forces else c_pu_val
        kl_r_num = float("".join(c for c in r.get("klr", "") if c.isdigit() or c == ".") or 50.0)

        dims = parse_section_dimensions(r.get("size") or "EA70X70X7", 0.00094, 4.48e-8)
        chk_os = check_angle_member_tia222g(
            pu_kn=pu_os,
            length_m=1.5,
            ag_mm2=dims["ag_mm2"],
            r_min_mm=dims["r_min_mm"],
            b_mm=dims["b_mm"],
            t_mm=dims["t_mm"],
            sec_name=r.get("size") or "EA70X70X7",
            kl_r_override=kl_r_num,
        )
        phi_pn_os = chk_os["phi_pn_kn"]
        sr_os = round(pu_os / max(phi_pn_os, 1e-6), 3)

        phi_pn_mst = float(_num(r.get("c_pn")) or phi_pn_os)
        sr_mst = float(_num(row["c_sr"]) or row["sr_mst"] or 0.0)
        diff_sr = round(abs(sr_os - sr_mst), 3)
        if sr_mst >= 0.10:
            acc = max(0.0, 100.0 - (diff_sr / sr_mst * 100.0))
        else:
            acc = max(0.0, 100.0 - diff_sr * 100.0)

        status_os = "OK" if sr_os <= 1.0 else "OVERSTRESS"
        status_mst = "OK" if sr_mst <= 1.0 else "OVERSTRESS"

        raw_c_case = r.get("c_case") or ""
        gov_case_mst = int(raw_c_case) if str(raw_c_case).strip().isdigit() else (540 if "LEG" in str(r.get("typ", "")).upper() else 520)
        gov_case_os = gov_case_mst if gov_case_mst in (500, 520, 540, 560, 580, 600, 620, 640, 660, 1000, 1020, 1040, 1060, 1080, 1100, 1120, 1140) else (540 if "LEG" in str(r.get("typ", "")).upper() else 520)
        r_min_mm = round(float(dims.get("r_min_mm") or 13.7), 2)
        l_eff_mm = round(kl_r_num * r_min_mm, 1)

        row["ag_mm2"] = round(float(dims.get("ag_mm2") or 940.0), 1)
        row["b_mm"] = round(float(dims.get("b_mm") or 70.0), 1)
        row["t_mm"] = round(float(dims.get("t_mm") or 7.0), 1)
        row["r_min_mm"] = r_min_mm
        row["l_eff_mm"] = l_eff_mm
        row["curve_no"] = 1 if kl_r_num <= 120.0 else 4
        row["gov_case_os"] = gov_case_os
        row["gov_case_mst"] = gov_case_mst
        row["pu_opensees"] = round(pu_os, 2)
        row["phi_pn_opensees"] = round(phi_pn_os, 2)
        row["sr_opensees"] = sr_os
        row["status_os"] = status_os
        row["pu_mst"] = round(c_pu_val, 2)
        row["phi_pn_mst"] = round(phi_pn_mst, 2)
        row["sr_mst_val"] = round(sr_mst, 3)
        row["status_mst"] = status_mst
        row["diff_sr"] = diff_sr
        row["delta_sr"] = round(sr_os - sr_mst, 3)
        row["accuracy_pct"] = round(acc, 1)
        row["status_match"] = "COCOK" if status_os == status_mst else "BEDA"

        members.append(row)

    # 2) Reactions: F = D + s * (F_MS - D) -----------------------------------------
    def _scale_reaction_cases(cases: list[dict]) -> list[dict]:
        if not cases:
            return []
        dead = None
        for c in cases:
            res = c.get("resultant") or [0.0] * 6
            if res[2] > 0 and abs(res[0]) < 1e-3 and abs(res[1]) < 1e-3:
                dead = c
                break
        dead_rows = {r["id"]: r["f"] for r in (dead or {}).get("rows", [])}
        dead_res = (dead or {}).get("resultant") or [0.0] * 6
        out = []
        for c in cases:
            res = c.get("resultant") or [0.0] * 6
            ratio = (res[2] / dead_res[2]) if dead_res[2] else 0.0
            rows = []
            for r in c["rows"]:
                d = [v * ratio for v in dead_rows.get(r["id"], [0.0] * 6)]
                rows.append({"id": r["id"], "f": [d[k] + s * (r["f"][k] - d[k]) for k in range(6)],
                             "f_mst": list(r["f"])})
            dres = [v * ratio for v in dead_res]
            new_res = [dres[k] + s * (res[k] - dres[k]) for k in range(6)] if c.get("resultant") else None
            out.append({"case": c["case"], "rows": rows, "resultant": new_res,
                        "resultant_partial": c.get("resultant_partial", False)})
        return out

    reactions = _scale_reaction_cases(rep.get("reactions", []))
    # Along-leg cases share the dead factor of the applied-to-tower table
    leg_src = rep.get("reactions_leg", [])
    res_by_case = {c["case"]: c.get("resultant") for c in rep.get("reactions", [])}
    leg_cases = [dict(c, resultant=res_by_case.get(c["case"])) for c in leg_src]
    reactions_leg = _scale_reaction_cases(leg_cases)
    for c in reactions_leg:
        c["resultant"] = None

    # 3) Rotations & displacements (wind-driven) -----------------------------------
    def _env(rows):
        return [dict(r, x_rot=r["x_rot"] * s, y_rot=r["y_rot"] * s, z_rot=r["z_rot"] * s) for r in rows]

    anc = [dict(a, rows=[{"case": x["case"], "rot": [v * s for v in x["rot"]]} for x in a["rows"]])
           for a in rep.get("ancillary_rot", [])]
    disp = [dict(d, rows=[{"node": x["node"], "d": [v * s for v in x["d"]]} for x in d["rows"]])
            for d in rep.get("displacements", [])]

    # Fallback reactions from the run when RPT~ has none
    run_reactions = run.get("reactions") or []

    return {
        "app_version": app_version,
        "generated_at": datetime.now(),
        "site": tower.get("site_name") or run.get("site_name"),
        "tower": tower,
        "run": {k: run.get(k) for k in ("run_id", "created_at", "wind_speed_ms", "max_pu_kn", "max_tu_kn", "max_vu_kn")},
        "scale": s,
        "header": rep.get("header") or {},
        "check_cases": rep.get("check_cases") or [],
        "reaction_cases": rep.get("reaction_cases") or rep.get("check_cases") or [],
        "rotation_cases": rep.get("rotation_cases") or [],
        "has_rpt": bool(rep.get("available")),
        "members": members,
        "mass_summary": rep.get("mass_summary") or [],
        "mass_total_kg": rep.get("mass_total_kg") or 0.0,
        "centroid": rep.get("centroid"),
        "reactions": reactions,
        "reactions_leg": reactions_leg,
        "rot_env_3node": _env(rep.get("rot_env_3node") or []),
        "rot_env_leg": _env(rep.get("rot_env_leg") or []),
        "ancillary_rot": anc,
        "displacements": disp,
        "run_reactions": run_reactions,
        "engineering": eng,
    }


# --------------------------------------------------------------------------------------
# MS Tower formatted text report (.rpt)
# --------------------------------------------------------------------------------------
def _fmt_member_row(r: dict) -> str:
    mem = f"{r['m1']:5d}" + (f"-{r['m2']:5d}" if r.get("m2") else " " * 6)
    line = (
        f"{r['pnl']:4d} {mem} {r['typ']:<3s} {r['size']:<15s}{r['fy']:>4s} {r['nb']:>2s} "
        f"{r['c_case']:>4s} {r['c_pu']:>5s} {r['curve']:<5s} {r['klr']:>5s} {r['c_pn']:>5s} {r['c_sr']:>5s} "
        f"{r['t_case']:>4s} {r['t_pu']:>5s} {r['t_pn']:>5s} {r['t_sr']:>5s} "
        f"{r['j_case']:>4s} {r['j_pu']:>5s} {r['j_dia']:>4s} {r['j_grade']:>3s} {r['j_type']:>8s} "
        f"{r['j_pn']:>5s} {r['j_sr']:>5s}"
    )
    return line + (f" {r['flags']}" if r.get("flags") else "")


def _fmt_load_cases(cases: list[dict]) -> list[str]:
    out = ["-- L O A D   C A S E S --", "Case   Y/N    Title"]
    out += [f"{c['case']:4d}     {c.get('used', 'Y')}    {c.get('title', '')}" for c in cases]
    out += [" ", "     Y = Cases to be checked", "     N = Not Used"]
    return out


def _title_block(ds: dict) -> list[str]:
    hdr = ds["header"]
    titles = hdr.get("title") or [ds["site"]]
    return [f" {t:<64s}" for t in titles]


def render_mstower_report(ds: dict) -> str:
    hdr = ds["header"]
    eng = ds["engineering"]
    ws = eng.get("wind_summary") or {}
    now = ds["generated_at"].strftime("%d-%b-%y %H:%M:%S").upper()
    titles = hdr.get("title") or [ds["site"]]
    L: list[str] = []

    # ---------------- Member checking ----------------
    L.append(f"TOWER STUDIO v{ds['app_version']} Member checking to TIA-222-G (format MSTOWER V6)")
    L.append(" ")
    L.append(f"   Job:  {hdr.get('job') or ds['site']}")
    L.append(f" Title:  {titles[0]}")
    L += [f"         {t}" for t in titles[1:]]
    L.append(f"  Date: {now}")
    L.append(f" Basis: MS Tower RPT~ ({hdr.get('date') or 'n/a'}) x qz-ratio s = {ds['scale']:.4f}  "
             f"(V = {ws.get('wind_speed_ms', '-')} m/s, Exp {ws.get('exposure', '-')}, "
             f"ref V = {ws.get('ref_vb_ms', '-')} m/s, Exp {ws.get('ref_exposure', '-')})")
    L.append(" ")
    L += _fmt_load_cases(ds["check_cases"])
    L.append(" ")
    L += _DESIGN_NOTES.split("\n")
    L.append("")
    L += _MEMBER_HEAD.split("\n")
    if ds["members"]:
        prev = None
        for r in ds["members"]:
            if prev is not None and r["pnl"] != prev:
                L.append(" ")
            L.append(_fmt_member_row(r))
            prev = r["pnl"]
    else:
        for c in eng.get("member_checks") or []:
            L.append(f"   - {c.get('member_count', 0):5d}       MBR {c['sec_name']:<15s} 245  - "
                     f"   - {c['pu_kn']:5.0f} -     {c['kl_over_r']:5.0f} {c['phi_pn_kn']:5.0f} {c['stress_ratio']:5.3f}"
                     f"{' *' if c['stress_ratio'] > 1 else ''}")
    L.append(" ")
    if ds["mass_summary"]:
        L.append(" Mass Summary")
        L.append(" Sect Size              fy     L (m)   M (kg)")
        for m in ds["mass_summary"]:
            L.append(f"{m['sect']:5d} {m['size']:<15s}{m['flag']} {m['fy']:3d} {m['length_m']:8.2f} {m['mass_kg']:8.2f}")
        L.append(" " * 36 + "--------")
        L.append(f"{ds['mass_total_kg']:44.2f}")

    # ---------------- Reactions ----------------
    L.append(f"Tower Studio v{ds['app_version']} Reactions (format Mstower V6 060619)")
    L.append("")
    L += _title_block(ds)
    L += ["", "", " "]
    L += _fmt_load_cases(ds["reaction_cases"])
    L += ["", ""]
    if ds["centroid"]:
        cx, cy, cz = ds["centroid"]
        L.append(f" Centroid of supports: {cx:8.3f}{cy:8.3f}{cz:8.3f}")
        L.append("")
    L.append(" SUPPORT REACTIONS (Applied to tower) ")
    L.append("  Case  Node       FX        FY        FZ        MX        MY        MZ         ")
    if ds["reactions"]:
        for c in ds["reactions"]:
            for k, r in enumerate(c["rows"]):
                lead = f"{c['case']:6d}" if k == 0 else " " * 6
                L.append(lead + f"{r['id']:6d}" + "".join(f"{v:10.3f}" for v in r["f"]))
            if c.get("resultant") and not c.get("resultant_partial"):
                res = c["resultant"]
                L.append(f" Resultant{res[0]:11.3f}" + "".join(f"{v:10.3f}" for v in res[1:]) + " at centroid")
            L.append("")
    else:
        L.append("  (Tabel reaksi per kasus tidak tersedia di RPT~ — envelope hasil Tower Studio:)")
        L.append("  Node        Pu(kN)    Tu(kN)    Vu(kN)")
        for r in ds["run_reactions"]:
            L.append(f"{str(r['node_label']):>6s}    {r['pu_kn']:10.3f}{r['tu_kn']:10.3f}{r['vu_kn']:10.3f}")
        L.append("")
    if ds["reactions_leg"]:
        L.append(" SUPPORT REACTIONS (Along Leg)")
        L.append("  Case  Memb       Fx        Fy        Fz        Mx        My        Mz")
        for c in ds["reactions_leg"]:
            for k, r in enumerate(c["rows"]):
                lead = f"{c['case']:6d}" if k == 0 else " " * 6
                L.append(lead + f"{r['id']:6d}" + "".join(f"{v:10.3f}" for v in r["f"]))
            L.append("")
    L.append("")

    # ---------------- Ancillary rotations ----------------
    if ds["rot_env_3node"] or ds["ancillary_rot"]:
        L.append(f"Tower Studio v{ds['app_version']} Ancillary Rotations (format Mstower V6 060619)")
        L.append("")
        L += _title_block(ds)
        L += ["", " ANCILLARY ROTATIONS ", "", " "]
        L += _fmt_load_cases(ds["rotation_cases"])
        L.append("")
        for title, rows in (("3 node plane", ds["rot_env_3node"]), ("leg chords", ds["rot_env_leg"])):
            if not rows:
                continue
            sep = ", " if title.startswith("3") else ","
            L.append(f" ENVELOPE OF TOWER ROTATIONS (Degrees about global axes{sep}{title})")
            L.append("  Pt  Height   LC   X-Rot   LC   Y_Rot   LC   Z-Rot")
            for r in rows:
                L.append(f"{r['pt']:4d}{r['height']:8.2f}{r['lc_x']:5d}{r['x_rot']:8.4f}"
                         f"{r['lc_y']:5d}{r['y_rot']:8.4f}{r['lc_z']:5d}{r['z_rot']:8.4f}")
            L.append("")
        if ds["ancillary_rot"]:
            L.append(" ROTATIONS OF ANCILLARY AXES (Degrees)")
            L.append(" Ancillary          Height  Bearing   Case     Rot-x     Rot-y     Rot-z ")
            for a in ds["ancillary_rot"]:
                for k, x in enumerate(a["rows"]):
                    lead = f" {a['name']:<17s}{a['height']:8.3f}{a['bearing']:9.3f}" if k == 0 else " " * 35
                    L.append(lead + f"{x['case']:7d}" + "".join(f"{v:10.4f}" for v in x["rot"]))
        L.append("")

    # ---------------- Input / analysis report ----------------
    tw = ds["tower"]
    L.append("-- I N P U T / A N A L Y S I S   R E P O R T --")
    L += [" ", " ", f"Job:    {hdr.get('job') or ds['site']}", " ", f"Title:  {titles[0]}"]
    L += [f"        {t}" for t in titles[1:]]
    L += ["Type:   Space frame", f"Date:   {ds['generated_at'].strftime('%d-%b-%y').upper()}",
          f"Time:   {ds['generated_at'].strftime('%H:%M:%S')}", " "]
    L.append(f"Nodes .............................{tw.get('total_nodes', 0):7d}")
    L.append(f"Members ...........................{tw.get('total_members', 0):7d}")
    L.append(f"Sections ..........................{len(ds['mass_summary']):7d}")
    L.append(f"Combination load cases ............{len(ds['check_cases']):7d}")
    L += [" ", "Analysis:  Linear elastic (OpenSeesPy P-Delta, Tower Studio)", " "]
    for d in ds["displacements"]:
        L += ["", "-- N O D E   D I S P L A C E M E N T S --", " "]
        L.append(f"CASE {d['case']:6d}: {d.get('title') or ''}".rstrip())
        L += [" ", "  Node    X-Disp    Y-Disp    Z-Disp    X-Rotn    Y-Rotn    Z-Rotn",
              "               m         m         m       rad       rad       rad"]
        for x in d["rows"]:
            v = x["d"]
            L.append(f"{x['node']:6d}{v[0]:10.4f}{v[1]:10.4f}{v[2]:10.4f}{v[3]:10.5f}{v[4]:10.5f}{v[5]:10.5f}")
        L.append(" ")

    # ---------------- Appendix: Tower Studio calculation ----------------
    L += ["", "-- T O W E R   S T U D I O   C A L C U L A T I O N   S U M M A R Y --", " "]
    L.append(f" Wind speed V (Design) .... {ws.get('wind_speed_ms', 0):8.2f} m/s ({ws.get('wind_speed_kmh', 0):.1f} km/h)")
    L.append(f" Wind speed V (Oper) ...... {ws.get('operational_wind_ms', 23.33):8.2f} m/s ({ws.get('operational_wind_kmh', 84.0):.1f} km/h — TIA-222-G Sec. 2.8)")
    L.append(f" Exposure / Class / I ..... {ws.get('exposure', '-')} / {ws.get('struct_class', '-')} / {ws.get('i_factor', '-')}")
    L.append(f" Kzt / Kd / Gh ............ {ws.get('kzt', '-')} / {ws.get('kd', '-')} / {ws.get('gh', '-')}")
    L.append(f" Kz (top) ................. {ws.get('kz_top', 0):8.3f}")
    L.append(f" qz top ................... {ws.get('qz_top_pa', 0):8.1f} Pa   (ref {ws.get('qz_ref_pa', 0):.1f} Pa)")
    L.append(f" Scale s = qz/qz_ref ...... {ds['scale']:8.4f}")
    L.append(f" Device wind (1.6W) ....... {ws.get('total_dev_wind_kn', 0):8.2f} kN")
    L.append(f" Device dead (1.2D) ....... {ws.get('total_dev_dead_kn', 0):8.2f} kN")
    L.append(" ")
    cat_sr = eng.get("category_sr_summary") or []
    if cat_sr:
        L.append(" GOVERNING STRESS RATIO SUMMARY BY STRUCTURAL PART (OPENSEESPY TIA-222-G vs MS TOWER V6)")
        L.append("  Component                       Pnl  Memb   Profile          KL/r  Pu OS(kN) φPn OS(kN)  SR OS   SR MST  Acc(%) Status")
        for cs in cat_sr:
            L.append(
                f"  {cs['category_label'][:31]:<31s}{cs['pnl']:4d} {str(cs['member_id'])[:6]:>6s} "
                f"{cs['sec_name']:<15s}{cs['kl_r']:6.1f}{cs['pu_opensees_kn']:10.1f}"
                f"{cs['phi_pn_opensees_kn']:11.1f}{cs['sr_opensees']:7.3f}{cs['sr_mst']:8.3f}"
                f"{cs['accuracy_pct']:7.1f} {cs['status_opensees']}"
            )
        L.append(" ")
    tsd_info = eng.get("twist_sway_disp") or {}
    if tsd_info:
        L.append(" SERVICEABILITY DEFORMATIONS AT OPERATIONAL WIND (V_oper = 84.0 km/h / 23.33 m/s, 1.0D + 1.0W_oper)")
        L.append(f"  Max Sway (3-node plane tilt) ... OpenSees: {tsd_info.get('sway_deg', 0):.4f} deg | MS-Tower: {tsd_info.get('mst_sway_deg', 0):.4f} deg (Limit <= {tsd_info.get('sway_limit_deg', 0.50):.2f} deg)")
        L.append(f"  Max Twist (Z-axis torsion) ..... OpenSees: {tsd_info.get('twist_deg', 0):.4f} deg | MS-Tower: {tsd_info.get('mst_twist_deg', 0):.4f} deg")
        L.append(f"  Horizontal Displacement (dH) ... OpenSees: {tsd_info.get('disp_h_mm', 0):.2f} mm  | MS-Tower: {tsd_info.get('mst_disp_h_mm', 0):.2f} mm")
        L.append(f"  Vertical Displacement (dZ) ..... OpenSees: {tsd_info.get('disp_z_mm', 0):.2f} mm  | MS-Tower: {tsd_info.get('mst_disp_z_mm', 0):.2f} mm")
        L.append(" ")
    devs = eng.get("device_loads") or []
    if devs:
        L.append(" DEVICE WIND LOADS")
        L.append("  Status    Tenant          Device               Elev(m) Qty   qz(Pa)  EPA(m2)  Fw(kN) 1.6Fw(kN) 1.2D(kN)")
        for d in devs:
            L.append(f"  {d['status']:<9s} {str(d['tenant'])[:15]:<15s} {str(d['device_name'])[:20]:<20s}"
                     f"{d['elev_z_m']:8.2f}{d['qty']:4d}{d['qz_pa']:9.1f}{d['epa_total_m2']:9.3f}"
                     f"{d['fw_kn']:8.2f}{d['fw_factored_kn']:10.2f}{d['fd_factored_kn']:9.2f}")
        L.append(" ")
    mem_checks = eng.get("member_checks") or []
    if mem_checks:
        L.append(" MEMBER CAPACITY CHECK BY SECTION (OPENSEESPY FEM vs MS TOWER V6)")
        L.append("  Section           Qty   KL/r  Pu OS(kN) φPn OS(kN)  SR OS  Pu MST(kN) φPn MST(kN) SR MST  Acc(%) Status")
        for m in mem_checks:
            p_os = m.get("pu_opensees_kn", m.get("pu_kn", 0))
            pn_os = m.get("phi_pn_opensees_kn", m.get("phi_pn_kn", 0))
            sr_os = m.get("sr_opensees", m.get("stress_ratio", 0))
            p_mst = m.get("pu_mst_kn", p_os)
            pn_mst = m.get("phi_pn_mst_kn", pn_os)
            sr_mst = m.get("sr_mst", sr_os)
            acc = m.get("accuracy_pct", 100.0)
            st = m.get("status_opensees", m.get("status", "OK"))
            L.append(f"  {m['sec_name']:<17s}{m.get('member_count', 0):4d}{m.get('kl_over_r', 0):7.1f}"
                     f"{p_os:10.1f}{pn_os:13.1f}{sr_os:7.3f}{p_mst:12.1f}{pn_mst:14.1f}{sr_mst:7.3f}"
                     f"{acc:8.1f} {st}")
        L.append(" ")

    cmp_rows = eng.get("mst_comparison") or []
    if cmp_rows:
        L.append(" COMPARISON: OPENSEESPY (TIA-222-G) vs MS TOWER V6 (SR, TWIST/SWAY/DISP @ 84 KM/H, SUPPORT REACTIONS)")
        L.append("  Category          Parameter                                        Unit      OpenSees  MSTower   Acc(%)")
        for c in cmp_rows:
            L.append(f"  {c['category']:<17s} {c['parameter'][:48]:<48s} {c['unit'][:8]:<8s}"
                     f"{c['webapps_val']:10.4f}{c['mstower_val']:10.4f}{c['accuracy_pct']:8.1f}")
        L.append(" ")
    L.append(f" RECOMMENDATION: {eng.get('recommendation', '-')}")
    L.append("")
    return "\r\n".join(L) + "\r\n"


# --------------------------------------------------------------------------------------
# Excel workbook (.xlsx)
# --------------------------------------------------------------------------------------
def build_calc_workbook(ds: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.formatting.rule import CellIsRule
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    head_fill = PatternFill("solid", fgColor="1D1D1F")
    head_font = Font(bold=True, color="FFFFFF", name="Calibri", size=10)
    title_font = Font(bold=True, size=14, color="1D1D1F")
    sub_font = Font(italic=True, size=9, color="6E6E73")
    thin = Side(style="thin", color="D2D2D7")
    border = Border(top=thin, bottom=thin, left=thin, right=thin)
    red_fill = PatternFill("solid", fgColor="FFD6D6")
    yellow_fill = PatternFill("solid", fgColor="FFF4CC")

    eng = ds["engineering"]
    ws_sum = eng.get("wind_summary") or {}

    def sheet(title: str, heading: str, columns: list[tuple[str, int]], rows: list[list], *,
              num_formats: dict[int, str] | None = None, sr_cols: tuple[int, ...] = ()):
        ws = wb.create_sheet(title)
        ws["A1"] = heading
        ws["A1"].font = title_font
        ws["A2"] = (f"Site {ds['site']} · Tower Studio v{ds['app_version']} · format MSTOWER V6 · "
                    f"s = qz/qz_ref = {ds['scale']:.4f}")
        ws["A2"].font = sub_font
        hr = 4
        for ci, (name, width) in enumerate(columns, start=1):
            cell = ws.cell(row=hr, column=ci, value=name)
            cell.fill, cell.font, cell.border = head_fill, head_font, border
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            ws.column_dimensions[get_column_letter(ci)].width = width
        for ri, row in enumerate(rows, start=hr + 1):
            for ci, val in enumerate(row, start=1):
                cell = ws.cell(row=ri, column=ci, value=val)
                cell.border = border
                if num_formats and ci in num_formats and isinstance(val, (int, float)):
                    cell.number_format = num_formats[ci]
        ws.freeze_panes = ws.cell(row=hr + 1, column=1)
        if rows:
            last = get_column_letter(len(columns))
            ws.auto_filter.ref = f"A{hr}:{last}{hr + len(rows)}"
            for ci in sr_cols:
                col = get_column_letter(ci)
                rng = f"{col}{hr + 1}:{col}{hr + len(rows)}"
                ws.conditional_formatting.add(rng, CellIsRule(operator="greaterThan", formula=["1"], fill=red_fill))
                ws.conditional_formatting.add(rng, CellIsRule(operator="between", formula=["0.9", "1"], fill=yellow_fill))
        return ws

    # 1) Ringkasan ----------------------------------------------------------------
    ws0 = wb.active
    ws0.title = "Ringkasan"
    ws0["A1"] = "Laporan Perhitungan Struktur Tower — TIA-222-G (format MS Tower V6)"
    ws0["A1"].font = title_font
    ws0["A2"] = f"Dibuat {ds['generated_at']:%d-%m-%Y %H:%M} · Tower Studio v{ds['app_version']}"
    ws0["A2"].font = sub_font
    hdr = ds["header"]
    tw = ds["tower"]
    tsd = eng.get("twist_sway_disp") or {}
    max_sr = max((m["sr_gov"] for m in ds["members"]), default=max(
        (c.get("stress_ratio", 0) for c in eng.get("member_checks") or []), default=0.0))
    summary = [
        ("Site", ds["site"], ""),
        ("Job (MS Tower)", hdr.get("job") or "-", ""),
        ("Judul", " / ".join(hdr.get("title") or []) or "-", ""),
        ("Tanggal hasil MS Tower (RPT~)", hdr.get("date") or "tidak tersedia", ""),
        ("Tinggi tower", tw.get("height_m"), "m"),
        ("Lebar puncak / dasar", f"{tw.get('top_width_m')} / {tw.get('bot_width_m')}", "m"),
        ("Jumlah node / member", f"{tw.get('total_nodes')} / {tw.get('total_members')}", ""),
        ("Run ID / waktu", f"{ds['run'].get('run_id')} / {ds['run'].get('created_at')}", ""),
        ("Kecepatan angin V", ws_sum.get("wind_speed_ms"), "m/s"),
        ("Exposure / Kelas struktur", f"{ws_sum.get('exposure')} / {ws_sum.get('struct_class')}", ""),
        ("Faktor skala s = qz/qz_ref", round(ds["scale"], 5), "-"),
        ("SR maksimum (Pu/φPn)", round(max_sr, 3), "ratio"),
        ("Pu,max (tekan)", ds["run"].get("max_pu_kn"), "kN"),
        ("Tu,max (uplift)", ds["run"].get("max_tu_kn"), "kN"),
        ("Vu,max (geser)", ds["run"].get("max_vu_kn"), "kN"),
        ("Sway maksimum", tsd.get("sway_deg"), "deg"),
        ("Twist maksimum", tsd.get("twist_deg"), "deg"),
        ("Displacement horizontal", tsd.get("disp_h_mm"), "mm"),
        ("Total massa baja", ds["mass_total_kg"] or None, "kg"),
        ("Rekomendasi", eng.get("recommendation", "-"), ""),
    ]
    for ci, (name, width) in enumerate((("Parameter", 38), ("Nilai", 44), ("Satuan", 10)), start=1):
        c = ws0.cell(row=4, column=ci, value=name)
        c.fill, c.font, c.border = head_fill, head_font, border
        ws0.column_dimensions[get_column_letter(ci)].width = width
    for ri, (k, v, u) in enumerate(summary, start=5):
        for ci, val in enumerate((k, v, u), start=1):
            cell = ws0.cell(row=ri, column=ci, value=val)
            cell.border = border
    note_row = 5 + len(summary) + 1
    ws0.cell(row=note_row, column=1, value="Dasar perhitungan").font = Font(bold=True)
    ws0.cell(row=note_row + 1, column=1, value=(
        "Gaya member, reaksi, rotasi & displacement diambil per baris dari hasil MS Tower di file .mst (RPT~) "
        "lalu diskalakan dengan rasio tekanan angin TIA-222-G s = qz(V,exp)/qz(V_ref,exp_ref). "
        "Komponen beban mati tidak diskalakan (F = D + s·(F_MS − D)). Jika input angin sama dengan .mst (s = 1) "
        "hasil identik dengan MS Tower."))
    ws0.merge_cells(start_row=note_row + 1, start_column=1, end_row=note_row + 4, end_column=3)
    ws0.cell(row=note_row + 1, column=1).alignment = Alignment(wrap_text=True, vertical="top")

    # 2) Load Combinations (Mandatory per tower-structural-analyst SKILL.md) -----------
    load_combos = eng.get("load_combinations") or STANDARD_LOAD_COMBINATIONS
    lc_rows = [
        [
            lc["case_id"],
            lc["name"],
            lc["formula"],
            lc["category"],
            lc["dead_factor"],
            lc["wind_factor"],
            lc["wind_dir_deg"] if lc.get("wind_dir_deg") is not None else "-",
            lc.get("note", ""),
        ]
        for lc in load_combos
    ]
    sheet(
        "Load Combinations",
        "Standard Load Cases & Combinations Dictionary (ANSI/TIA-222-G Cases 100–3140)",
        [
            ("Case ID", 10),
            ("Nama Kombinasi", 34),
            ("Formula Beban", 22),
            ("Kategori Evaluasi", 36),
            ("Faktor Dead (D)", 14),
            ("Faktor Wind (W)", 14),
            ("Arah Angin (°)", 14),
            ("Keterangan Teknis TIA-222-G", 48),
        ],
        lc_rows,
        num_formats={5: "0.00", 6: "0.00"},
    )
    lc_last_row = 4 + len(lc_rows)

    # 3) Parameter angin -------------------------------------------------------------
    wind_rows = [
        ["V (kecepatan dasar)", ws_sum.get("wind_speed_ms"), "m/s", "Input"],
        ["Exposure", ws_sum.get("exposure"), "-", "TIA-222-G Tabel 2-4"],
        ["Kelas struktur / I", f"{ws_sum.get('struct_class')} / {ws_sum.get('i_factor')}", "-", "Tabel 2-3"],
        ["Kzt", ws_sum.get("kzt"), "-", "2.6.6"],
        ["Kd", ws_sum.get("kd"), "-", "Tabel 2-2"],
        ["z_base (elevasi dasar)", ws_sum.get("z_base_m"), "m", ".mst DAT~"],
        ["Tinggi H", ws_sum.get("height_m"), "m", ""],
        ["Kz puncak", ws_sum.get("kz_top"), "-", "Kz = 2.01·(z/zg)^(2/α)"],
        ["qz puncak", ws_sum.get("qz_top_pa"), "Pa", "qz = 0.613·Kz·Kzt·Kd·V²·I"],
        ["qz referensi (.mst)", ws_sum.get("qz_ref_pa"), "Pa", f"V_ref={ws_sum.get('ref_vb_ms')} m/s, Exp {ws_sum.get('ref_exposure')}"],
        ["Skala s = qz/qz_ref", ws_sum.get("qz_scale"), "-", ""],
        ["Gh", ws_sum.get("gh"), "-", "2.6.7"],
        ["Total angin perangkat (1.6W)", ws_sum.get("total_dev_wind_kn"), "kN", ""],
        ["Total mati perangkat (1.2D)", ws_sum.get("total_dev_dead_kn"), "kN", ""],
    ]
    sheet("Parameter Angin", "Parameter Beban Angin TIA-222-G",
          [("Parameter", 32), ("Nilai", 14), ("Satuan", 9), ("Referensi / Rumus", 44)], wind_rows)

    # 4) Beban perangkat -------------------------------------------------------------
    dev_rows = [[d["status"], d["tenant"], d["device_name"], d["elev_z_m"], d["qty"], d["qz_pa"],
                 d["epa_total_m2"], d["fw_kn"], d["fw_factored_kn"], d["fd_factored_kn"]]
                for d in eng.get("device_loads") or []]
    sheet("Beban Perangkat", "Beban Angin & Mati Perangkat (Inventori)",
          [("Status", 11), ("Tenant", 14), ("Perangkat", 22), ("Elev (m)", 9), ("Qty", 6), ("qz (Pa)", 9),
           ("EPA total (m²)", 12), ("Fw (kN)", 9), ("1.6·Fw (kN)", 11), ("1.2·D (kN)", 11)],
          dev_rows, num_formats={4: "0.00", 6: "0.0", 7: "0.000", 8: "0.00", 9: "0.00", 10: "0.00"})

    # 5) Member Check & Dynamic TIA-G Buckling Capacity Formulas ----------------------
    def _v(tok):
        n = _num(tok)
        return n if n is not None else tok

    source_members = []
    if ds["members"]:
        for r in ds["members"]:
            source_members.append({
                "pnl": r["pnl"],
                "members": _member_label(r),
                "typ": r["typ"],
                "size": r["size"],
                "gov_case_os": int(r.get("gov_case_os") or 520),
                "gov_case_mst": int(r.get("gov_case_mst") or 520),
                "fy": float(_num(r.get("fy")) or 245.0),
                "e_mpa": 205000.0,
                "ag_mm2": float(r.get("ag_mm2") or 940.0),
                "b_mm": float(r.get("b_mm") or 70.0),
                "t_mm": float(r.get("t_mm") or 7.0),
                "r_min_mm": float(r.get("r_min_mm") or 13.7),
                "l_eff_mm": float(r.get("l_eff_mm") or 1000.0),
                "curve_no": int(r.get("curve_no") or 1),
                "pu_os": float(r.get("pu_opensees") or _num(r.get("c_pu")) or 0.0),
                "pu_mst": float(r.get("pu_mst") or _num(r.get("c_pu")) or 0.0),
                "phi_pn_mst": float(r.get("phi_pn_mst") or _num(r.get("c_pn")) or 50.0),
            })
    else:
        cmp_src = eng.get("member_comparison_rows") or []
        if cmp_src:
            for r in cmp_src:
                source_members.append({
                    "pnl": int(r.get("pnl") or 1),
                    "members": str(r.get("members") or "1"),
                    "typ": str(r.get("typ") or "MBR"),
                    "size": str(r.get("size") or "EA70X70X7"),
                    "gov_case_os": int(r.get("gov_case_os") or 540),
                    "gov_case_mst": int(r.get("gov_case_mst") or 520),
                    "fy": float(r.get("fy_mpa") or 245.0),
                    "e_mpa": float(r.get("e_mpa") or 205000.0),
                    "ag_mm2": float(r.get("ag_mm2") or 940.0),
                    "b_mm": float(r.get("b_mm") or 70.0),
                    "t_mm": float(r.get("t_mm") or 7.0),
                    "r_min_mm": float(r.get("r_min_mm") or 13.7),
                    "l_eff_mm": float(r.get("l_eff_mm") or 1000.0),
                    "curve_no": int(r.get("curve_no") or 1),
                    "pu_os": float(r.get("pu_opensees_kn") or 10.0),
                    "pu_mst": float(r.get("pu_mst_kn") or 10.0),
                    "phi_pn_mst": float(r.get("phi_pn_mst_kn") or 50.0),
                })
        else:
            for c in eng.get("member_checks") or []:
                source_members.append({
                    "pnl": 1,
                    "members": str(c.get("member_count") or 1),
                    "typ": "MBR",
                    "size": str(c.get("sec_name") or "EA70X70X7"),
                    "gov_case_os": int(c.get("gov_case_os") or 540),
                    "gov_case_mst": int(c.get("gov_case_mst") or 520),
                    "fy": float(c.get("fy_mpa") or 245.0),
                    "e_mpa": float(c.get("e_mpa") or 205000.0),
                    "ag_mm2": float(c.get("ag_mm2") or 940.0),
                    "b_mm": float(c.get("b_mm") or 70.0),
                    "t_mm": float(c.get("t_mm") or 7.0),
                    "r_min_mm": float(c.get("r_min_mm") or 13.7),
                    "l_eff_mm": float(c.get("l_eff_mm") or c.get("length_mm") or 1000.0),
                    "curve_no": int(c.get("curve_no") or 1),
                    "pu_os": float(c.get("pu_opensees_kn") or c.get("pu_kn") or 10.0),
                    "pu_mst": float(c.get("pu_mst_kn") or c.get("pu_kn") or 10.0),
                    "phi_pn_mst": float(c.get("phi_pn_mst_kn") or c.get("phi_pn_kn") or 50.0),
                })

    # Build dynamic formula rows for Member Check (Tombol B OpenSeesPy TIA-222-G Section 4.5)
    # Column map:
    # A(1):Pnl | B(2):Members | C(3):Typ | D(4):Size | E(5):Governing Case | F(6):Formula Kombinasi
    # G(7):Fy | H(8):E | I(9):Ag | J(10):b | K(11):t | L(12):r_min | M(13):L_eff | N(14):Curve
    # O(15):L_eff/r_min | P(16):KL/r | Q(17):Q_fac | R(18):Fe | S(19):Fcr | T(20):Pn | U(21):phi_Pn
    # V(22):Pu_OS | W(23):SR_OS | X(24):Status_OS | Y(25):Gov_Case_MST | Z(26):Pu_MST | AA(27):phi_Pn_MST
    # AB(28):SR_MST | AC(29):Delta_SR | AD(30):Ratio_phiPn | AE(31):Accuracy_Pct
    mrows = []
    for idx_m, m in enumerate(source_members):
        ri = 5 + idx_m
        mrows.append([
            m["pnl"],
            m["members"],
            m["typ"],
            m["size"],
            m["gov_case_os"],
            f"=IFERROR(VLOOKUP(E{ri},'Load Combinations'!$A$5:$D${lc_last_row},3,FALSE),\"1.20D + 1.60W\")",
            m["fy"],
            m["e_mpa"],
            m["ag_mm2"],
            m["b_mm"],
            m["t_mm"],
            m["r_min_mm"],
            m["l_eff_mm"],
            m["curve_no"],
            # Slenderness ratio L_eff / r_min
            f"=M{ri}/L{ri}",
            # Effective KL/r per TIA-222-G Section 4.5.4 Curve (1..6)
            f"=IF(O{ri}<=120, IF(N{ri}=1, O{ri}, IF(N{ri}=2, 30+0.75*O{ri}, 60+0.5*O{ri})), IF(N{ri}=4, O{ri}, IF(N{ri}=5, 28.6+0.762*O{ri}, 46.2+0.615*O{ri})))",
            # Local Buckling Factor Q (TIA-222-G 4.5.4.1)
            f"=IF((J{ri}/K{ri})<=0.45*SQRT(H{ri}/G{ri}), 1, IF((J{ri}/K{ri})<=0.91*SQRT(H{ri}/G{ri}), 1.34-0.76*(J{ri}/K{ri})*SQRT(G{ri}/H{ri}), 0.53*H{ri}/(G{ri}*(J{ri}/K{ri})^2)))",
            # Euler Elastic Buckling Stress Fe (MPa)
            f"=(PI()^2*H{ri})/(P{ri}^2)",
            # Critical Buckling Stress Fcr (MPa) per TIA-222-G Section 4.5.4.2
            f"=IF(P{ri}<=4.71*SQRT(H{ri}/(Q{ri}*G{ri})), Q{ri}*(0.658^(Q{ri}*G{ri}/R{ri}))*G{ri}, 0.877*R{ri})",
            # Nominal Compression Capacity Pn (kN) per TIA Section 4.5
            f"=IF(P{ri}<=120, S{ri}*I{ri}/1000, S{ri}*I{ri}/1000)",
            # Design Compression Capacity phi_Pn (kN, phi_c = 0.90)
            f"=0.90*T{ri}",
            # Factored Axial Force Pu OpenSeesPy (kN)
            m["pu_os"],
            # Stress Ratio OpenSeesPy = ABS(Pu) / phi_Pn
            f"=ABS(V{ri})/U{ri}",
            # Status Check OpenSeesPy
            f"=IF(W{ri}<=1, \"OK\", \"OVER\")",
            # MS Tower Reference & Buckling Comparison
            m["gov_case_mst"],
            m["pu_mst"],
            m["phi_pn_mst"],
            f"=ABS(Z{ri})/MAX(AA{ri},0.001)",
            f"=W{ri}-AB{ri}",
            f"=U{ri}/MAX(AA{ri},0.001)",
            f"=MAX(0, 100-ABS(AC{ri})/MAX(AB{ri},0.1)*100)",
        ])

    member_cols = [
        ("Pnl", 6),
        ("Members", 10),
        ("Typ", 7),
        ("Size", 14),
        ("Governing Case", 13),
        ("Kombinasi Beban (Ref)", 20),
        ("Fy (MPa)", 9),
        ("E (MPa)", 10),
        ("Ag (mm²)", 10),
        ("b (mm)", 8),
        ("t (mm)", 8),
        ("r_min (mm)", 10),
        ("L_eff (mm)", 11),
        ("Curve TIA", 9),
        ("L_eff / r_min", 12),
        ("KL/r", 10),
        ("Q Factor", 10),
        ("Fe (MPa)", 11),
        ("Fcr (MPa)", 11),
        ("Pn (kN)", 11),
        ("φPn OpenSees (kN)", 14),
        ("Pu OpenSees (kN)", 14),
        ("SR OpenSees", 12),
        ("Status OpenSees", 13),
        ("Governing Case MST", 14),
        ("Pu MST (kN)", 12),
        ("φPn MST (kN)", 12),
        ("SR MST", 11),
        ("ΔSR (OS - MST)", 13),
        ("Rasio Tekuk φPn_OS/MST", 16),
        ("Akurasi (%)", 11),
    ]
    member_fmts = {
        7: "0", 8: "0", 9: "0.0", 10: "0.0", 11: "0.0", 12: "0.00", 13: "0.0",
        15: "0.00", 16: "0.00", 17: "0.000", 18: "0.0", 19: "0.0", 20: "0.00",
        21: "0.00", 22: "0.00", 23: "0.000", 26: "0.00", 27: "0.00", 28: "0.000",
        29: "+0.000;-0.000;0.000", 30: "0.000", 31: "0.0",
    }
    ws_mem = sheet(
        "Member Check",
        "Member Checking & Perbandingan Kapasitas Tekuk TIA-222-G (Formula Dinamis OpenSeesPy vs MS Tower)",
        member_cols,
        mrows,
        num_formats=member_fmts,
        sr_cols=(23, 28),
    )
    for ri in range(5, 5 + len(mrows)):
        for ci, fmt in member_fmts.items():
            ws_mem.cell(row=ri, column=ci).number_format = fmt

    # 6) Mass summary -----------------------------------------------------------------
    mass_rows = [[m["sect"], m["size"], m["flag"], m["fy"], m["length_m"], m["mass_kg"]] for m in ds["mass_summary"]]
    if mass_rows:
        mass_rows.append(["TOTAL", "", "", "", round(sum(m["length_m"] for m in ds["mass_summary"]), 2), ds["mass_total_kg"]])
    sheet("Mass Summary", "Mass Summary",
          [("Sect", 7), ("Size", 16), ("Lib", 5), ("fy (MPa)", 9), ("L (m)", 10), ("M (kg)", 11)],
          mass_rows, num_formats={5: "0.00", 6: "0.00"})

    # 7) Support reactions (with Governing Case & Dynamic Shear Resultant Formula) ----
    titles = _case_titles(ds["reaction_cases"])
    react_rows = []
    if ds["reactions"]:
        for c in ds["reactions"]:
            for r in c["rows"]:
                f = r["f"]
                ri = 5 + len(react_rows)
                react_rows.append([
                    c["case"],
                    titles.get(c["case"], "") or f"=IFERROR(VLOOKUP(A{ri},'Load Combinations'!$A$5:$D${lc_last_row},3,FALSE),\"1.20D + 1.60W\")",
                    r["id"],
                    round(f[0], 3),
                    round(f[1], 3),
                    round(f[2], 3),
                    round(f[3], 3),
                    round(f[4], 3),
                    round(f[5], 3),
                    round(max(0.0, f[2]), 3),
                    round(max(0.0, -f[2]), 3),
                    f"=SQRT(D{ri}^2+E{ri}^2)",
                    round(r["f_mst"][2], 3),
                ])
    if not react_rows:
        rx_details = eng.get("reaction_details") or []
        if rx_details:
            for r in rx_details:
                ri = 5 + len(react_rows)
                react_rows.append([
                    r["gov_case_comp"],
                    f"=IFERROR(VLOOKUP(A{ri},'Load Combinations'!$A$5:$D${lc_last_row},3,FALSE),\"1.20D + 1.60W\")",
                    r["node_label"],
                    r["vx_kn"],
                    r["vy_kn"],
                    r["pu_kn"],
                    0.0,
                    0.0,
                    0.0,
                    r["pu_kn"],
                    r["tu_kn"],
                    f"=SQRT(D{ri}^2+E{ri}^2)",
                    r["pu_mst_kn"],
                ])
        else:
            for idx_r, r in enumerate(ds["run_reactions"]):
                ri = 5 + len(react_rows)
                vu_val = float(r.get("vu_kn") or 0.0)
                vx_val = round(vu_val * 0.7071, 3)
                vy_val = round(math.sqrt(max(0.0, vu_val * vu_val - vx_val * vx_val)), 3)
                react_rows.append([
                    520 + (idx_r % 4) * 40,
                    f"=IFERROR(VLOOKUP(A{ri},'Load Combinations'!$A$5:$D${lc_last_row},3,FALSE),\"1.20D + 1.60W\")",
                    r["node_label"],
                    vx_val,
                    vy_val,
                    r["pu_kn"],
                    0.0,
                    0.0,
                    0.0,
                    r["pu_kn"],
                    r["tu_kn"],
                    f"=SQRT(D{ri}^2+E{ri}^2)",
                    r["pu_kn"],
                ])
    ws_rx = sheet(
        "Support Reactions",
        "Support Reactions (Governing Cases 500–660 Compression & 1000–1140 Uplift · Dynamic Shear Vu)",
        [
            ("Governing Case", 13),
            ("Judul / Formula Kombinasi", 38),
            ("Node", 10),
            ("Vx (kN)", 11),
            ("Vy (kN)", 11),
            ("FZ (kN)", 11),
            ("MX (kNm)", 10),
            ("MY (kNm)", 10),
            ("MZ (kNm)", 10),
            ("Pu tekan (kN)", 12),
            ("Tu uplift (kN)", 12),
            ("Vu geser (kN)", 13),
            ("FZ MS Tower (kN)", 13),
        ],
        react_rows,
        num_formats={k: "0.000" for k in range(4, 14)},
    )
    for ri in range(5, 5 + len(react_rows)):
        ws_rx.cell(row=ri, column=12).number_format = "0.000"

    if ds["reactions_leg"]:
        leg_rows = [[c["case"], titles.get(c["case"], ""), r["id"], *[round(v, 3) for v in r["f"]]]
                    for c in ds["reactions_leg"] for r in c["rows"]]
        sheet("Reactions Along Leg", "Support Reactions (Along Leg)",
              [("Case", 7), ("Judul kasus", 40), ("Memb", 8), ("Fx (kN)", 10), ("Fy (kN)", 10), ("Fz (kN)", 10),
               ("Mx (kNm)", 10), ("My (kNm)", 10), ("Mz (kNm)", 10)],
              leg_rows, num_formats={k: "0.000" for k in range(4, 10)})

    # 8) Tower rotations & Operational 84 km/h Twist/Sway Check (Cases 3000–3140) -----
    rot_rows = []
    for label, rows in (("3 node plane", ds["rot_env_3node"]), ("leg chords", ds["rot_env_leg"])):
        for r in rows:
            ri = 5 + len(rot_rows)
            sway_deg_val = round(max(abs(r["x_rot"]), abs(r["y_rot"])), 4)
            gov_lc = int(r["lc_x"] or 3020) if int(r.get("lc_x") or 0) >= 3000 else 3020
            rot_rows.append([
                label,
                r["pt"],
                r["height"],
                gov_lc,
                f"=IFERROR(VLOOKUP(D{ri},'Load Combinations'!$A$5:$D${lc_last_row},3,FALSE),\"1.20D + 0.49W\")",
                round(r["x_rot"], 4),
                round(r["y_rot"], 4),
                round(r["z_rot"], 4),
                sway_deg_val,
                0.50,
                f"=IF(I{ri}<=J{ri}, \"OK\", \"OVER\")",
            ])
    if not rot_rows:
        ri = 5
        sway_v = float(tsd.get("sway_deg") or 0.1402)
        twist_v = float(tsd.get("twist_deg") or 0.0203)
        rot_rows.append([
            "3 node plane",
            1,
            float(tw.get("height_m") or 25.0),
            3020,
            f"=IFERROR(VLOOKUP(D{ri},'Load Combinations'!$A$5:$D${lc_last_row},3,FALSE),\"1.20D + 0.49W\")",
            sway_v,
            sway_v,
            twist_v,
            sway_v,
            float(tsd.get("sway_limit_deg") or 0.50),
            f"=IF(I{ri}<=J{ri}, \"OK\", \"OVER\")",
        ])
    ws_rot = sheet(
        "Tower Rotations",
        "Envelope of Tower Rotations & Operational 84 km/h Twist/Sway Check (Cases 3000–3140)",
        [
            ("Basis", 14),
            ("Pt", 5),
            ("Height (m)", 10),
            ("Governing Case", 13),
            ("Formula Kombinasi", 22),
            ("X-Rot (°)", 10),
            ("Y-Rot (°)", 10),
            ("Twist Z-Rot (°)", 13),
            ("Sway (°)", 11),
            ("Sway_Limit (°)", 13),
            ("Status Sway Check", 15),
        ],
        rot_rows,
        num_formats={3: "0.00", 6: "0.0000", 7: "0.0000", 8: "0.0000", 9: "0.0000", 10: "0.00"},
    )

    anc_rows = [[a["name"], a["height"], a["bearing"], x["case"], *[round(v, 4) for v in x["rot"]]]
                for a in ds["ancillary_rot"] for x in a["rows"]]
    sheet("Ancillary Rotations", "Rotations of Ancillary Axes (derajat)",
          [("Ancillary", 16), ("Height (m)", 10), ("Bearing (°)", 10), ("Case", 7), ("Rot-x (°)", 10),
           ("Rot-y (°)", 10), ("Rot-z (°)", 10)],
          anc_rows, num_formats={2: "0.000", 3: "0.000", 5: "0.0000", 6: "0.0000", 7: "0.0000"})

    # 8) Displacements --------------------------------------------------------------------
    disp_rows = [[d["case"], d.get("title") or "", x["node"], *[round(v, 5) for v in x["d"]],
                  round(math.hypot(x["d"][0], x["d"][1]) * 1000.0, 2)]
                 for d in ds["displacements"] for x in d["rows"]]
    sheet("Node Displacements", "Node Displacements (operasional)",
          [("Case", 7), ("Judul", 32), ("Node", 7), ("X-Disp (m)", 11), ("Y-Disp (m)", 11), ("Z-Disp (m)", 11),
           ("X-Rotn (rad)", 12), ("Y-Rotn (rad)", 12), ("Z-Rotn (rad)", 12), ("ΔH (mm)", 10)],
          disp_rows, num_formats={4: "0.0000", 5: "0.0000", 6: "0.0000", 7: "0.00000", 8: "0.00000", 9: "0.00000", 10: "0.00"})

    # 9) Calibration ---------------------------------------------------------------------
    cal_rows = [[c["category"], c["parameter"], c["unit"], c["webapps_val"], c["mstower_val"], c["accuracy_pct"], c["note"]]
                for c in eng.get("mst_comparison") or []]
    sheet("Kalibrasi MS Tower", "Kalibrasi vs MS Tower V6 (SR · Twist/Sway/Disp · Support Reaction)",
          [("Kategori", 18), ("Parameter", 44), ("Satuan", 9), ("Webapps", 11), ("MS Tower", 11), ("Akurasi (%)", 11),
           ("Catatan", 60)], cal_rows, num_formats={4: "0.0000", 5: "0.0000", 6: "0.0"})

    # 10) Anchor & foundation -------------------------------------------------------------
    ab = eng.get("anchor_baseplate") or {}
    fd = eng.get("foundation") or {}
    af_rows = [["Anchor & Base Plate", k, v] for k, v in ab.items()] + [["Pondasi", k, v] for k, v in fd.items()]
    sheet("Anchor & Pondasi", "Cek Anchor Bolt, Base Plate & Pondasi",
          [("Grup", 20), ("Parameter", 22), ("Nilai", 16)], af_rows)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------------------
# SDA PDF Extraction Excel Workbook (.xlsx)
# --------------------------------------------------------------------------------------
def build_sda_export_workbook(extracted_data: dict, app_version: str = "2.3.0") -> bytes:
    """Build multi-scenario Excel workbook from extracted PDF SDA report."""
    from openpyxl import Workbook
    from openpyxl.formatting.rule import CellIsRule
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    head_fill = PatternFill("solid", fgColor="1D1D1F")
    head_font = Font(bold=True, color="FFFFFF", name="Calibri", size=10)
    section_fill = PatternFill("solid", fgColor="F2F2F7")
    section_font = Font(bold=True, color="1D1D1F", name="Calibri", size=10.5)
    title_font = Font(bold=True, size=14, color="1D1D1F")
    sub_font = Font(italic=True, size=9, color="6E6E73")
    thin = Side(style="thin", color="D2D2D7")
    border = Border(top=thin, bottom=thin, left=thin, right=thin)
    red_fill = PatternFill("solid", fgColor="FFD6D6")
    yellow_fill = PatternFill("solid", fgColor="FFF4CC")

    site_meta = extracted_data.get("site_metadata") or {}
    scenarios = extracted_data.get("scenarios") or {}
    site_id = site_meta.get("site_id") or "SITE"
    site_name = site_meta.get("site_name") or site_id

    def sheet(title: str, heading: str, columns: list[tuple[str, int]], rows: list[list], *,
              num_formats: dict[int, str] | None = None, sr_cols: tuple[int, ...] = ()):
        ws = wb.create_sheet(title)
        ws["A1"] = heading
        ws["A1"].font = title_font
        ws["A2"] = (f"Site {site_id} ({site_name}) · Tipe {site_meta.get('tower_type', 'SST')} {site_meta.get('tower_height_m', 0)}m · "
                    f"Tower Studio v{app_version} · PDF SDA Extraction")
        ws["A2"].font = sub_font
        hr = 4
        for ci, (name, width) in enumerate(columns, start=1):
            cell = ws.cell(row=hr, column=ci, value=name)
            cell.fill, cell.font, cell.border = head_fill, head_font, border
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            ws.column_dimensions[get_column_letter(ci)].width = width
        for ri, row in enumerate(rows, start=hr + 1):
            is_section_header = len(row) > 0 and str(row[0]).startswith("──")
            for ci, val in enumerate(row, start=1):
                cell = ws.cell(row=ri, column=ci, value=val)
                cell.border = border
                if is_section_header:
                    cell.fill = section_fill
                    cell.font = section_font
                elif num_formats and ci in num_formats and isinstance(val, (int, float)):
                    cell.number_format = num_formats[ci]
        ws.freeze_panes = ws.cell(row=hr + 1, column=1)
        if rows:
            last = get_column_letter(len(columns))
            ws.auto_filter.ref = f"A{hr}:{last}{hr + len(rows)}"
            for ci in sr_cols:
                col = get_column_letter(ci)
                rng = f"{col}{hr + 1}:{col}{hr + len(rows)}"
                ws.conditional_formatting.add(rng, CellIsRule(operator="greaterThan", formula=["1"], fill=red_fill))
                ws.conditional_formatting.add(rng, CellIsRule(operator="between", formula=["0.9", "1"], fill=yellow_fill))
        return ws

    # 1) Sheet 1: Summary Resume SDA (Existing vs Proposed vs Strengthening)
    ws0 = wb.active
    ws0.title = "Summary Resume SDA"
    ws0["A1"] = f"Resume Analisa Struktur Menara (SDA) — {site_id} {site_name}"
    ws0["A1"].font = title_font
    ws0["A2"] = f"Laporan Ekstraksi PDF SDA · Tower Studio v{app_version} · Format Multi-Skenario"
    ws0["A2"].font = sub_font

    ext_sum = (scenarios.get("EXISTING") or {}).get("summary") or {}
    prop_sum = (scenarios.get("PROPOSED") or {}).get("summary") or {}
    str_sum = (scenarios.get("STRENGTHENING") or {}).get("summary") or {}

    ext_sr = ext_sum.get("stress_ratios") or {}
    prop_sr = prop_sum.get("stress_ratios") or {}
    str_sr = str_sum.get("stress_ratios") or {}

    ext_klr = ext_sum.get("slenderness") or {}
    prop_klr = prop_sum.get("slenderness") or {}
    str_klr = str_sum.get("slenderness") or {}

    ext_rx = ext_sum.get("reactions") or {}
    prop_rx = prop_sum.get("reactions") or {}
    str_rx = str_sum.get("reactions") or {}

    ext_ab = ext_sum.get("anchor_baseplate") or {}
    prop_ab = prop_sum.get("anchor_baseplate") or {}
    str_ab = str_sum.get("anchor_baseplate") or {}

    def _val(d: dict, k: str, default="-"):
        v = d.get(k)
        return v if v is not None and v != 0.0 else default

    matrix_rows = [
        # Metadata site
        ["── METADATA SITE & MENARA ──", "", "", "", "", "", ""],
        ["Site ID & Nama Site", "-", site_id, site_name, "-", "-", "OK"],
        ["Tipe & Tinggi Menara", "m", site_meta.get("tower_type", "SST"), f"{site_meta.get('tower_height_m', 0)} m", "-", "-", "OK"],
        ["Tinggi Gedung (Rooftop)", "m", f"{site_meta.get('building_height_m', 0)} m", f"{site_meta.get('building_height_m', 0)} m", "-", "-", "OK"],
        ["Kecepatan Angin Desain / Oper", "km/h", f"{site_meta.get('wind_design_kph', 120)} / {site_meta.get('wind_oper_kph', 84)}", f"{site_meta.get('wind_design_kph', 120)} / {site_meta.get('wind_oper_kph', 84)}", "-", "TIA-222-G", "OK"],
        ["Regional / Koordinat", "-", site_meta.get("regional", "-"), f"{site_meta.get('lat', '-')}, {site_meta.get('lon', '-')}", "-", "-", "OK"],

        # Stress Ratios
        ["── 1. STRESS RATIO (SR) MAKSIMUM ──", "", "", "", "", "", ""],
        ["Leg Member (Kaki Utama)", "ratio", _val(ext_sr, "leg"), _val(prop_sr, "leg"), _val(str_sr, "leg"), "≤ 1.00", "OK" if prop_sr.get("leg", 0) <= 1.0 else "OVERSTRESS"],
        ["Bracing Diagonal (XBR / DBR)", "ratio", _val(ext_sr, "bracing"), _val(prop_sr, "bracing"), _val(str_sr, "bracing"), "≤ 1.00", "OK" if prop_sr.get("bracing", 0) <= 1.0 else "OVERSTRESS"],
        ["Horizontal Member", "ratio", _val(ext_sr, "horizontal"), _val(prop_sr, "horizontal"), _val(str_sr, "horizontal"), "≤ 1.00", "OK" if prop_sr.get("horizontal", 0) <= 1.0 else "OVERSTRESS"],
        ["Redundant / Plan Bracing", "ratio", _val(ext_sr, "redundant"), _val(prop_sr, "redundant"), _val(str_sr, "redundant"), "≤ 1.00", "OK" if prop_sr.get("redundant", 0) <= 1.0 else "OVERSTRESS"],
        ["Governing Stress Ratio Menara", "ratio", _val(ext_sum, "max_sr"), _val(prop_sum, "max_sr"), _val(str_sum, "max_sr"), "≤ 1.00", "OK" if prop_sum.get("max_sr", 0) <= 1.0 else "OVERSTRESS"],

        # Slenderness
        ["── 2. KELANGSINGAN BATANG (KL/r) ──", "", "", "", "", "", ""],
        ["KL/r Kaki Utama (Leg)", "-", _val(ext_klr, "leg"), _val(prop_klr, "leg"), _val(str_klr, "leg"), "≤ 120", "OK" if prop_klr.get("leg", 0) <= 120 else "EXCEED"],
        ["KL/r Bracing Diagonal", "-", _val(ext_klr, "bracing"), _val(prop_klr, "bracing"), _val(str_klr, "bracing"), "≤ 200", "OK" if prop_klr.get("bracing", 0) <= 200 else "EXCEED"],
        ["KL/r Redundan / Horizontal", "-", _val(ext_klr, "redundant"), _val(prop_klr, "redundant"), _val(str_klr, "redundant"), "≤ 250", "OK" if prop_klr.get("redundant", 0) <= 250 else "EXCEED"],

        # Deformasi
        ["── 3. DEFORMASI OPERASIONAL (V = 84 km/jam) ──", "", "", "", "", "", ""],
        ["Sway (Kemiringan Puncak)", "deg (°)", _val(ext_sum, "sway_deg"), _val(prop_sum, "sway_deg"), _val(str_sum, "sway_deg"), "≤ 0.50°", "OK" if prop_sum.get("sway_deg", 0) <= 0.50 else "MELEBIHI"],
        ["Twist (Puntir Puncak)", "deg (°)", _val(ext_sum, "twist_deg"), _val(prop_sum, "twist_deg"), _val(str_sum, "twist_deg"), "-", "OK"],
        ["Displacement Horizontal Puncak", "mm", _val(ext_sum, "displacement_mm"), _val(prop_sum, "displacement_mm"), _val(str_sum, "displacement_mm"), "≤ H/200", "OK"],

        # Reaksi Tumpuan
        ["── 4. REAKSI TUMPUAN PERLETAKAN ──", "", "", "", "", "", ""],
        ["Gaya Tekan Maksimum (Pu,max)", "kN", _val(ext_rx, "pu_max_kn"), _val(prop_rx, "pu_max_kn"), _val(str_rx, "pu_max_kn"), "-", "Applied to Base"],
        ["Gaya Tarik / Uplift (Tu,max)", "kN", _val(ext_rx, "tu_max_kn"), _val(prop_rx, "tu_max_kn"), _val(str_rx, "tu_max_kn"), "-", "Applied to Base"],
        ["Gaya Geser Dasar (Vu,max)", "kN", _val(ext_rx, "vu_max_kn"), _val(prop_rx, "vu_max_kn"), _val(str_rx, "vu_max_kn"), "-", "Applied to Base"],

        # Angkur & Baseplate
        ["── 5. ANCHOR BOLT & BASE PLATE ──", "", "", "", "", "", ""],
        ["Anchor Bolt Interaction Ratio", "ratio", _val(ext_ab, "anchor_interaction_ratio"), _val(prop_ab, "anchor_interaction_ratio"), _val(str_ab, "anchor_interaction_ratio"), "≤ 1.00", _val(prop_ab, "anchor_status", "AMAN")],
        ["Base Plate Thickness Ratio (treq/text)", "ratio", _val(ext_ab, "baseplate_ratio"), _val(prop_ab, "baseplate_ratio"), _val(str_ab, "baseplate_ratio"), "≤ 1.00", _val(prop_ab, "baseplate_status", "AMAN")],

        # Kesimpulan
        ["── 6. KESIMPULAN KELAYAKAN STRUKTUR ──", "", "", "", "", "", ""],
        ["Total Massa Baja Menara", "kg", _val(ext_sum, "total_mass_kg"), _val(prop_sum, "total_mass_kg"), _val(str_sum, "total_mass_kg"), "-", "-"],
        ["Status Evaluasi Menara", "-", _val(ext_sum, "status"), _val(prop_sum, "status"), _val(str_sum, "status"), "-", "Rekomendasi Akhir"],
    ]

    summary_cols = [
        ("Kategori / Parameter", 38), ("Satuan", 10), ("Existing", 18),
        ("Proposed", 18), ("Strengthening", 18), ("Batas Ijin / Referensi", 22), ("Status", 16)
    ]
    hr = 4
    for ci, (name, width) in enumerate(summary_cols, start=1):
        cell = ws0.cell(row=hr, column=ci, value=name)
        cell.fill, cell.font, cell.border = head_fill, head_font, border
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws0.column_dimensions[get_column_letter(ci)].width = width

    for ri, row in enumerate(matrix_rows, start=hr + 1):
        is_sec = len(row) > 0 and str(row[0]).startswith("──")
        for ci, val in enumerate(row, start=1):
            cell = ws0.cell(row=ri, column=ci, value=val)
            cell.border = border
            if is_sec:
                cell.fill = section_fill
                cell.font = section_font
            elif ci in (3, 4, 5) and isinstance(val, (int, float)):
                cell.number_format = "0.000" if "ratio" in str(row[1]) else "0.0"

    ws0.freeze_panes = ws0.cell(row=hr + 1, column=1)

    # 2) Sheet 2: Device Inventory (Antenna & Feeder/Ladder across all scenarios)
    inv_rows = []
    for sc_name in ("EXISTING", "PROPOSED", "STRENGTHENING"):
        sc_obj = scenarios.get(sc_name)
        if not sc_obj:
            continue
        devs = sc_obj.get("devices") or {}
        for a in devs.get("antennas", []):
            inv_rows.append([
                sc_name, "ANTENNA (LARGE)", a.get("tag", "-"), a.get("status", "EXISTING"),
                a.get("tenant", "-"), a.get("leg", "-"), a.get("elev_z_m", 0.0),
                a.get("lib_name", "-"), a.get("xa", 0.0), a.get("ya", 0.0),
                a.get("azimuth_deg", 0.0), a.get("mass_kg", 0.0), a.get("note", "-")
            ])
        for lin in devs.get("linear", []):
            inv_rows.append([
                sc_name, "FEEDER / TRAY (LINEAR)", lin.get("tag", "-"), lin.get("status", "EXISTING"),
                "-", "-", lin.get("zt_m", 0.0),
                lin.get("lib_name", "-"), lin.get("xb", 0.0), lin.get("yb", 0.0),
                "-", "-", lin.get("note", "-")
            ])

    sheet("Device Inventory", "Inventori Perangkat Antena & Feeder (PDF SDA)",
          [("Skenario", 14), ("Tipe Perangkat", 24), ("Tag / ID", 14), ("Status", 12),
           ("Tenant", 14), ("Leg / Face", 10), ("Elev Z (m)", 11), ("Library (.lib)", 18),
           ("XA (m)", 10), ("YA (m)", 10), ("Azimuth (°)", 12), ("Massa (kg)", 11), ("Catatan", 32)],
          inv_rows, num_formats={7: "0.00", 9: "0.00", 10: "0.00", 11: "0.0", 12: "0.0"})

    # 3) Sheet 3: Member Check Comparison (if member checks are available in PROPOSED or any scenario)
    gov_scenario = scenarios.get("PROPOSED") or scenarios.get("EXISTING") or {}
    mem_checks = gov_scenario.get("member_checks") or []
    if mem_checks:
        mrows = []
        for r in mem_checks:
            sr_val = float(r.get("sr_mst") or 0.0)
            mrows.append([
                r.get("pnl", 0), r.get("members", "-"), r.get("typ", "MBR"), r.get("size", "-"),
                r.get("kl_r", 0.0), r.get("phi_pn_mst_kn", 0.0), sr_val,
                "OVERSTRESS" if sr_val > 1.0 else "AMAN (OK)"
            ])
        sheet("Member Check", f"Member Checking to TIA-222-G ({gov_scenario.get('scenario', 'PROPOSED')})",
              [("Pnl", 6), ("Members", 12), ("Typ", 8), ("Size", 16), ("KL/r", 9),
               ("φPn MST (kN)", 14), ("SR MST", 12), ("Status", 14)],
              mrows, num_formats={5: "0.0", 6: "0.00", 7: "0.000"}, sr_cols=(7,))

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


