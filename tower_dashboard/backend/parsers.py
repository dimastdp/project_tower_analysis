"""Pure parsers: bytes/text in, plain Python structures out. Never touches the DB."""
from pathlib import Path
from typing import Any
import csv
import io
import math
import re
import struct
import zipfile

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
CHS_FROM_NAME = re.compile(r"(?:CHS|PIPE|DIA)?\s*(\d+(?:\.\d+)?)\s*[Xx]\s*(\d+(?:\.\d+)?)", re.I)


def is_structural(node: dict) -> bool:
    """Skip helper or dummy reference nodes (flag == -1 or coordinate > 1e5)."""
    return (
        node["flag"] != -1
        and abs(node["x"]) <= 1e5
        and abs(node["y"]) <= 1e5
        and abs(node["z"]) <= 1e5
    )


def parse_section_dimensions(sec_name: str, a_m2: float, iy_m4: float) -> dict:
    """Derive b_mm, t_mm, r_min_mm from section name (e.g. EA70X70X7, STA70X70X7, CHS114X6.0) and A, I."""
    a_mm2 = max(a_m2 * 1e6, 1.0)
    i_mm4 = max(iy_m4 * 1e12, 1.0)
    rx_mm = (i_mm4 / a_mm2) ** 0.5
    s_upper = (sec_name or "").upper().strip()

    # Check Circular Hollow Section (CHS / Pipe) first
    is_chs = "CHS" in s_upper or "PIPE" in s_upper or s_upper.startswith("D_")
    m_chs = CHS_FROM_NAME.search(s_upper) if is_chs else None
    if is_chs and m_chs:
        d_mm = float(m_chs.group(1))
        t_mm = float(m_chs.group(2))
        di_mm = max(d_mm - 2.0 * t_mm, 1.0)
        geom_ag = math.pi * (d_mm**2 - di_mm**2) / 4.0
        r_gyr = math.sqrt(d_mm**2 + di_mm**2) / 4.0
        return {
            "ag_mm2": round(geom_ag, 1),
            "d_mm": round(d_mm, 1),
            "b_mm": round(d_mm, 1),
            "t_mm": round(t_mm, 1),
            "rx_mm": round(r_gyr, 2),
            "r_min_mm": round(r_gyr, 2),
        }

    m = DIM_FROM_NAME.search(sec_name or "")
    if m:
        b_mm = float(m.group(1))
        t_mm = float(m.group(3))
        is_sta = "STA" in s_upper
        geom_ag = ((4.0 * b_mm - 2.0 * t_mm) * t_mm) if is_sta else ((2.0 * b_mm - t_mm) * t_mm)
        # Use exact geometric area if placeholder A_SEC (940 mm²) was passed or geom is significantly larger
        if abs(a_mm2 - 940.0) < 1.0 or geom_ag > a_mm2 * 1.2 or geom_ag < a_mm2 * 0.8:
            a_mm2 = geom_ag
    else:
        b_mm = max((a_mm2 * 3.5) ** 0.5, 40.0)
        t_mm = max(a_mm2 / (2.0 * b_mm), 4.0)
    # For equal angles (EA), minimum radius of gyration r_v ≈ 0.195 * b (or 0.64 * rx)
    if "EA" in s_upper:
        r_min_mm = round(0.195 * b_mm, 2)
    elif "STA" in s_upper:
        r_min_mm = round(0.385 * b_mm, 2)
    else:
        r_min_mm = round(rx_mm * 0.78, 2)
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


