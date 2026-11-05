import pytest


def _upload(client, samples, name="SAMPLE-4LEG.mst"):
    with open(samples / "SAMPLE-4LEG.mst", "rb") as f:
        return client.post("/api/towers/upload", files={"file": (name, f, "application/octet-stream")})


def _import_lib(client, samples):
    with open(samples / "ANCILLARY.lib", "rb") as f:
        return client.post("/api/library/devices/import", files={"file": ("ANCILLARY.lib", f, "text/plain")})


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_version(client):
    res = client.get("/api/version").json()
    assert res["version"] == "2.3.0"
    assert "TIA-222-G" in res["standard"]


def test_upload_and_geometry(client, samples):
    r = _upload(client, samples, "site-001.mst")
    assert r.status_code == 200
    t = r.json()
    assert t["site_name"] == "SITE-001"
    assert t["height_m"] == 30.0
    geo = client.get("/api/towers/SITE-001/geometry").json()
    assert len(geo["nodes"]) == 28             # helper node filtered
    assert sum(n["support"] for n in geo["nodes"]) == 4
    assert len(geo["segments"]) == 96


def test_upload_rejects_wrong_extension(client):
    r = client.post("/api/towers/upload", files={"file": ("x.txt", b"DAT~", "text/plain")})
    assert r.status_code == 400
    assert r.json()["detail"] == "Only .mst and .pdf files are accepted."


def test_upload_without_dat_block(client):
    r = client.post("/api/towers/upload", files={"file": ("bad.mst", b"garbage", "application/octet-stream")})
    assert r.status_code == 422


def test_unknown_site_404(client):
    assert client.get("/api/towers/NOPE").status_code == 404


def test_reupload_keeps_inventory(client, samples):
    _upload(client, samples)
    body = {"status": "EXISTING", "tenant": "XL", "device_name": "SEC-1.50",
            "mounting_name": None, "elev_z_m": 25, "qty": 2}
    assert client.post("/api/sites/SAMPLE-4LEG/devices", json=body).status_code == 201
    _upload(client, samples)
    assert len(client.get("/api/sites/SAMPLE-4LEG/devices").json()) == 1


def test_inventory_validation(client, samples):
    _upload(client, samples)
    bad = {"status": "MAYBE", "tenant": "XL", "device_name": "A", "elev_z_m": 1, "qty": 0}
    assert client.post("/api/sites/SAMPLE-4LEG/devices", json=bad).status_code == 422


def test_library_import_and_search(client, samples):
    assert _import_lib(client, samples).json() == {"imported": 7}
    assert len(client.get("/api/library/devices", params={"q": "MW"}).json()) >= 2
    # Re-import upserts instead of duplicating.
    _import_lib(client, samples)
    assert len(client.get("/api/library/devices").json()) == 7


def test_analysis_is_reproducible_and_reacts_to_devices(client, samples):
    _upload(client, samples)
    _import_lib(client, samples)

    # Initial analysis is auto-run upon upload
    assert client.get("/api/sites/SAMPLE-4LEG/analysis/latest").status_code == 200

    r1 = client.post("/api/sites/SAMPLE-4LEG/analysis", json={"wind_speed_ms": 33.33}).json()
    r2 = client.post("/api/sites/SAMPLE-4LEG/analysis", json={"wind_speed_ms": 33.33}).json()
    assert len(r1["reactions"]) == 4
    assert r1["max_pu_kn"] == pytest.approx(r2["max_pu_kn"])
    assert r2["run_id"] == r1["run_id"] + 1

    # Statics hand check: sum of vertical reactions == total factored dead load (24 free nodes x 1.2 x 0.5 kN)
    net_z = sum(x["pu_kn"] - x["tu_kn"] for x in r1["reactions"])
    assert net_z == pytest.approx(24 * 1.2 * 0.5, rel=1e-3)

    dev = {"status": "PROPOSED", "tenant": "TELKOMSEL", "device_name": "MW-1.2",
           "mounting_name": "POLE", "elev_z_m": 28, "qty": 2}
    client.post("/api/sites/SAMPLE-4LEG/devices", json=dev)
    client.post("/api/sites/SAMPLE-4LEG/devices", json={**dev, "device_name": "UNKNOWN-X"})
    r3 = client.post("/api/sites/SAMPLE-4LEG/analysis", json={"wind_speed_ms": 33.33}).json()
    assert r3["max_pu_kn"] > r1["max_pu_kn"]
    assert r3["max_vu_kn"] > r1["max_vu_kn"]
    assert any("UNKNOWN-X" in w for w in r3["warnings"])

    latest = client.get("/api/sites/SAMPLE-4LEG/analysis/latest").json()
    assert latest["run_id"] == r3["run_id"]


