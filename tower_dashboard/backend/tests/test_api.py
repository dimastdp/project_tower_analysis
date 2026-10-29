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
    assert res["version"] == "2.2.0"
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
    assert r.json()["detail"] == "Only .mst files are accepted."


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

    assert client.get("/api/sites/SAMPLE-4LEG/analysis/latest").status_code == 404

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