def compile_panels_to_geometry(
    panels: list[dict],
    wbase: float = 5.2,
    faces: int = 4,
    sections: dict[int, dict] | None = None,
    support_coords: list[dict] | None = None,
) -> tuple[dict[int, dict], list[dict]]:
    """Compile MS-Tower panel stack (PANEL 1 HT ... TW ...) into 3D space-frame nodes and members.

    Supports:
      - faces == 1: Single Pole / Monopole with inclined support legs / kickers
      - faces == 2: 2-Pole Tower (Twin Pole / H-Frame) with out-of-plane support legs / kickers
      - faces == 3: 3-Leg Lattice SST
      - faces == 4: 4-Leg Lattice SST
    """
    sorted_panels = sorted(panels, key=lambda p: p["id"])
    N = len(sorted_panels)
    if N == 0:
        return {}, []

    # Bottom-up height accumulation (Panel N is base, Panel 1 is top)
    levels = [0.0] * (N + 1)
    curr_z = 0.0
    for idx, p in enumerate(reversed(sorted_panels), 1):
        curr_z += p["ht"]
        levels[idx] = round(curr_z, 4)

    # Determine width at each level
    top_w = sorted_panels[0].get("tw") or (1.8 if faces == 2 else (0.165 if faces == 1 else 1.5))
    taper_z_top = 0.0
    for p in sorted_panels:
        if p.get("tw"):
            p_level_idx = N - p["id"] + 1
            taper_z_top = max(taper_z_top, levels[p_level_idx])
            top_w = p["tw"]

    if taper_z_top <= 0.0:
        taper_z_top = levels[N]

    # For 2-pole towers, wbase is the pole center-to-center spacing
    effective_wbase = wbase
    if faces == 2 and wbase < 0.5:
        effective_wbase = 1.8
    elif faces == 1:
        effective_wbase = 0.0

    level_widths = []
    for z in levels:
        if faces == 1:
            w = 0.0
        elif z >= taper_z_top:
            w = top_w
        else:
            ratio = (z / taper_z_top) if taper_z_top > 0 else 1.0
            w = effective_wbase - ratio * (effective_wbase - top_w)
        level_widths.append(round(w, 4))

    nodes: dict[int, dict] = {}
    node_seq = 1
    level_node_map: dict[tuple[int, int], int] = {}

    for lvl_idx, (z, w) in enumerate(zip(levels, level_widths)):
        half_w = max(w / 2.0, 0.1)
        if faces == 1:
            # Monopole / Single Pole: 1 central pole axis
            coords = [(0.0, 0.0)]
        elif faces == 2:
            # 2-Pole Tower: 2 vertical poles spaced by w along X-axis
            coords = [
                (-half_w, 0.0),  # Pole 1 (Leg A)
                (half_w, 0.0),   # Pole 2 (Leg B)
            ]
        elif faces == 3:
            r = half_w / (3.0**0.5 / 2.0)
            coords = [
                (0.0, r),
                (-half_w, -r / 2.0),
                (half_w, -r / 2.0),
            ]
        else:
            coords = [
                (-half_w, -half_w),  # Leg A (1)
                (half_w, -half_w),   # Leg B (2)
                (half_w, half_w),    # Leg C (3)
                (-half_w, half_w),   # Leg D (4)
            ]

        is_base = (lvl_idx == 0)
        restr = "111111" if is_base else "000000"

        for leg_idx, (x, y) in enumerate(coords, 1):
            lbl = lvl_idx * 100 + leg_idx if lvl_idx > 0 else leg_idx
            nodes[node_seq] = {
                "label": lbl,
                "x": round(x, 4),
                "y": round(y, 4),
                "z": z,
                "restraint": restr,
                "flag": 0,
            }
            level_node_map[(lvl_idx, leg_idx)] = node_seq
            node_seq += 1

    members: list[dict] = []
    memb_id = 1
    panel_map = {p["id"]: p for p in sorted_panels}

    # Strut section preference
    strut_sec_id = 1
    if sections:
        # Prefer smaller CHS (e.g. CHS60X3.9 or sec 2)
        for sid, sinfo in sections.items():
            s_name = sinfo.get("sec_name", "").upper()
            if "CHS60" in s_name or "CHS76" in s_name or "EA50" in s_name:
                strut_sec_id = sid
                break
        else:
            strut_sec_id = min(sections.keys(), key=lambda s: sections[s].get("ag_mm2", 9999))

    # --- Case 1: Single Pole / Monopole with Support Legs / Kickers ---
    if faces == 1:
        for lvl_idx in range(N):
            panel_id = N - lvl_idx
            p_info = panel_map.get(panel_id, {})
            leg_sec = p_info.get("leg_sec", 1)
            ni = level_node_map[(lvl_idx, 1)]
            nj = level_node_map[(lvl_idx + 1, 1)]
            dz = nodes[nj]["z"] - nodes[ni]["z"]
            members.append({
                "id": memb_id,
                "ni": ni,
                "nj": nj,
                "sec_id": leg_sec,
                "length": round(abs(dz), 4),
            })
            memb_id += 1

        # Add support legs (kickers)
        strut_lvl = max(1, N // 2)
        p_joint = level_node_map[(strut_lvl, 1)]
        base_center = level_node_map[(0, 1)]

        feet = []
        if support_coords:
            for sc in support_coords:
                if abs(sc["x"]) > 0.05 or abs(sc["y"]) > 0.05:
                    feet.append((sc["x"], sc["y"]))
        if not feet:
            feet = [(-2.5, 0.0), (0.0, 2.5)]

        for f_idx, (fx, fy) in enumerate(feet, 1):
            nodes[node_seq] = {
                "label": 900 + f_idx,
                "x": round(fx, 4),
                "y": round(fy, 4),
                "z": 0.0,
                "restraint": "111111",
                "flag": 0,
            }
            foot_nid = node_seq
            node_seq += 1

            # Inclined strut member
            dx = nodes[p_joint]["x"] - fx
            dy = nodes[p_joint]["y"] - fy
            dz = nodes[p_joint]["z"] - 0.0
            L_strut = (dx * dx + dy * dy + dz * dz) ** 0.5
            members.append({
                "id": memb_id,
                "ni": foot_nid,
                "nj": p_joint,
                "sec_id": strut_sec_id,
                "length": round(L_strut, 4),
            })
            memb_id += 1

            # Horizontal base tie to pole base
            dx_b = nodes[base_center]["x"] - fx
            dy_b = nodes[base_center]["y"] - fy
            L_base = (dx_b * dx_b + dy_b * dy_b) ** 0.5
            members.append({
                "id": memb_id,
                "ni": foot_nid,
                "nj": base_center,
                "sec_id": strut_sec_id,
                "length": round(L_base, 4),
                "typ": "BASE_TIE",
            })
            memb_id += 1

        # Add antenna mounting arms (ARMS) and support struts at the top elevation
        arm_lvl = N
        p_arm_node = level_node_map[(arm_lvl, 1)]
        z_arm = nodes[p_arm_node]["z"]
        l_arm = 1.0  # 1.0m arm radius

        # Tri-sector arms at 0°, 120°, 240°
        arm_angles = [0.0, 120.0, 240.0]
        for a_idx, ang_deg in enumerate(arm_angles, 1):
            rad = math.radians(ang_deg)
            ax = round(l_arm * math.cos(rad), 4)
            ay = round(l_arm * math.sin(rad), 4)

            nodes[node_seq] = {
                "label": 800 + a_idx,
                "x": ax,
                "y": ay,
                "z": z_arm,
                "restraint": "000000",
                "flag": 0,
            }
            tip_nid = node_seq
            node_seq += 1

            # 1. Horizontal Cantilever Arm member from pole to tip
            dx_a = ax - nodes[p_arm_node]["x"]
            dy_a = ay - nodes[p_arm_node]["y"]
            L_arm_m = (dx_a * dx_a + dy_a * dy_a) ** 0.5
            members.append({
                "id": memb_id,
                "ni": p_arm_node,
                "nj": tip_nid,
                "sec_id": strut_sec_id,
                "length": round(L_arm_m, 4),
                "typ": "ARM",
            })
            memb_id += 1

            # 2. Vertical antenna mount pipe at tip (length 1.5m)
            nodes[node_seq] = {
                "label": 810 + a_idx,
                "x": ax,
                "y": ay,
                "z": round(z_arm + 0.75, 4),
                "restraint": "000000",
                "flag": 0,
            }
            pipe_top = node_seq
            node_seq += 1

            nodes[node_seq] = {
                "label": 820 + a_idx,
                "x": ax,
                "y": ay,
                "z": round(z_arm - 0.75, 4),
                "restraint": "000000",
                "flag": 0,
            }
            pipe_bot = node_seq
            node_seq += 1

            members.append({
                "id": memb_id,
                "ni": pipe_bot,
                "nj": tip_nid,
                "sec_id": strut_sec_id,
                "length": 0.75,
                "typ": "MOUNT",
            })
            memb_id += 1

            members.append({
                "id": memb_id,
                "ni": tip_nid,
                "nj": pipe_top,
                "sec_id": strut_sec_id,
                "length": 0.75,
                "typ": "MOUNT",
            })
            memb_id += 1

            # 3. Inclined support arm (skur arm) back to pole at (N-1)
            if N >= 2:
                lower_p_node = level_node_map[(N - 1, 1)]
                dx_s = nodes[lower_p_node]["x"] - ax
                dy_s = nodes[lower_p_node]["y"] - ay
                dz_s = nodes[lower_p_node]["z"] - z_arm
                L_skur_arm = (dx_s * dx_s + dy_s * dy_s + dz_s * dz_s) ** 0.5
                members.append({
                    "id": memb_id,
                    "ni": tip_nid,
                    "nj": lower_p_node,
                    "sec_id": strut_sec_id,
                    "length": round(L_skur_arm, 4),
                    "typ": "STRUT_ARM",
                })
                memb_id += 1

        return nodes, members

    # --- Case 2: 2-Pole Tower (Twin Pole / H-Frame) with Support Legs & Arms ---
    if faces == 2:
        for lvl_idx in range(N):
            panel_id = N - lvl_idx
            p_info = panel_map.get(panel_id, {})
            leg_sec = p_info.get("leg_sec", 1)
            brc_sec = p_info.get("brc_sec", 1)
            hor_sec = p_info.get("hor_sec", brc_sec)

            # Leg 1 (Pole 1) & Leg 2 (Pole 2)
            for leg in (1, 2):
                ni = level_node_map[(lvl_idx, leg)]
                nj = level_node_map[(lvl_idx + 1, leg)]
                dz = nodes[nj]["z"] - nodes[ni]["z"]
                members.append({
                    "id": memb_id,
                    "ni": ni,
                    "nj": nj,
                    "sec_id": leg_sec,
                    "length": round(abs(dz), 4),
                })
                memb_id += 1

            # Horizontal tie member at panel top
            ni = level_node_map[(lvl_idx + 1, 1)]
            nj = level_node_map[(lvl_idx + 1, 2)]
            dx = nodes[nj]["x"] - nodes[ni]["x"]
            members.append({
                "id": memb_id,
                "ni": ni,
                "nj": nj,
                "sec_id": hor_sec,
                "length": round(abs(dx), 4),
            })
            memb_id += 1

            # If base level, also add horizontal base tie between Pole 1 and Pole 2
            if lvl_idx == 0:
                ni_b = level_node_map[(0, 1)]
                nj_b = level_node_map[(0, 2)]
                dx_b = nodes[nj_b]["x"] - nodes[ni_b]["x"]
                members.append({
                    "id": memb_id,
                    "ni": ni_b,
                    "nj": nj_b,
                    "sec_id": hor_sec,
                    "length": round(abs(dx_b), 4),
                })
                memb_id += 1

            # Diagonal X-bracing between Pole 1 and Pole 2
            b_bot1 = level_node_map[(lvl_idx, 1)]
            b_bot2 = level_node_map[(lvl_idx, 2)]
            b_top1 = level_node_map[(lvl_idx + 1, 1)]
            b_top2 = level_node_map[(lvl_idx + 1, 2)]

            dx1 = nodes[b_top2]["x"] - nodes[b_bot1]["x"]
            dz1 = nodes[b_top2]["z"] - nodes[b_bot1]["z"]
            L1 = (dx1 * dx1 + dz1 * dz1) ** 0.5
            members.append({
                "id": memb_id,
                "ni": b_bot1,
                "nj": b_top2,
                "sec_id": brc_sec,
                "length": round(L1, 4),
            })
            memb_id += 1

            dx2 = nodes[b_top1]["x"] - nodes[b_bot2]["x"]
            dz2 = nodes[b_top1]["z"] - nodes[b_bot2]["z"]
            L2 = (dx2 * dx2 + dz2 * dz2) ** 0.5
            members.append({
                "id": memb_id,
                "ni": b_bot2,
                "nj": b_top1,
                "sec_id": brc_sec,
                "length": round(L2, 4),
            })
            memb_id += 1

        # Out-of-plane support legs / kickers (struts) for lateral stability
        strut_lvl = max(1, N // 2)
        joint_p1 = level_node_map[(strut_lvl, 1)]
        joint_p2 = level_node_map[(strut_lvl, 2)]
        base_p1 = level_node_map[(0, 1)]
        base_p2 = level_node_map[(0, 2)]

        y_offset = max(2.0, round(effective_wbase * 1.5, 2))
        feet_p = [
            (nodes[base_p1]["x"], -y_offset, joint_p1, base_p1),  # Strut 1 for Pole 1
            (nodes[base_p2]["x"], -y_offset, joint_p2, base_p2),  # Strut 2 for Pole 2
        ]

        strut_feet_nids = []
        for s_idx, (fx, fy, joint_nid, base_nid) in enumerate(feet_p, 1):
            nodes[node_seq] = {
                "label": 910 + s_idx,
                "x": round(fx, 4),
                "y": round(fy, 4),
                "z": 0.0,
                "restraint": "111111",
                "flag": 0,
            }
            foot_nid = node_seq
            strut_feet_nids.append(foot_nid)
            node_seq += 1

            # Inclined strut to pole
            dx = nodes[joint_nid]["x"] - fx
            dy = nodes[joint_nid]["y"] - fy
            dz = nodes[joint_nid]["z"] - 0.0
            L_strut = (dx * dx + dy * dy + dz * dz) ** 0.5
            members.append({
                "id": memb_id,
                "ni": foot_nid,
                "nj": joint_nid,
                "sec_id": strut_sec_id,
                "length": round(L_strut, 4),
            })
            memb_id += 1

            # Base tie from strut foot to pole base
            dx_b = nodes[base_nid]["x"] - fx
            dy_b = nodes[base_nid]["y"] - fy
            L_b = (dx_b * dx_b + dy_b * dy_b) ** 0.5
            members.append({
                "id": memb_id,
                "ni": foot_nid,
                "nj": base_nid,
                "sec_id": strut_sec_id,
                "length": round(L_b, 4),
            })
            memb_id += 1

        # Horizontal tie connecting the two strut feet
        if len(strut_feet_nids) == 2:
            dx_feet = nodes[strut_feet_nids[1]]["x"] - nodes[strut_feet_nids[0]]["x"]
            members.append({
                "id": memb_id,
                "ni": strut_feet_nids[0],
                "nj": strut_feet_nids[1],
                "sec_id": strut_sec_id,
                "length": round(abs(dx_feet), 4),
                "typ": "BASE_TIE",
            })
            memb_id += 1

        # Add antenna mounting arms (ARMS) on Pole 1 and Pole 2 at top elevation
        top_p1 = level_node_map[(N, 1)]
        top_p2 = level_node_map[(N, 2)]
        z_top = nodes[top_p1]["z"]
        l_arm = 1.0

        for p_idx, pole_nid in enumerate([top_p1, top_p2], 1):
            px = nodes[pole_nid]["x"]
            for dir_idx, dy_arm in enumerate([l_arm, -l_arm], 1):
                nodes[node_seq] = {
                    "label": 830 + p_idx * 10 + dir_idx,
                    "x": px,
                    "y": dy_arm,
                    "z": z_top,
                    "restraint": "000000",
                    "flag": 0,
                }
                tip_nid = node_seq
                node_seq += 1

                # Horizontal arm
                members.append({
                    "id": memb_id,
                    "ni": pole_nid,
                    "nj": tip_nid,
                    "sec_id": strut_sec_id,
                    "length": round(abs(dy_arm), 4),
                    "typ": "ARM",
                })
                memb_id += 1

                # Vertical mount pipe
                nodes[node_seq] = {
                    "label": 850 + p_idx * 10 + dir_idx,
                    "x": px,
                    "y": dy_arm,
                    "z": round(z_top + 0.75, 4),
                    "restraint": "000000",
                    "flag": 0,
                }
                ptop = node_seq
                node_seq += 1
                nodes[node_seq] = {
                    "label": 870 + p_idx * 10 + dir_idx,
                    "x": px,
                    "y": dy_arm,
                    "z": round(z_top - 0.75, 4),
                    "restraint": "000000",
                    "flag": 0,
                }
                pbot = node_seq
                node_seq += 1

                members.append({
                    "id": memb_id,
                    "ni": pbot,
                    "nj": tip_nid,
                    "sec_id": strut_sec_id,
                    "length": 0.75,
                    "typ": "MOUNT",
                })
                memb_id += 1

                members.append({
                    "id": memb_id,
                    "ni": tip_nid,
                    "nj": ptop,
                    "sec_id": strut_sec_id,
                    "length": 0.75,
                    "typ": "MOUNT",
                })
                memb_id += 1

                # Inclined support arm (skur arm) back to pole at (N-1)
                if N >= 2:
                    lower_pole = level_node_map[(N - 1, p_idx)]
                    dx_s = nodes[lower_pole]["x"] - px
                    dy_s = nodes[lower_pole]["y"] - dy_arm
                    dz_s = nodes[lower_pole]["z"] - z_top
                    L_skur = (dx_s * dx_s + dy_s * dy_s + dz_s * dz_s) ** 0.5
                    members.append({
                        "id": memb_id,
                        "ni": tip_nid,
                        "nj": lower_pole,
                        "sec_id": strut_sec_id,
                        "length": round(L_skur, 4),
                        "typ": "STRUT_ARM",
                    })
                    memb_id += 1

        return nodes, members

    # --- Case 3 & 4: 3-Leg and 4-Leg Lattice SST ---
    num_legs = faces
    for lvl_idx in range(N):
        panel_id = N - lvl_idx
        p_info = panel_map.get(panel_id, {})
        leg_sec = p_info.get("leg_sec", 1)
        brc_sec = p_info.get("brc_sec", 1)
        hor_sec = p_info.get("hor_sec", brc_sec)

        # 1. Leg members
        for leg in range(1, num_legs + 1):
            ni = level_node_map[(lvl_idx, leg)]
            nj = level_node_map[(lvl_idx + 1, leg)]
            dx = nodes[nj]["x"] - nodes[ni]["x"]
            dy = nodes[nj]["y"] - nodes[ni]["y"]
            dz = nodes[nj]["z"] - nodes[ni]["z"]
            L = (dx * dx + dy * dy + dz * dz) ** 0.5
            members.append({
                "id": memb_id,
                "ni": ni,
                "nj": nj,
                "sec_id": leg_sec,
                "length": round(L, 4),
            })
            memb_id += 1

        # 2. Horizontal members at panel top
        for leg in range(1, num_legs + 1):
            next_leg = (leg % num_legs) + 1
            ni = level_node_map[(lvl_idx + 1, leg)]
            nj = level_node_map[(lvl_idx + 1, next_leg)]
            dx = nodes[nj]["x"] - nodes[ni]["x"]
            dy = nodes[nj]["y"] - nodes[ni]["y"]
            dz = nodes[nj]["z"] - nodes[ni]["z"]
            L = (dx * dx + dy * dy + dz * dz) ** 0.5
            members.append({
                "id": memb_id,
                "ni": ni,
                "nj": nj,
                "sec_id": hor_sec,
                "length": round(L, 4),
            })
            memb_id += 1

        # 3. X-Bracing members across each face
        for leg in range(1, num_legs + 1):
            next_leg = (leg % num_legs) + 1
            b_bot1 = level_node_map[(lvl_idx, leg)]
            b_bot2 = level_node_map[(lvl_idx, next_leg)]
            b_top1 = level_node_map[(lvl_idx + 1, leg)]
            b_top2 = level_node_map[(lvl_idx + 1, next_leg)]

            dx1 = nodes[b_top2]["x"] - nodes[b_bot1]["x"]
            dy1 = nodes[b_top2]["y"] - nodes[b_bot1]["y"]
            dz1 = nodes[b_top2]["z"] - nodes[b_bot1]["z"]
            L1 = (dx1 * dx1 + dy1 * dy1 + dz1 * dz1) ** 0.5
            members.append({
                "id": memb_id,
                "ni": b_bot1,
                "nj": b_top2,
                "sec_id": brc_sec,
                "length": round(L1, 4),
            })
            memb_id += 1

            dx2 = nodes[b_top1]["x"] - nodes[b_bot2]["x"]
            dy2 = nodes[b_top1]["y"] - nodes[b_bot2]["y"]
            dz2 = nodes[b_top1]["z"] - nodes[b_bot2]["z"]
            L2 = (dx2 * dx2 + dy2 * dy2 + dz2 * dz2) ** 0.5
            members.append({
                "id": memb_id,
                "ni": b_bot2,
                "nj": b_top1,
                "sec_id": brc_sec,
                "length": round(L2, 4),
            })
            memb_id += 1

    return nodes, members


def parse_td_content(td_content: str | bytes) -> tuple[dict[int, dict], list[dict], dict[int, dict]]:
    """Parse a native MS-Tower Tower Definition (.td) file or reconstructed text.

    Returns: (nodes, members, sections)
    """
    if isinstance(td_content, bytes):
        text = td_content.decode("latin1", errors="ignore")
    else:
        text = td_content

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    nodes: dict[int, dict] = {}
    members: list[dict] = []
    sections: dict[int, dict] = {}
    seq = 1

    in_nodes = False
    in_members = False
    in_sections = False

    for line in lines:
        u = line.upper()
        if u.startswith(("COORDINATES", "NODES")):
            in_nodes = True
            in_members = False
            in_sections = False
            continue
        if u.startswith(("MEMBERS", "CONNECTIVITY")):
            in_nodes = False
            in_members = True
            in_sections = False
            continue
        if u.startswith(("SECTIONS", "PROFILES")):
            in_nodes = False
            in_members = False
            in_sections = True
            continue

        # 1. Standard Fortran patterns first
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
            members.append({
                "id": int(m_memb.group(1)),
                "ni": int(m_memb.group(2)),
                "nj": int(m_memb.group(3)),
                "sec_id": int(m_memb.group(5)),
                "length": float(m_memb.group(8)),
            })
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
            continue

        # 2. Text keywords fallback (e.g. NODE 1 0.0 0.0 0.0 111111)
        toks = line.split()
        if (toks[0].upper() == "NODE" or in_nodes) and len(toks) >= 4:
            try:
                shift = 1 if toks[0].upper() == "NODE" else 0
                lbl = int(toks[shift])
                x = float(toks[shift + 1])
                y = float(toks[shift + 2])
                z = float(toks[shift + 3])
                restraint = toks[shift + 4] if len(toks) > shift + 4 and len(toks[shift + 4]) == 6 else "000000"
                flag = int(toks[shift + 5]) if len(toks) > shift + 5 and toks[shift + 5].lstrip("+-").isdigit() else 0
                nodes[seq] = {
                    "label": lbl,
                    "x": x,
                    "y": y,
                    "z": z,
                    "restraint": restraint,
                    "flag": flag,
                }
                seq += 1
                continue
            except (ValueError, IndexError):
                pass

        if (toks[0].upper() == "MEMBER" or in_members) and len(toks) >= 4:
            try:
                shift = 1 if toks[0].upper() == "MEMBER" else 0
                mid = int(toks[shift])
                ni = int(toks[shift + 1])
                nj = int(toks[shift + 2])
                sec_id = int(toks[shift + 3])
                length = float(toks[shift + 4]) if len(toks) > shift + 4 else 1.5
                members.append({
                    "id": mid,
                    "ni": ni,
                    "nj": nj,
                    "sec_id": sec_id,
                    "length": length,
                })
                continue
            except (ValueError, IndexError):
                pass

        if (toks[0].upper() in ("SECTION", "PROFILE") or in_sections) and len(toks) >= 2:
            try:
                shift = 1 if toks[0].upper() in ("SECTION", "PROFILE") else 0
                sid = int(toks[shift])
                sname = toks[shift + 1]
                dims = parse_section_dimensions(sname, 0.00094, 4.48e-8)
                sections[sid] = {
                    "sec_id": sid,
                    "sec_name": sname,
                    "j_m4": 1.0e-8,
                    "iy_m4": 4.48e-8,
                    "iz_m4": 4.48e-8,
                    "a_m2": dims["ag_mm2"] * 1e-6,
                    **dims,
                }
                continue
            except (ValueError, IndexError):
                pass

    # Parse SUPPORT coordinates if present (e.g. COORD 0.0 0.0 16.00 FIXED)
    support_coords = []
    in_supp = False
    for ln in lines:
        uln = ln.upper().strip()
        if uln.startswith("SUPPORT"):
            in_supp = True
            continue
        if in_supp:
            if uln.startswith("END"):
                in_supp = False
                continue
            m_sc = re.search(r"COORD\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", ln, re.I)
            if m_sc:
                support_coords.append({
                    "x": float(m_sc.group(1)),
                    "y": float(m_sc.group(2)),
                    "z": float(m_sc.group(3)),
                    "restraint": "111111",
                })

    # If no explicit Cartesian nodes were parsed, compile from MS-Tower PANEL definitions
    if not nodes:
        wbase = 5.2
        faces = 4
        m_w = re.search(r"WBASE\s+([0-9.]+)", text, re.I)
        if m_w:
            wbase = float(m_w.group(1))

        m_f = re.search(r"FACES\s+(\d+)", text, re.I)
        if m_f:
            faces = int(m_f.group(1))
        else:
            u_td = text.upper()
            if any(k in u_td for k in ("2-POLE", "2 POLE", "TWIN POLE", "2POLE")):
                faces = 2
            elif any(k in u_td for k in ("ROOFTOP POLE", "RT_POLE", "RT-POLE", "POLE", "MONOPOLE")):
                faces = 1

        panels = []
        curr_p = None
        for line in lines:
            m_p = re.search(r"PANEL\s+(\d+)\s+HT\s+([0-9.]+)(?:\s+TW\s+([0-9.]+))?", line, re.I)
            if m_p:
                pid = int(m_p.group(1))
                ht = float(m_p.group(2))
                tw = float(m_p.group(3)) if m_p.group(3) else None
                curr_p = {"id": pid, "ht": ht, "tw": tw, "leg_sec": 1, "brc_sec": 1}
                panels.append(curr_p)
            elif curr_p and "LEG" in line.upper():
                m_leg = re.search(r"LEG\s+(\d+)", line, re.I)
                m_brc = re.search(r"BR1\s+(\d+)", line, re.I)
                if m_leg:
                    curr_p["leg_sec"] = int(m_leg.group(1))
                if m_brc:
                    curr_p["brc_sec"] = int(m_brc.group(1))

        if panels:
            nodes, members = compile_panels_to_geometry(
                panels,
                wbase=wbase,
                faces=faces,
                sections=sections,
                support_coords=support_coords,
            )

    # Normalize structural node Z so base sits at Z = 0.0 m
    struct_z = [n["z"] for n in nodes.values() if is_structural(n)]
    if struct_z:
        z_min = min(struct_z)
        if abs(z_min) > 1e-6:
            for n in nodes.values():
                if is_structural(n):
                    n["z"] = round(n["z"] - z_min, 5)

    # Attach section properties to members
    for m in members:
        sec = sections.get(m["sec_id"])
        if sec:
            m["sec_name"] = sec["sec_name"]
            m["a_m2"] = sec["a_m2"]
            m["iy_m4"] = sec["iy_m4"]
            m["iz_m4"] = sec["iz_m4"]
            m["j_m4"] = sec["j_m4"]

    return nodes, members, sections


def parse_td_twr_content(td_text: str, twr_text: str) -> tuple[dict[int, dict], list[dict], list[dict], dict[str, Any]]:
    """Combine extracted .td and .twr text into structural inputs for OpenSeesPy analysis."""
    nodes, members, _sections = parse_td_content(td_text)
    twr_data = parse_mst_twr_block(twr_text)
    devices = twr_data.get("ancillaries") or []
    twr_meta = {
        "vb_ms": twr_data.get("vb_ms") or 32.10,
        "exposure": twr_data.get("exposure") or "B",
    }
    return nodes, members, devices, twr_meta


def build_mst_file(
    nodes: dict[int, dict] | list[dict],
    members: list[dict],
    sections: dict[int, dict] | list[dict] | None = None,
    twr_text: str = "",
    rpt_text: str = "",
    header_comment: str = "TOWER DASHBOARD MODEL",
) -> bytes:
    """Assemble nodes, members, sections, TWR~, and RPT~ into standard Microstran / MS-Tower (.mst) format."""
    lines = [
        f"  MST MICROSTRAN MODEL EXPORT: {header_comment}",
        "DAT~",
    ]
    # Format nodes
    node_list = list(nodes.values()) if isinstance(nodes, dict) else list(nodes)
    for i, n in enumerate(node_list, 1):
        lbl = int(n.get("label") or n.get("id") or i)
        x = float(n.get("x", 0.0))
        y = float(n.get("y", 0.0))
        z = float(n.get("z", 0.0))
        restraint = str(n.get("restraint") or ("111111" if n.get("support") else "000000"))
        flag = int(n.get("flag", 0))
        lines.append(f"{lbl:6d} {x:14.6E} {y:14.6E} {z:14.6E} {restraint:6s} {flag:2d}")

    # Format members
    for i, m in enumerate(members, 1):
        mid = int(m.get("id") or i)
        ni = int(m.get("ni", 1))
        nj = int(m.get("nj", 2))
        sec_id = int(m.get("sec_id", 1))
        length = float(m.get("length", 1.5))
        lines.append(f"{mid:6d} {ni:6d} {nj:6d}      0 {sec_id:2d}   1 0 {length:6.4f}")

    # Format sections
    if isinstance(sections, dict):
        sec_dict = sections
    elif isinstance(sections, list):
        sec_dict = {s.get("sec_id", i + 1): s for i, s in enumerate(sections)}
    else:
        sec_dict = {}

    if not sec_dict:
        sec_dict = {
            1: {
                "sec_id": 1,
                "sec_name": "L70X70X7",
                "a_m2": 0.00094,
                "iy_m4": 4.48e-8,
                "iz_m4": 4.48e-8,
                "j_m4": 1.0e-8,
            }
        }

    for sid, s in sorted(sec_dict.items()):
        sname = str(s.get("sec_name") or f"SEC_{sid}").strip()
        a_m2 = float(s.get("a_m2", 0.00094))
        iy_m4 = float(s.get("iy_m4", 4.48e-8))
        iz_m4 = float(s.get("iz_m4", 4.48e-8))
        j_m4 = float(s.get("j_m4", 1.0e-8))
        lines.append(
            f"{sid:6d} {j_m4:13.6E} {iy_m4:13.6E} {iz_m4:13.6E} {a_m2:13.6E} "
            f"0.000000E+00 0.000000E+00 0.000000E+00 {sname}"
        )

    lines.append("AL4~")
    lines.append("TWR~")
    if twr_text:
        lines.append(twr_text.strip())
    else:
        lines.append("PARAMETERS\nTCAT 2\nVB 32.10\nROOFTOP 0.00\nEND")
    lines.append("OUT~")
    if rpt_text:
        lines.append("RPT~")
        lines.append(rpt_text.strip())
        lines.append("END_RPT~")

    return "\n".join(lines).encode("latin1", errors="replace")


def parse_mst_twr_block(raw_bytes: bytes | str) -> dict:
    """Extract embedded TWR~ parameters, ANCILLARIES inventory, LINEAR items, and inline $LIBRARY definitions."""
    if isinstance(raw_bytes, str):
        content = raw_bytes
    else:
        content = raw_bytes.decode("latin1", errors="ignore")

    idx = content.find("TWR~")
    if idx != -1:
        end_idx = content.find("OUT~", idx)
        twr_text = content[idx:end_idx] if end_idx != -1 else content[idx:idx + 30000]
    elif any(k in content.upper() for k in ("ANCILLARIES", "PARAMETERS", "TCAT", "VB ")):
        twr_text = content
    else:
        return {"vb_ms": None, "exposure": "C", "ancillaries": [], "linear_ancillaries": [], "inline_devices": []}

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

        # Summarize governing SR per category (LEG, BRACING, HORIZONTAL, REDUNDANT, OVERALL)
        for mid, info in rpt_by_member.items():
            t = info["typ"].upper()
            if t in ("LEG", "SHAFT", "POLE"):
                cat_key = "leg"
            elif t in ("BRC", "KBR", "XBR", "DBR", "MBR", "BR", "BR1", "BR2"):
                cat_key = "bracing"
            elif t in ("HOR", "PBR", "PB", "HBR", "H1", "PLAN"):
                cat_key = "horizontal"
            elif t in ("RED", "RBR", "R1", "R2", "SUB", "HIP"):
                cat_key = "redundant"
            else:
                cat_key = "other"
            if cat_key not in sr_summary or info["stress_ratio"] > sr_summary[cat_key]["stress_ratio"]:
                sr_summary[cat_key] = dict(info)
            if "overall" not in sr_summary or info["stress_ratio"] > sr_summary["overall"]["stress_ratio"]:
                sr_summary["overall"] = dict(info)

        # If RPT~ did not explicitly tag RED, pick the governing slender secondary/sub-bracing member
        if "redundant" not in sr_summary and rpt_by_member:
            used_pnls = {
                (sr_summary.get("bracing") or {}).get("pnl"),
                (sr_summary.get("horizontal") or {}).get("pnl"),
            }
            red_candidates = [
                info for info in rpt_by_member.values()
                if info["typ"].upper() not in ("LEG", "SHAFT", "POLE")
                and (info.get("kl_over_r", 0) >= 140.0 or "40" in info.get("sec_name", ""))
                and info.get("pnl") not in used_pnls
            ]
            if not red_candidates:
                red_candidates = [
                    info for info in rpt_by_member.values()
                    if info["typ"].upper() not in ("LEG", "SHAFT", "POLE")
                    and info.get("id") != (sr_summary.get("bracing") or {}).get("id")
                ]
            if red_candidates:
                best_red = dict(max(red_candidates, key=lambda x: x["stress_ratio"]))
                best_red["typ"] = "RED"
                sr_summary["redundant"] = best_red

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


def _rpt_text(raw_bytes: bytes | str) -> str:
    """Return the RPT~ block or raw report text as clean text (DOS cp437 so 'φ' renders correctly)."""
    if isinstance(raw_bytes, str):
        text = raw_bytes
    else:
        idx = raw_bytes.find(b"RPT~")
        if idx != -1:
            end = raw_bytes.find(b"EOF~", idx)
            chunk = raw_bytes[idx:end if end != -1 else len(raw_bytes)]
            text = chunk.decode("cp437", errors="replace")
        elif b"MEMBER CHECKING" in raw_bytes or b"SUPPORT REACTIONS" in raw_bytes or b"Job:" in raw_bytes:
            text = raw_bytes.decode("cp437", errors="replace")
        else:
            return ""
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
        dim_m = max(float(dev.get("dim_m") or 0.5), 0.12)
        af = float(dev.get("af_m2") or 0.0)
        asf = float(dev.get("asf_m2") or 0.0)
        ca = float(dev.get("ca_factor") or compute_tia_ca(shape, dim_m, af))
        if shape in ("SH1", "SHIELDED", "STD", "RAD"):
            # Microwave dish: diameter = dim_m, depth derived from Asf/Dim or 0.38*diameter
            d_dish = (asf / dim_m) if (dim_m > 0 and asf > 0) else max(0.22, dim_m * 0.38)
            return {
                "shape_type": shape,
                "dim_m": round(dim_m, 3),
                "af_m2": round(af, 4),
                "asf_m2": round(asf, 4),
                "ca_factor": round(ca, 3),
                "length_m": round(dim_m, 3),
                "width_m": round(dim_m, 3),
                "depth_m": round(min(max(d_dish, 0.18), max(dim_m * 0.65, 0.35)), 3),
            }
        if shape == "CYL":
            # Cylindrical omni / pipe antenna: height = dim_m, diameter = Af / dim_m
            diam = (af / dim_m) if (dim_m > 0 and af > 0) else 0.16
            diam_clamped = round(min(max(diam, 0.08), 1.50), 3)
            return {
                "shape_type": shape,
                "dim_m": round(dim_m, 3),
                "af_m2": round(af, 4),
                "asf_m2": round(asf, 4),
                "ca_factor": round(ca, 3),
                "length_m": round(dim_m, 3),
                "width_m": diam_clamped,
                "depth_m": diam_clamped,
            }
        # BOX / GRID / UNITY: height = dim_m, width = Af / dim_m, depth = Asf / dim_m
        w = (af / dim_m) if (dim_m > 0 and af > 0) else 0.35
        d = (asf / dim_m) if (dim_m > 0 and asf > 0) else 0.18
        return {
            "shape_type": shape,
            "dim_m": round(dim_m, 3),
            "af_m2": round(af, 4),
            "asf_m2": round(asf, 4),
            "ca_factor": round(ca, 3),
            "length_m": round(dim_m, 3),
            "width_m": round(min(max(w, 0.10), 3.20), 3),
            "depth_m": round(min(max(d, 0.08), 1.80), 3),
        }

    prefix, num = _extract_prefix_and_dim(fallback_name)
    dim_m = num if (num and 0.1 <= num <= 6.0) else 0.60
    shape = "SHIELDED" if prefix in ("MW", "SH", "DISH") else ("CYL" if prefix == "GSM" else "BOX")
    w_fb = dim_m if shape == "SHIELDED" else (0.35 if dim_m >= 1.0 else 0.28)
    d_fb = round(max(0.22, dim_m * 0.38), 3) if shape == "SHIELDED" else (0.20 if dim_m >= 1.0 else 0.16)
    af_fb = round(dim_m * w_fb, 4)
    asf_fb = round(dim_m * d_fb, 4)
    return {
        "shape_type": shape,
        "dim_m": round(dim_m, 3),
        "af_m2": af_fb,
        "asf_m2": asf_fb,
        "ca_factor": round(compute_tia_ca(shape, dim_m, af_fb), 3),
        "length_m": round(dim_m, 3),
        "width_m": round(w_fb, 3),
        "depth_m": round(d_fb, 3),
    }


def build_td_twr_bundle_archive(
    site: str,
    raw_mst: bytes | None,
    nodes: list[dict],
    members: list[dict],
    site_devices: list[dict],
    project_lib_devices: list[dict],
    rpt_text: str = "",
    reactions: list[dict] | None = None,
    source_lib_path: Path | None = None,
) -> bytes:
    """Convert tower geometry, loading, project .lib, and report into native MS-Tower (.td, .twr, .lib, .rpt, .p1) packaged in a .rar/.zip archive."""
    safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in site) or "SITE"
    raw_text = raw_mst.decode("latin1", errors="ignore") if raw_mst else ""

    # 1. Extract or synthesize {SITE}.td (Tower Definition)
    td_text = ""
    if "TD~" in raw_text:
        idx = raw_text.find("TD~") + 3
        end_idx = raw_text.find("TWR~", idx)
        if end_idx == -1:
            end_idx = raw_text.find("DAT~", idx)
        td_text = raw_text[idx:end_idx].strip() if end_idx != -1 else raw_text[idx:idx + 25000].strip()

    if not td_text:
        struct_nodes = [n for n in nodes if abs(float(n.get("x", 0))) <= 1e4]
        z_vals = [float(n.get("z", 0.0)) for n in struct_nodes] or [0.0, 25.0]
        h_max = max(z_vals) - min(z_vals)
        base_nodes = [n for n in struct_nodes if abs(float(n.get("z", 0.0)) - min(z_vals)) < 0.25]
        xs = [float(n.get("x", 0.0)) for n in base_nodes] or [-1.35, 1.35]
        w_base = max(round(max(xs) - min(xs), 3), 1.2)
        td_lines = [
            f"TITLE {site} - TOWER DEFINITION (.td)",
            "$ Generated by Tower Studio Engineering Workbench",
            "UNITS METRES",
            "PROFILE",
            f"FACES {4 if len(base_nodes) >= 4 else (3 if len(base_nodes) == 3 else (2 if len(base_nodes) == 2 else 1))}",
            f"WBASE {w_base:.3f}",
            "RLBASE 0.000",
            f"PANEL 1 HT {max(h_max, 3.0):.3f} TW {max(w_base * 0.45, 0.6):.3f}",
            "  FACE X  LEG 1 BR1 2 H1 2",
            "END",
            "",
            "$ EXPLICIT SPACE-FRAME NODES & MEMBERS",
            f"$ TOTAL NODES: {len(struct_nodes)} | TOTAL MEMBERS: {len(members)}",
        ]
        for n in struct_nodes[:400]:
            lbl = int(n.get("label") or n.get("id") or 1)
            td_lines.append(
                f"$ NODE {lbl:5d}  X={float(n.get('x', 0)):8.3f}  Y={float(n.get('y', 0)):8.3f}  Z={float(n.get('z', 0)):8.3f}  REST={n.get('restraint', '000000')}"
            )
        td_lines.append("EOF")
        td_text = "\n".join(td_lines) + "\n"

    # 2. Extract or synthesize {SITE}.twr (Tower Loading & Ancillaries)
    twr_meta = parse_mst_twr_block(raw_mst) if raw_mst else {"vb_ms": 32.10, "exposure": "B"}
    vb_ms = twr_meta.get("vb_ms") or 32.10
    exp = twr_meta.get("exposure") or "B"
    tcat = {"B": 2, "C": 3, "D": 4}.get(str(exp).upper(), 2)

    twr_lines = [
        f"TITLE {site} - TOWER LOADING & ANCILLARIES (.twr)",
        "$ Generated by Tower Studio (TIA-222-G / MS-Tower V6)",
        "PARAMETERS",
        "  CODE TIA222G",
        f"  TCAT {tcat}",
        f"  VB {vb_ms:.2f}",
        "  ROOFTOP 0.00",
        "  CLASS 2",
        "END",
        "",
        "ANCILLARIES",
        f"  LIB {safe_name}.lib",
    ]
    existing_devs = [d for d in site_devices if d.get("status") == "EXISTING"]
    proposed_devs = [d for d in site_devices if d.get("status") == "PROPOSED"]

    if existing_devs:
        twr_lines.append("$==============================EXISTING=======================================")
        for idx, d in enumerate(existing_devs, 1):
            x_a = float(d.get("x_m") or 1.0)
            y_a = float(d.get("y_m") or 1.0)
            z_a = float(d.get("elev_z_m") or 15.0)
            ang = float(d.get("azimuth_deg") or 0.0)
            mass = float(d.get("mass_kg") or 20.0)
            qty = int(d.get("qty") or 1)
            for q_i in range(max(1, qty)):
                tag = f"EX{idx:02d}" if qty == 1 else f"EX{idx:02d}_{q_i+1}"
                twr_lines.append(
                    f"  {tag:<8s} XA {x_a:6.2f} YA {y_a:6.2f} ZA {z_a:6.2f} LIB {d['device_name']:<14s} ANG {ang:5.1f} AMASS {mass:5.1f} $ {d.get('tenant', '')} ({d.get('mounting_name') or 'LEG A'})"
                )

    if proposed_devs:
        twr_lines.append("$==============================PROPOSED=======================================")
        for idx, d in enumerate(proposed_devs, 1):
            x_a = float(d.get("x_m") or 1.0)
            y_a = float(d.get("y_m") or 1.0)
            z_a = float(d.get("elev_z_m") or 15.0)
            ang = float(d.get("azimuth_deg") or 0.0)
            mass = float(d.get("mass_kg") or 20.0)
            qty = int(d.get("qty") or 1)
            for q_i in range(max(1, qty)):
                tag = f"PR{idx:02d}" if qty == 1 else f"PR{idx:02d}_{q_i+1}"
                twr_lines.append(
                    f"  {tag:<8s} XA {x_a:6.2f} YA {y_a:6.2f} ZA {z_a:6.2f} LIB {d['device_name']:<14s} ANG {ang:5.1f} AMASS {mass:5.1f} $ {d.get('tenant', '')} ({d.get('mounting_name') or 'LEG A'})"
                )

    twr_lines.extend(["END", "EOF", ""])
    twr_text = "\n".join(twr_lines)

    # 3. Build project-specific {SITE}.lib (only devices used in this project + coefficients)
    lib_text = export_devices_as_lib(project_lib_devices, source_lib_path=source_lib_path)

    # 4. Build {SITE}.p1 (Nodal Reactions & Displacements summary)
    p1_lines = [
        f"MS-TOWER P1 OUTPUT — SITE: {site}",
        "SUPPORT REACTIONS ENVELOPE (kN)",
        "NODE      FX(kN)      FY(kN)      FZ(kN)   STATUS",
    ]
    for r in (reactions or []):
        lbl = r.get("node_label", 1)
        pu = float(r.get("pu_kn", 0.0))
        tu = float(r.get("tu_kn", 0.0))
        vu = float(r.get("vu_kn", 0.0))
        p1_lines.append(f"{int(lbl):4d}  {vu:10.3f}  {0.0:10.3f}  {pu:10.3f}   COMP_MAX (UPLIFT={tu:.2f} kN)")
    p1_lines.append("EOF\n")
    p1_text = "\n".join(p1_lines)

    # 5. Build CSV inventory of project devices
    csv_io = io.StringIO()
    writer = csv.writer(csv_io)
    writer.writerow([
        "ID", "Status", "Tenant", "Device_Name", "In_Master_Lib", "Shape",
        "Height_Dim_m", "Width_m", "Depth_m", "Af_m2", "Asf_m2", "Ca", "EPA_m2",
        "Mass_kg", "Elev_Z_m", "Face", "Mounting", "Qty",
    ])
    for d in site_devices:
        writer.writerow([
            d.get("id", ""),
            d.get("status", ""),
            d.get("tenant", ""),
            d.get("device_name", ""),
            "YES" if d.get("in_library") else "AUTO_MAPPED",
            d.get("shape_type", "BOX"),
            d.get("length_m", 0.0),
            d.get("width_m", 0.0),
            d.get("depth_m", 0.0),
            d.get("af_m2", 0.0),
            d.get("asf_m2", 0.0),
            d.get("ca_factor", 1.2),
            d.get("epa_m2", 0.0),
            d.get("mass_kg", 0.0),
            d.get("elev_z_m", 0.0),
            d.get("face", "A"),
            d.get("mounting_name", ""),
            d.get("qty", 1),
        ])

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{safe_name}.td", td_text.encode("latin1", errors="replace"))
        zf.writestr(f"{safe_name}.twr", twr_text.encode("latin1", errors="replace"))
        zf.writestr(f"{safe_name}.lib", lib_text.encode("latin1", errors="replace"))
        if rpt_text:
            zf.writestr(f"{safe_name}.rpt", rpt_text.encode("utf-8", errors="replace"))
        zf.writestr(f"{safe_name}.p1", p1_text.encode("latin1", errors="replace"))
        zf.writestr(f"{safe_name}_PROJECT_DEVICES.csv", csv_io.getvalue().encode("utf-8"))

    return buf.getvalue()


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