def test_delete_tower_cascades(client, samples):
    _upload(client, samples)
    client.post("/api/sites/SAMPLE-4LEG/analysis", json={"wind_speed_ms": 30})
    assert client.delete("/api/towers/SAMPLE-4LEG").status_code == 204
    assert client.get("/api/towers").json() == []


def test_analysis_report_and_exports(client, samples):
    _upload(client, samples)
    _import_lib(client, samples)
    client.post("/api/sites/SAMPLE-4LEG/analysis", json={"wind_speed_ms": 30})

    # 1) JSON report
    rep = client.get("/api/sites/SAMPLE-4LEG/analysis/report")
    assert rep.status_code == 200
    data = rep.json()
    assert data["site_name"] == "SAMPLE-4LEG"
    assert "Member checking to TIA-222-G" in data["report_text"]

    # 2) Text report (.rpt)
    rpt = client.get("/api/sites/SAMPLE-4LEG/analysis/export/rpt")
    assert rpt.status_code == 200
    assert "attachment" in rpt.headers["content-disposition"]
    assert "SAMPLE-4LEG_MSTOWER_REPORT.rpt" in rpt.headers["content-disposition"]
    assert "SUPPORT REACTIONS" in rpt.text

    # 3) Excel workbook (.xlsx)
    xls = client.get("/api/sites/SAMPLE-4LEG/analysis/export/excel")
    assert xls.status_code == 200
    assert "spreadsheetml.sheet" in xls.headers["content-type"]
    assert "SAMPLE-4LEG_DETAIL_HITUNGAN_MSTOWER.xlsx" in xls.headers["content-disposition"]
    assert len(xls.content) > 5000


def test_sda_pdf_pua_decoder():
    from pdf_sda_extractor import decode_pua_text

    # Encode ASCII characters to PUA range (0xF020 to 0xF07E)
    ascii_sample = "MStower [V6.02.002] POROS TELUK BANO"
    pua_chars = []
    for ch in ascii_sample:
        if ch == " ":
            pua_chars.append("\uF0A0")
        else:
            pua_chars.append(chr(ord(ch) + 0xF000))
    pua_string = "".join(pua_chars)

    decoded = decode_pua_text(pua_string)
    assert decoded == ascii_sample


