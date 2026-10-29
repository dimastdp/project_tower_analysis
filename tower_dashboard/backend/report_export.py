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

from opensees_model import check_angle_member_tia222g
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

        row["pu_opensees"] = round(pu_os, 2)
        row["phi_pn_opensees"] = round(phi_pn_os, 2)
        row["sr_opensees"] = sr_os
        row["status_os"] = status_os
        row["pu_mst"] = round(c_pu_val, 2)
        row["phi_pn_mst"] = round(phi_pn_mst, 2)
        row["sr_mst_val"] = round(sr_mst, 3)
        row["status_mst"] = status_mst
        row["diff_sr"] = diff_sr
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
    L.append(f" Wind speed V ............. {ws.get('wind_speed_ms', 0):8.2f} m/s ({ws.get('wind_speed_kmh', 0):.1f} km/h)")
    L.append(f" Exposure / Class / I ..... {ws.get('exposure', '-')} / {ws.get('struct_class', '-')} / {ws.get('i_factor', '-')}")
    L.append(f" Kzt / Kd / Gh ............ {ws.get('kzt', '-')} / {ws.get('kd', '-')} / {ws.get('gh', '-')}")
    L.append(f" Kz (top) ................. {ws.get('kz_top', 0):8.3f}")
    L.append(f" qz top ................... {ws.get('qz_top_pa', 0):8.1f} Pa   (ref {ws.get('qz_ref_pa', 0):.1f} Pa)")
    L.append(f" Scale s = qz/qz_ref ...... {ds['scale']:8.4f}")
    L.append(f" Device wind (1.6W) ....... {ws.get('total_dev_wind_kn', 0):8.2f} kN")
    L.append(f" Device dead (1.2D) ....... {ws.get('total_dev_dead_kn', 0):8.2f} kN")
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
        L.append(" MEMBER CAPACITY CHECK (OPENSEESPY FEM vs MS TOWER V6)")
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
        L.append(" CALIBRATION vs MS TOWER V6 (SR, TWIST/SWAY/DISP, SUPPORT REACTION)")
        L.append("  Category          Parameter                                        Unit      Webapps   MSTower   Acc(%)")
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

    # 2) Parameter angin -------------------------------------------------------------
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

    # 3) Beban perangkat -------------------------------------------------------------
    dev_rows = [[d["status"], d["tenant"], d["device_name"], d["elev_z_m"], d["qty"], d["qz_pa"],
                 d["epa_total_m2"], d["fw_kn"], d["fw_factored_kn"], d["fd_factored_kn"]]
                for d in eng.get("device_loads") or []]
    sheet("Beban Perangkat", "Beban Angin & Mati Perangkat (Inventori)",
          [("Status", 11), ("Tenant", 14), ("Perangkat", 22), ("Elev (m)", 9), ("Qty", 6), ("qz (Pa)", 9),
           ("EPA total (m²)", 12), ("Fw (kN)", 9), ("1.6·Fw (kN)", 11), ("1.2·D (kN)", 11)],
          dev_rows, num_formats={4: "0.00", 6: "0.0", 7: "0.000", 8: "0.00", 9: "0.00", 10: "0.00"})

    # 4) Member check -----------------------------------------------------------------
    def _v(tok):
        n = _num(tok)
        return n if n is not None else tok

    if ds["members"]:
        mrows = [[
            r["pnl"], _member_label(r), r["typ"], r["size"], _v(r["fy"]), r["klr"],
            # MS Tower V6
            r.get("pu_mst", _v(r["c_pu"])), r.get("phi_pn_mst", _v(r["c_pn"])), r.get("sr_mst_val", round(r["sr_mst"], 3)), r.get("status_mst", "OK"),
            # OpenSeesPy FEM
            r.get("pu_opensees", _v(r["c_pu"])), r.get("phi_pn_opensees", _v(r["c_pn"])), r.get("sr_opensees", round(r["sr_gov"], 3)), r.get("status_os", "OK"),
            # Comparison
            r.get("diff_sr", 0.0), r.get("accuracy_pct", 100.0), r.get("status_match", "COCOK"),
            # MS Tower cases
            _v(r["c_case"]), r["curve"],
            _v(r["t_case"]), _v(r["t_pu"]), _v(r["t_pn"]), _v(r["t_sr"]),
            _v(r["j_case"]), _v(r["j_pu"]), f"{r.get('j_dia', '')}-{r.get('j_grade', '')}",
            _v(r["j_pn"]), _v(r["j_sr"]), r["flags"],
        ] for r in ds["members"]]
        member_cols = [
            ("Pnl", 5), ("Members", 10), ("Typ", 6), ("Size", 14), ("fy (MPa)", 8), ("KL/r", 7),
            ("Pu MST (kN)", 11), ("φPn MST (kN)", 12), ("SR MST", 11), ("Status MST", 12),
            ("Pu OpenSees (kN)", 12), ("φPn OpenSees (kN)", 13), ("SR OpenSees", 11), ("Status OpenSees", 13),
            ("ΔSR (|OS - MST|)", 12), ("Akurasi (%)", 11), ("Kesesuaian", 12),
            ("C-Case", 8), ("Curve", 7),
            ("T-Case", 8), ("T Pu (kN)", 9), ("T φPn (kN)", 10), ("T Pu/φPn", 9),
            ("J-Case", 8), ("J Pu (kN)", 9), ("Baut Dia-Gr", 11),
            ("J φPn (kN)", 10), ("J Pu/φPn", 9), ("Flag", 6),
        ]
        member_fmts = {7: "0.00", 8: "0.00", 9: "0.000", 11: "0.00", 12: "0.00", 13: "0.000", 15: "0.000", 16: "0.0", 21: "0.00", 22: "0.00", 23: "0.000", 25: "0.00", 27: "0.00", 28: "0.000"}
        sr_columns = (9, 13)
    else:
        mrows = [[
            0, str(c.get("member_count") or 1), "MBR", c["sec_name"], 245, c["kl_over_r"],
            c.get("pu_mst_kn", c["pu_kn"]), c.get("phi_pn_mst_kn", c["phi_pn_kn"]), c.get("sr_mst", c["stress_ratio"]), c.get("status_mst", c["status"]),
            c.get("pu_opensees_kn", c["pu_kn"]), c.get("phi_pn_opensees_kn", c["phi_pn_kn"]), c.get("sr_opensees", c["stress_ratio"]), c.get("status_opensees", c["status"]),
            c.get("diff_sr", 0.0), c.get("accuracy_pct", 100.0), "COCOK" if c.get("status_match", True) else "BEDA",
            "-", "-", "-", None, None, None, "-", None, "-", None, None, "*" if c["stress_ratio"] > 1 else "",
        ] for c in eng.get("member_checks") or []]
        member_cols = [
            ("Pnl", 5), ("Members", 10), ("Typ", 6), ("Size", 14), ("fy (MPa)", 8), ("KL/r", 7),
            ("Pu MST (kN)", 11), ("φPn MST (kN)", 12), ("SR MST", 11), ("Status MST", 12),
            ("Pu OpenSees (kN)", 12), ("φPn OpenSees (kN)", 13), ("SR OpenSees", 11), ("Status OpenSees", 13),
            ("ΔSR (|OS - MST|)", 12), ("Akurasi (%)", 11), ("Kesesuaian", 12),
            ("C-Case", 8), ("Curve", 7),
            ("T-Case", 8), ("T Pu (kN)", 9), ("T φPn (kN)", 10), ("T Pu/φPn", 9),
            ("J-Case", 8), ("J Pu (kN)", 9), ("Baut Dia-Gr", 11),
            ("J φPn (kN)", 10), ("J Pu/φPn", 9), ("Flag", 6),
        ]
        member_fmts = {7: "0.00", 8: "0.00", 9: "0.000", 11: "0.00", 12: "0.00", 13: "0.000", 15: "0.000", 16: "0.0"}
        sr_columns = (9, 13)

    sheet("Member Check", "Member Checking to TIA-222-G (Komparasi OpenSeesPy FEM vs MS Tower V6)",
          member_cols, mrows, num_formats=member_fmts, sr_cols=sr_columns)

    # 5) Mass summary -----------------------------------------------------------------
    mass_rows = [[m["sect"], m["size"], m["flag"], m["fy"], m["length_m"], m["mass_kg"]] for m in ds["mass_summary"]]
    if mass_rows:
        mass_rows.append(["TOTAL", "", "", "", round(sum(m["length_m"] for m in ds["mass_summary"]), 2), ds["mass_total_kg"]])
    sheet("Mass Summary", "Mass Summary",
          [("Sect", 7), ("Size", 16), ("Lib", 5), ("fy (MPa)", 9), ("L (m)", 10), ("M (kg)", 11)],
          mass_rows, num_formats={5: "0.00", 6: "0.00"})

    # 6) Support reactions ------------------------------------------------------------
    titles = _case_titles(ds["reaction_cases"])
    react_rows = []
    for c in ds["reactions"]:
        for r in c["rows"]:
            f = r["f"]
            react_rows.append([c["case"], titles.get(c["case"], ""), r["id"], *[round(v, 3) for v in f],
                               round(max(0.0, f[2]), 3), round(max(0.0, -f[2]), 3), round(math.hypot(f[0], f[1]), 3),
                               round(r["f_mst"][2], 3)])
        if c.get("resultant") and not c.get("resultant_partial"):
            res = c["resultant"]
            react_rows.append([c["case"], titles.get(c["case"], ""), "Resultant", *[round(v, 3) for v in res],
                               None, None, None, None])
    if not react_rows:
        react_rows = [[None, "Envelope Tower Studio", r["node_label"], None, None, None, None, None, None,
                       r["pu_kn"], r["tu_kn"], r["vu_kn"], None] for r in ds["run_reactions"]]
    sheet("Support Reactions", "Support Reactions (Applied to tower)",
          [("Case", 7), ("Judul kasus", 40), ("Node", 10), ("FX (kN)", 10), ("FY (kN)", 10), ("FZ (kN)", 10),
           ("MX (kNm)", 10), ("MY (kNm)", 10), ("MZ (kNm)", 10), ("Pu tekan (kN)", 11), ("Tu uplift (kN)", 11),
           ("Vu geser (kN)", 11), ("FZ MS Tower (kN)", 12)],
          react_rows, num_formats={k: "0.000" for k in range(4, 14)})

    if ds["reactions_leg"]:
        leg_rows = [[c["case"], titles.get(c["case"], ""), r["id"], *[round(v, 3) for v in r["f"]]]
                    for c in ds["reactions_leg"] for r in c["rows"]]
        sheet("Reactions Along Leg", "Support Reactions (Along Leg)",
              [("Case", 7), ("Judul kasus", 40), ("Memb", 8), ("Fx (kN)", 10), ("Fy (kN)", 10), ("Fz (kN)", 10),
               ("Mx (kNm)", 10), ("My (kNm)", 10), ("Mz (kNm)", 10)],
              leg_rows, num_formats={k: "0.000" for k in range(4, 10)})

    # 7) Tower rotations ----------------------------------------------------------------
    rot_rows = []
    for label, rows in (("3 node plane", ds["rot_env_3node"]), ("leg chords", ds["rot_env_leg"])):
        rot_rows += [[label, r["pt"], r["height"], r["lc_x"], round(r["x_rot"], 4), r["lc_y"], round(r["y_rot"], 4),
                      r["lc_z"], round(r["z_rot"], 4)] for r in rows]
    sheet("Tower Rotations", "Envelope of Tower Rotations (Twist & Sway, derajat)",
          [("Basis", 14), ("Pt", 5), ("Height (m)", 10), ("LC", 7), ("X-Rot (°)", 10), ("LC", 7), ("Y-Rot (°)", 10),
           ("LC", 7), ("Z-Rot / Twist (°)", 14)],
          rot_rows, num_formats={3: "0.00", 5: "0.0000", 7: "0.0000", 9: "0.0000"})

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

