"""Generate SYNTHETIC sample files for development and tests.

These are NOT real Microstran exports. They only mimic the ASCII DAT~ block layout
that parsers.py expects, so the pipeline can be exercised end to end. Replace them
with real .mst / ANCILLARY.lib files to resolve PRD risks R-01 / R-02.

Usage:  python make_samples.py [output_dir]
"""
import math
import sys
from pathlib import Path


def build_tower(height=30.0, base=4.0, top=1.5, panels=6):
    """Square 4-leg lattice tower: legs, horizontals and X-bracing on every face."""
    nodes = []  # (x, y, z, restraint, flag)
    for k in range(panels + 1):
        z = height * k / panels
        half = (base + (top - base) * k / panels) / 2.0
        restraint = "111111" if k == 0 else "000000"
        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            nodes.append((sx * half, sy * half, z, restraint, 0))
    # One helper node that the parser/FEM must skip (flag -1, huge coordinate).
    nodes.append((9.99e5, 0.0, 0.0, "000000", -1))

    def nid(level, corner):
        return level * 4 + corner + 1  # 1-based sequential index

    pairs = []
    for k in range(panels):
        for c in range(4):
            pairs.append((nid(k, c), nid(k + 1, c), 1))                    # leg
            pairs.append((nid(k, c), nid(k + 1, (c + 1) % 4), 2))          # diagonal
            pairs.append((nid(k, (c + 1) % 4), nid(k + 1, c), 2))          # diagonal
    for k in range(1, panels + 1):
        for c in range(4):
            pairs.append((nid(k, c), nid(k, (c + 1) % 4), 3))              # horizontal
    return nodes, pairs


def write_mst(path: Path) -> None:
    nodes, pairs = build_tower()
    lines = ["MICROSTRAN SYNTHETIC SAMPLE (not a real export)", "DAT~"]
    for i, (x, y, z, r, f) in enumerate(nodes, start=1):
        lines.append(f"{i:6d} {x: .6E} {y: .6E} {z: .6E} {r} {f}")
    for m, (a, b, sec) in enumerate(pairs, start=1):
        na, nb = nodes[a - 1], nodes[b - 1]
        length = math.dist(na[:3], nb[:3])
        lines.append(f"{m:6d} {a:5d} {b:5d} 1 {sec:3d} 1 0 {length:.4f}")
    lines.append("AL4~")
    body = "\r\n".join(lines).encode("latin1")
    # Prefix/suffix some binary noise, like the partly-binary real files.
    path.write_bytes(b"\x00\x01MST\x00" + body + b"\r\n\x00\xff\x00")


ANCILLARY = """$ ========== TELKOMSEL ANTENNAS ==========
SEC-2.76    CYL  0.30  25.0  0.80  0.80  $ Sector antenna 2.76 m
SEC-1.50    CYL  0.26  15.0  0.45  0.45  $ Sector antenna 1.50 m
$ ========== IOH ANTENNAS ==========
IOH-SEC-2.0 BOX  0.30  20.0  0.60  0.60  $ Panel antenna 2.0 m
$ ========== MW DISHES ==========
MW-0.6      SH1  0.60  30.0  0.28  0.28  $ Microwave dish 0.6 m
MW-1.2      SH1  1.20  60.0  1.13  1.13  $ Microwave dish 1.2 m
$ ========== MOUNTING ==========
SECTOR-FRAME-A GRID 3.00 150.0 1.20 1.20 $ Sector frame
RRU-01      BOX  0.40  25.0  0.20  0.20  $ Remote radio unit
COEFFICIENTS
BOX 1.4
CYL 1.2
"""


def write_lib(path: Path) -> None:
    path.write_text(ANCILLARY, encoding="latin1")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "samples"
    out.mkdir(parents=True, exist_ok=True)
    write_mst(out / "SAMPLE-4LEG.mst")
    write_lib(out / "ANCILLARY.lib")
    print(f"Synthetic samples written to {out}")