def test_sda_pdf_upload_and_extraction(client):
    import io
    import zipfile
    import openpyxl
    import pymupdf

    # Construct a synthetic SDA PDF document using PyMuPDF
    doc = pymupdf.open()

    # Page 1: Title and Summary metadata
    page1 = doc.new_page()
    p1_text = """
    LAPORAN AKHIR STRUKTUR SDA
    Site ID : TWR-JKT-099
    Site Name : KEBON SIRIH ROOFTOP
    Project ID : PRJ-2026-TELKOM
    Regional : REGIONAL JABODETABEK
    Tipe Tower : Greenfield 4-Leg Lattice SST
    Tinggi Menara : 42.00 m
    Kecepatan Angin Desain : 120 km/h
    Kecepatan Angin Operasional : 60 km/h

    RESUME ANALISA STRUKTUR
    Stress Ratio Maksimum : 0.885
    Status Struktur : NO NEED STRENGTHENING
    Rotasi Sway : 0.420 deg
    Rotasi Twist : 0.115 deg
    Displacement : 0.082 m
    Reaksi Tumpuan Maksimum:
    Tekan (Pu) : 245.50 kN
    Tarik (Tu) : 180.20 kN
    Geser (Vu) : 32.10 kN
    """
    page1.insert_text((50, 50), p1_text)

    # Page 2: MS-Tower Proposed .twr page with ancillaries
    page2 = doc.new_page()
    p2_text = """PT DWIRAY SUKSES MULIA
Job: TWR-JKT-099 KEBON SIRIH
Page 2 of 4  15 OCT 2026 10:30 AM
ANCILLARIES
SEC01 XA 1.20 YA 1.20 ZA 40.0 LIB SEC-1.50 ANG 0 AMASS 25.0 $ Leg A TELKOMSEL
$ RRUP01 XA -1.20 YA 1.20 ZA 38.0 LIB RRU-01 ANG 90 AMASS 15.0 $ Leg B PROPOSED
LINEAR
FEED01 XB 0.5 YB 0.5 ZB 0.0 XT 0.5 YT 0.5 ZT 40.0 LIB FEED-78 $ Feeder Run
C:\\MST\\SDA_SITE_TWR-JKT-099_PROP.twr MStower [V6.02.002]"""
    page2.insert_text((50, 50), p2_text)

    # Page 3: MS-Tower Proposed .rpt page with Member Checking
    page3 = doc.new_page()
    p3_text = """LEFTER KUCUKANDONYADIS
Job: TWR-JKT-099 KEBON SIRIH
Page 3 of 4  15 OCT 2026 10:30 AM
MEMBER CHECKING TO TIA-222-G
Pnl Members Typ Size fy nb Comp_Case Comp_Pu Curve KL/r Comp_phiPn Comp_Ratio Tens_Case Tens_Pu Tens_phiPn Tens_Ratio
  1 101-102 LEG L70X70X7 250 1 101 120.5 a 45.2 280.0 0.430 102 95.0 320.0 0.297
  2 201-202 XBR L50X50X5 250 1 101 45.2 a 125.0 75.0 0.603 102 30.0 110.0 0.273
TOTAL MASS OF TOWER = 14500 kg
ENVELOPE OF TOWER ROTATIONS
Node Elev Sway-X Sway-Y Max-Sway Twist
 100 42.0 0.350 0.420 0.420 0.115
C:\\MST\\SDA_SITE_TWR-JKT-099_PROP.rpt MStower [V6.02.002]"""
    page3.insert_text((50, 50), p3_text)

    # Page 4: Anchor Bolt & Baseplate calculation
    page4 = doc.new_page()
    p4_text = """ANCHOR BOLT AND BASE PLATE ANALYSIS
Uplift Tu : 180.20 kN
Shear Vu : 32.10 kN
Anchor Bolt Interaction Ratio : 0.680
Base Plate Thickness Existing : 25 mm
Base Plate Thickness Required : 18.5 mm
Base Plate Ratio : 0.740
STATUS : AMAN (MEMENUHI)
C:\\MST\\SDA_SITE_TWR-JKT-099_PROP.p1 MStower [V6.02.002]"""
    page4.insert_text((50, 50), p4_text)

    pdf_stream = io.BytesIO()
    doc.save(pdf_stream)
    doc.close()
    pdf_bytes = pdf_stream.getvalue()

    # 1. Test POST /api/sda/upload-pdf
    res = client.post(
        "/api/sda/upload-pdf",
        files={"file": ("SDA_REPORT_TWR_099.pdf", pdf_bytes, "application/pdf")},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert "report_id" in data
    assert data["site_metadata"]["site_id"] == "TWR-JKT-099"
    assert data["site_metadata"]["tower_height_m"] == 42.0
    assert "PROPOSED" in data["scenarios"]

    prop_sc = data["scenarios"]["PROPOSED"]
    assert len(prop_sc["devices"]["antennas"]) >= 2
    assert len(prop_sc["devices"]["linear"]) >= 1
    # Check that RRUP01 was classified as PROPOSED
    rru = next(a for a in prop_sc["devices"]["antennas"] if "RRUP" in a["id"])
    assert rru["status"] == "PROPOSED"

    # Check stress ratio & status (governed by 0.603 in .rpt member check)
    assert prop_sc["summary"]["status"] == "NO NEED STRENGTHENING"
    assert prop_sc["summary"]["stress_ratios"]["max_ratio"] == pytest.approx(0.603, abs=0.01)
    assert prop_sc["summary"]["stress_ratios"]["leg"] == pytest.approx(0.430, abs=0.01)

    report_id = data["report_id"]

    # 2. Test GET /api/sda/reports
    list_res = client.get("/api/sda/reports")
    assert list_res.status_code == 200
    assert any(r["id"] == report_id for r in list_res.json())

    # 3. Test GET /api/sda/reports/{id}
    detail_res = client.get(f"/api/sda/reports/{report_id}")
    assert detail_res.status_code == 200
    assert detail_res.json()["site_metadata"]["site_id"] == "TWR-JKT-099"

    # 4. Test GET /api/sda/{id}/download-mst-zip
    zip_res = client.get(f"/api/sda/{report_id}/download-mst-zip")
    assert zip_res.status_code == 200
    assert "application/zip" in zip_res.headers["content-type"]
    zf = zipfile.ZipFile(io.BytesIO(zip_res.content))
    names = zf.namelist()
    assert any("summary_metadata.json" in n for n in names)
    assert any("device_inventory.csv" in n for n in names)
    assert any("PROPOSED" in n and ".twr" in n for n in names)

    # 5. Test GET /api/sda/{id}/export-excel
    excel_res = client.get(f"/api/sda/{report_id}/export-excel")
    assert excel_res.status_code == 200
    assert "spreadsheetml.sheet" in excel_res.headers["content-type"]
    wb = openpyxl.load_workbook(io.BytesIO(excel_res.content))
    sheet_names = wb.sheetnames
    assert "Summary Resume SDA" in sheet_names
    assert "Device Inventory" in sheet_names


def test_unified_upload_pdf_and_export_mst(client):
    import io
    import pymupdf

    doc = pymupdf.open()
    # Page 1: .td geometry page
    p1 = doc.new_page()
    td_text = """PT DWIRAY SUKSES MULIA
Job: TWR-BALI-001 NUSA DUA
COORDINATES
     1 -1.500000E+00 -1.500000E+00  0.000000E+00 111111 0
     2  1.500000E+00 -1.500000E+00  0.000000E+00 111111 0
     3  1.500000E+00  1.500000E+00  0.000000E+00 111111 0
     4 -1.500000E+00  1.500000E+00  0.000000E+00 111111 0
     5 -1.000000E+00 -1.000000E+00  1.500000E+01 000000 0
     6  1.000000E+00 -1.000000E+00  1.500000E+01 000000 0
     7  1.000000E+00  1.000000E+00  1.500000E+01 000000 0
     8 -1.000000E+00  1.000000E+00  1.500000E+01 000000 0
MEMBERS
     1     1     5      0  1   1 0 15.016
     2     2     6      0  1   1 0 15.016
     3     3     7      0  1   1 0 15.016
     4     4     8      0  1   1 0 15.016
SECTIONS
     1  1.000000E-08  4.480000E-08  4.480000E-08  9.400000E-04 0.000000E+00 0.000000E+00 0.000000E+00 EA70X70X7
C:\\MST\\SDA_SITE_TWR-BALI-001_PROP.td MStower [V6.02.002]"""
    p1.insert_text((50, 50), td_text)

    # Page 2: .twr page
    p2 = doc.new_page()
    twr_text = """PT DWIRAY SUKSES MULIA
Job: TWR-BALI-001 NUSA DUA
PARAMETERS
TCAT 2
VB 32.10
END
ANCILLARIES
SEC01 XA 1.0 YA 1.0 ZA 15.0 LIB SEC-1.50 ANG 0 AMASS 25.0 $ Leg A TELKOMSEL
$ RRUP01 XA -1.0 YA 1.0 ZA 14.0 LIB RRU-01 ANG 90 AMASS 15.0 $ Leg B PROPOSED
C:\\MST\\SDA_SITE_TWR-BALI-001_PROP.twr MStower [V6.02.002]"""
    p2.insert_text((50, 50), twr_text)

    stream = io.BytesIO()
    doc.save(stream)
    doc.close()
    pdf_bytes = stream.getvalue()

    # 1. Upload PDF into unified /api/towers/upload endpoint
    res = client.post(
        "/api/towers/upload",
        files={"file": ("SDA_TWR-BALI-001.pdf", pdf_bytes, "application/pdf")},
    )
    assert res.status_code == 200, res.text
    t_data = res.json()
    assert "site_name" in t_data
    site = t_data["site_name"]
    assert "TWR" in site or "BALI" in site
    assert t_data["total_nodes"] == 8
    assert t_data["total_members"] == 4

    # 2. Check that OpenSees FEM analysis ran automatically upon upload
    latest = client.get(f"/api/sites/{site}/analysis/latest")
    assert latest.status_code == 200
    analysis_data = latest.json()
    assert analysis_data["max_pu_kn"] > 0
    assert len(analysis_data["reactions"]) == 4

    # 3. Check Convert / Export ke .mst endpoint
    mst_res = client.get(f"/api/sites/{site}/export/mst")
    assert mst_res.status_code == 200
    assert "DAT~" in mst_res.text
    assert "TWR~" in mst_res.text
    assert f'{site}.mst' in mst_res.headers["content-disposition"]
    assert len(mst_res.content) > 200


def test_2pole_tower_with_support_legs(client):
    """Verify parametric compilation and analysis of 2-Pole tower with out-of-plane support legs."""
    from parsers import compile_panels_to_geometry, parse_section_dimensions
    from opensees_model import run_tia222g_analysis, check_pole_member_tia222g, build_engineering_report

    # 1. Test CHS dimension parser
    d_chs = parse_section_dimensions("CHS114X6.0", 0.002, 1e-6)
    assert d_chs["d_mm"] == 114.0
    assert d_chs["t_mm"] == 6.0
    assert d_chs["ag_mm2"] > 1800.0

    # 2. Compile 4-panel 2-Pole Tower (12m total height, 2.0m spacing)
    panels = [
        {"id": 1, "ht": 3.0, "tw": 2.0, "leg_sec": 1, "brc_sec": 2},
        {"id": 2, "ht": 3.0, "tw": 2.0, "leg_sec": 1, "brc_sec": 2},
        {"id": 3, "ht": 3.0, "tw": 2.0, "leg_sec": 1, "brc_sec": 2},
        {"id": 4, "ht": 3.0, "tw": 2.0, "leg_sec": 1, "brc_sec": 2},
    ]
    sections = {
        1: {"sec_id": 1, "sec_name": "CHS114X6.0", "ag_mm2": 2035.7, "d_mm": 114.0, "t_mm": 6.0, "a_m2": 0.0020357, "iy_m4": 3.0e-6},
        2: {"sec_id": 2, "sec_name": "CHS60X3.9", "ag_mm2": 687.3, "d_mm": 60.0, "t_mm": 3.9, "a_m2": 0.0006873, "iy_m4": 2.7e-7},
    }
    nodes, members = compile_panels_to_geometry(panels, wbase=2.0, faces=2, sections=sections)

    # 10 pole nodes + 2 strut base feet + antenna mounting arms
    assert len(nodes) >= 12
    # Verify support restraints: 2 pole bases + 2 strut feet = 4 fixed supports
    fixed_supports = [nid for nid, nd in nodes.items() if nd["restraint"] == "111111"]
    assert len(fixed_supports) == 4

    # Verify members include legs, ties, X-braces, support kickers, and antenna arms
    assert len(members) >= 20
    assert any(m.get("typ") == "ARM" for m in members)
    assert any(m.get("typ") == "MOUNT" for m in members)

    # 3. Run OpenSees FEM analysis on 2-Pole structure
    devices = [{"id": "ANT01", "face": "A", "elev_z_m": 12.0, "ca_sqm": 0.8, "weight_kg": 30.0}]
    rx = run_tia222g_analysis(nodes, members, devices_list=devices, v_basic_ms=33.33)
    assert len(rx) == 4
    report = build_engineering_report(nodes, members, devices, rx, wind_speed_ms=33.33)
    assert len(report["mst_comparison"]) > 0
    assert len(report["member_3d_stress"]) > 0

    # 4. CHS Pole beam-column capacity check
    pole_chk = check_pole_member_tia222g(
        pu_kn=45.0,
        mu_knm=8.5,
        length_m=3.0,
        d_mm=114.0,
        t_mm=6.0,
        sec_name="CHS114X6.0",
    )
    assert pole_chk["phi_pn_kn"] > 100.0
    assert pole_chk["phi_mn_knm"] > 10.0
    assert pole_chk["stress_ratio"] > 0.0


def test_single_pole_with_support_legs_and_arms(client):
    """Verify parametric compilation of Single Pole (Rooftop Pole) with support kickers and antenna arms."""
    from parsers import compile_panels_to_geometry
    from opensees_model import run_tia222g_analysis, build_engineering_report

    panels = [
        {"id": 1, "ht": 3.0, "tw": 0.114, "leg_sec": 4},
        {"id": 2, "ht": 3.0, "tw": 0.114, "leg_sec": 4},
        {"id": 3, "ht": 3.0, "tw": 0.165, "leg_sec": 6},
        {"id": 4, "ht": 3.0, "tw": 0.165, "leg_sec": 6},
    ]
    sections = {
        4: {"sec_id": 4, "sec_name": "CHS114x6.0", "ag_mm2": 2035.7, "d_mm": 114.0, "t_mm": 6.0},
        6: {"sec_id": 6, "sec_name": "CHS165X7.1", "ag_mm2": 3522.6, "d_mm": 165.0, "t_mm": 7.1},
        2: {"sec_id": 2, "sec_name": "CHS60X3.9", "ag_mm2": 687.3, "d_mm": 60.0, "t_mm": 3.9},
    }
    support_coords = [
        {"x": 0.0, "y": 0.0, "z": 16.0, "restraint": "111111"},
        {"x": -2.5, "y": 0.0, "z": 16.0, "restraint": "111111"},
        {"x": 0.0, "y": 2.5, "z": 16.0, "restraint": "111111"},
    ]

    nodes, members = compile_panels_to_geometry(
        panels,
        wbase=0.165,
        faces=1,
        sections=sections,
        support_coords=support_coords,
    )

    # 5 pole levels + 2 kicker foot nodes + antenna arms & mount pipes
    assert len(nodes) >= 7
    # 4 pole segments + support kickers + tri-sector mounting arms & skur arms
    assert len(members) >= 8
    assert any(m.get("typ") == "ARM" for m in members)
    assert any(m.get("typ") == "MOUNT" for m in members)
    assert any(m.get("typ") == "STRUT_ARM" for m in members)

    # Run OpenSees analysis
    rx = run_tia222g_analysis(nodes, members, devices_list=[], v_basic_ms=33.33)
    assert len(rx) == 3
    report = build_engineering_report(nodes, members, [], rx, wind_speed_ms=33.33)
    assert len(report["mst_comparison"]) > 0
    assert len(report["member_3d_stress"]) >= 8


def test_tombol_b_opensees_controller_and_dynamic_excel_formulas(client):
    """Verify Tombol B (/analysis/opensees) & openpyxl dynamic TIA-222-G buckling formulas + Load Combinations sheet."""
    import io
    import openpyxl

    mst_content = b"""DAT~
COORDINATES
     1 -1.500000E+00 -1.500000E+00  0.000000E+00 111111 0
     2  1.500000E+00 -1.500000E+00  0.000000E+00 111111 0
     3  1.500000E+00  1.500000E+00  0.000000E+00 111111 0
     4 -1.500000E+00  1.500000E+00  0.000000E+00 111111 0
     5 -1.000000E+00 -1.000000E+00  1.000000E+01 000000 0
     6  1.000000E+00 -1.000000E+00  1.000000E+01 000000 0
     7  1.000000E+00  1.000000E+00  1.000000E+01 000000 0
     8 -1.000000E+00  1.000000E+00  1.000000E+01 000000 0
MEMBERS
     1     1     5      0  1   1 0 10.025
     2     2     6      0  1   1 0 10.025
     3     3     7      0  1   1 0 10.025
     4     4     8      0  1   1 0 10.025
     5     1     6      0  2   1 0 10.308
     6     2     7      0  2   1 0 10.308
     7     3     8      0  2   1 0 10.308
     8     4     5      0  2   1 0 10.308
SECTIONS
     1  1.000000E-08  4.480000E-08  4.480000E-08  9.400000E-04 0.000000E+00 0.000000E+00 0.000000E+00 EA70X70X7
     2  1.000000E-08  1.100000E-08  1.100000E-08  4.800000E-04 0.000000E+00 0.000000E+00 0.000000E+00 EA50X50X5
"""
    up = client.post(
        "/api/towers/upload",
        files={"file": ("SITE_TOMBOL_B.mst", mst_content, "text/plain")},
    )
    assert up.status_code in (200, 201), up.text
    site = up.json()["site_name"]

    # Execute Tombol B: Standalone OpenSeesPy Analysis
    res_b = client.post(
        f"/api/sites/{site}/analysis/opensees",
        json={"wind_speed_ms": 33.33, "exposure": "C", "struct_class": 2, "kzt": 1.0},
    )
    assert res_b.status_code == 200, res_b.text
    payload_b = res_b.json()
    assert payload_b["analysis_mode"] == "pure_opensees"
    eng = payload_b["engineering"]
    assert len(eng["load_combinations"]) >= 40
    assert any(c["case_id"] == 500 for c in eng["load_combinations"])
    assert any(c["case_id"] == 1000 for c in eng["load_combinations"])
    assert any(c["case_id"] == 2000 for c in eng["load_combinations"])
    assert any(c["case_id"] == 3020 for c in eng["load_combinations"])

    # Download Excel workbook from Tombol B export endpoint
    xl_res = client.get(f"/api/sites/{site}/analysis/export/opensees-excel")
    assert xl_res.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(xl_res.content), data_only=False)

    assert "Load Combinations" in wb.sheetnames
    assert "Member Check" in wb.sheetnames
    assert "Support Reactions" in wb.sheetnames
    assert "Tower Rotations" in wb.sheetnames

    ws_mc = wb["Member Check"]
    # Row 5 contains live TIA-222-G buckling & VLOOKUP formulas
    assert "VLOOKUP" in str(ws_mc["F5"].value)
    assert str(ws_mc["O5"].value).startswith("=M5/L5")
    assert str(ws_mc["P5"].value).startswith("=IF(O5<=120")
    assert str(ws_mc["R5"].value).startswith("=(PI()^2*H5)/(P5^2)")
    assert str(ws_mc["S5"].value).startswith("=IF(P5<=4.71*SQRT")
    assert str(ws_mc["U5"].value).startswith("=0.90*T5")
    assert str(ws_mc["W5"].value).startswith("=ABS(V5)/U5")
    assert str(ws_mc["X5"].value).startswith('=IF(W5<=1, "OK", "OVER")')
    assert str(ws_mc["AC5"].value).startswith("=W5-AB5")
    assert str(ws_mc["AD5"].value).startswith("=U5/MAX(AA5,0.001)")

    ws_sr = wb["Support Reactions"]
    assert str(ws_sr["L5"].value).startswith("=SQRT(D5^2+E5^2)")

    ws_rot = wb["Tower Rotations"]
    assert str(ws_rot["K5"].value).startswith('=IF(I5<=J5, "OK", "OVER")')

