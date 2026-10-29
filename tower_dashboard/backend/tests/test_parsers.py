import pytest

from opensees_model import velocity_pressure
from parsers import parse_ancillary_lib, parse_mst_content, summarize_geometry


def test_parse_mst_nodes_members(samples):
    nodes, members = parse_mst_content((samples / "SAMPLE-4LEG.mst").read_bytes())
    assert len(nodes) == 29          # 7 levels x 4 + 1 helper node
    assert len(members) == 96        # 72 legs/diagonals + 24 horizontals
    supports = [n for n in nodes.values() if n["restraint"] == "111111"]
    assert len(supports) == 4


def test_parse_mst_without_dat_block():
    with pytest.raises(ValueError, match="DAT~"):
        parse_mst_content(b"no block here")


def test_geometry_summary_ignores_helper_nodes(samples):
    nodes, _ = parse_mst_content((samples / "SAMPLE-4LEG.mst").read_bytes())
    geo = summarize_geometry(nodes)
    assert geo == {"height_m": 30.0, "top_width_m": 1.5, "bot_width_m": 4.0}


def test_parse_ancillary_lib(samples):
    df = parse_ancillary_lib((samples / "ANCILLARY.lib").read_text(encoding="latin1"))
    assert len(df) == 7
    sec = df.set_index("device_name").loc["SEC-2.76"]
    assert sec["ca_factor"] == 1.2
    assert sec["epa_m2"] == pytest.approx(0.96)
    assert "TELKOMSEL" in sec["category"]


def test_velocity_pressure_floor_and_growth():
    # Below 4.6 m the pressure is constant; it grows with height.
    assert velocity_pressure(0.0, 33.33) == velocity_pressure(4.6, 33.33)
    assert velocity_pressure(40.0, 33.33) > velocity_pressure(10.0, 33.33)
    # Hand check at z = 10 m, V = 33.33 m/s
    kz = 2.01 * (10.0 / 274.32) ** (2 / 9.5)
    assert velocity_pressure(10.0, 33.33) == pytest.approx(0.613 * kz * 0.85 * 33.33**2 / 1000)
