"""HTTP, validation, orchestration and persistence. No FEM math lives here."""
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from db import connect, init_db
from parsers import (
    _extract_prefix_and_dim,
    compute_device_dimensions,
    compute_tia_ca,
    export_devices_as_lib,
    infer_device_placement,
    is_structural,
    parse_ancillary_lib,
    parse_mst_content,
    parse_mst_embedded_results,
    parse_mst_twr_block,
    suggest_similar_devices,
    summarize_geometry,
    upsert_device_in_lib_file,
)

MAX_MST_BYTES = 50 * 1024 * 1024
MAX_LIB_BYTES = 5 * 1024 * 1024
FEM_LOCK = threading.Lock()  # OpenSeesPy keeps global state
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LIB_PATH = WORKSPACE_ROOT / "MTEL.lib"
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def _upsert_catalog_devices(c, records: list[dict]) -> None:
    if not records:
        return
    c.executemany(
        """INSERT INTO catalog_devices
             (category, device_name, shape_type, dim_m, mass_kg, af_m2, asf_m2, ca_factor, epa_m2, remark)
           VALUES (:category, :device_name, :shape_type, :dim_m, :mass_kg, :af_m2, :asf_m2,
                   :ca_factor, :epa_m2, :remark)
           ON CONFLICT(device_name) DO UPDATE SET
             category=excluded.category, shape_type=excluded.shape_type, dim_m=excluded.dim_m,
             mass_kg=excluded.mass_kg, af_m2=excluded.af_m2, asf_m2=excluded.asf_m2,
             ca_factor=excluded.ca_factor, epa_m2=excluded.epa_m2, remark=excluded.remark""",
        records,
    )


def _store_parsed_tower(c, site: str, raw: bytes) -> dict:
    nodes, members = parse_mst_content(raw)
    if not nodes:
        raise ValueError("No nodes were found in the DAT~ block.")
    geo = summarize_geometry(nodes)
    twr_info = parse_mst_twr_block(raw)

    c.execute(
        """INSERT INTO towers
             (site_name, height_m, top_width_m, bot_width_m, total_nodes, total_members, raw_mst_data)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(site_name) DO UPDATE SET
             height_m=excluded.height_m, top_width_m=excluded.top_width_m,
             bot_width_m=excluded.bot_width_m, total_nodes=excluded.total_nodes,
             total_members=excluded.total_members, raw_mst_data=excluded.raw_mst_data,
             updated_at=CURRENT_TIMESTAMP""",
        (site, geo["height_m"], geo["top_width_m"], geo["bot_width_m"],
         len(nodes), len(members), raw),
    )
    tid = c.execute("SELECT tower_id FROM towers WHERE site_name = ?", (site,)).fetchone()[0]
    c.execute("DELETE FROM tower_nodes WHERE tower_id = ?", (tid,))
    c.execute("DELETE FROM tower_members WHERE tower_id = ?", (tid,))
    c.executemany(
        "INSERT INTO tower_nodes (tower_id, seq_id, label, x, y, z, restraint, flag) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(tid, sid, n["label"], n["x"], n["y"], n["z"], n["restraint"], n["flag"])
         for sid, n in nodes.items()],
    )
    c.executemany(
        "INSERT INTO tower_members (tower_id, member_id, ni, nj, sec_id, length) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [(tid, m["id"], m["ni"], m["nj"], m["sec_id"], m["length"]) for m in members],
    )

    if twr_info["inline_devices"]:
        _upsert_catalog_devices(c, twr_info["inline_devices"])

    existing_dev_count = c.execute(
        "SELECT COUNT(*) FROM site_devices WHERE tower_id = ?", (tid,)
    ).fetchone()[0]
    has_leg_coords = c.execute(
        "SELECT COUNT(*) FROM site_devices WHERE tower_id = ? AND mounting_name LIKE 'LEG %[%'", (tid,)
    ).fetchone()[0]
    if (existing_dev_count == 0 or (has_leg_coords == 0 and twr_info["ancillaries"])) and twr_info["ancillaries"]:
        c.execute("DELETE FROM site_devices WHERE tower_id = ?", (tid,))
        c.executemany(
            "INSERT INTO site_devices (tower_id, status, tenant, device_name, mounting_name, elev_z_m, qty) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (tid, a["status"], a["tenant"], a["device_name"], a["mounting_name"], a["elev_z_m"], a["qty"])
                for a in twr_info["ancillaries"]
            ],
        )
    return _tower_public(_tower_row(c, site))


def _bootstrap_workspace_data() -> None:
    """Seed MTEL.lib and repair any previously uploaded .mst models when running outside test fixtures."""
    if os.environ.get("TOWER_DB_PATH"):
        return
    with connect() as c:
        if DEFAULT_LIB_PATH.exists():
            count = c.execute("SELECT COUNT(*) FROM catalog_devices").fetchone()[0]
            if count < 50:
                df = parse_ancillary_lib(DEFAULT_LIB_PATH.read_text(encoding="latin1"))
                if not df.empty:
                    _upsert_catalog_devices(c, df.to_dict("records"))

        rows = c.execute("SELECT site_name, raw_mst_data FROM towers WHERE raw_mst_data IS NOT NULL").fetchall()
        for r in rows:
            try:
                _store_parsed_tower(c, r["site_name"], r["raw_mst_data"])
            except Exception:
                pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    _bootstrap_workspace_data()
    yield


__version__ = "2.0.0"

app = FastAPI(title="Tower Dashboard API", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- helpers ----------------------------------------------------------
def _tower_row(conn, site: str):
    row = conn.execute("SELECT * FROM towers WHERE site_name = ?", (site,)).fetchone()
    if row is None:
        raise HTTPException(404, "Site not found.")
    return row


def _tower_public(row) -> dict:
    keys = ("site_name", "height_m", "top_width_m", "bot_width_m", "total_nodes", "total_members")
    return {k: row[k] for k in keys}


# ---------- schemas ----------------------------------------------------------
class LibraryDeviceIn(BaseModel):
    category: str = Field(default="CUSTOM", min_length=1, max_length=60)
    device_name: str = Field(min_length=1, max_length=80)
    shape_type: str = Field(default="BOX", min_length=1, max_length=20)
    dim_m: float = Field(gt=0, le=50)
    mass_kg: float = Field(ge=0, le=5000)
    af_m2: float = Field(ge=0, le=100)
    asf_m2: float = Field(ge=0, le=100)
    ca_factor: Optional[float] = Field(default=None, gt=0, le=5)
    remark: Optional[str] = Field(default="", max_length=160)


class SiteDeviceIn(BaseModel):
    status: Literal["EXISTING", "PROPOSED"]
    tenant: str = Field(min_length=1, max_length=60)
    device_name: str = Field(min_length=1, max_length=80)
    mounting_name: Optional[str] = Field(default=None, max_length=80)
    elev_z_m: float = Field(ge=0, le=500)
    qty: int = Field(ge=1, le=999)


class AnalysisIn(BaseModel):
    wind_speed_ms: float = Field(default=33.33, gt=0, le=100)
    exposure: Literal["B", "C", "D"] = "C"
    struct_class: Literal[1, 2, 3] = 2
    kzt: float = Field(default=1.0, gt=0, le=3.0)


# ---------- health & version --------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/version")
def get_version():
    return {
        "version": __version__,
        "app_name": "Tower Dashboard",
        "standard": "TIA-222-G & MS Tower V6 Calibration",
    }


# ---------- towers -----------------------------------------------------------
@app.get("/api/towers")
def list_towers():
    with connect() as c:
        rows = c.execute("SELECT * FROM towers ORDER BY site_name").fetchall()
        return [_tower_public(r) for r in rows]


@app.post("/api/towers/upload")
async def upload_tower(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".mst"):
        raise HTTPException(400, "Only .mst files are accepted.")
    raw = await file.read()
    if len(raw) > MAX_MST_BYTES:
        raise HTTPException(413, "File is larger than 50 MB.")
    site = Path(file.filename).stem.upper()
    with connect() as c:
        try:
            return _store_parsed_tower(c, site, raw)
        except ValueError as exc:
            raise HTTPException(422, str(exc))


@app.get("/api/towers/{site}")
def get_tower(site: str):
    with connect() as c:
        return _tower_public(_tower_row(c, site))


@app.get("/api/towers/{site}/geometry")
def get_geometry(site: str):
    with connect() as c:
        tid = _tower_row(c, site)["tower_id"]
        node_rows = c.execute(
            "SELECT seq_id, label, x, y, z, restraint, flag FROM tower_nodes WHERE tower_id = ?",
            (tid,),
        ).fetchall()
        member_rows = c.execute(
            "SELECT ni, nj FROM tower_members WHERE tower_id = ?", (tid,)
        ).fetchall()

    by_seq = {r["seq_id"]: dict(r) for r in node_rows if is_structural(dict(r))}
    nodes = [
        {"id": sid, "x": n["x"], "y": n["y"], "z": n["z"], "support": n["restraint"] == "111111"}
        for sid, n in by_seq.items()
    ]
    segments = []
    for m in member_rows:
        a, b = by_seq.get(m["ni"]), by_seq.get(m["nj"])
        if a and b:
            segments.append([a["x"], a["y"], a["z"], b["x"], b["y"], b["z"]])
    return {"nodes": nodes, "segments": segments}


@app.delete("/api/towers/{site}", status_code=204)
def delete_tower(site: str):
    with connect() as c:
        tid = _tower_row(c, site)["tower_id"]
        c.execute("DELETE FROM towers WHERE tower_id = ?", (tid,))


# ---------- library (.lib) ---------------------------------------------------
@app.post("/api/library/devices/import")
async def import_library(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith((".lib", ".txt")):
        raise HTTPException(400, "Only .lib or .txt files are accepted.")
    raw = await file.read()
    if len(raw) > MAX_LIB_BYTES:
        raise HTTPException(413, "File is larger than 5 MB.")
    df = parse_ancillary_lib(raw.decode("latin1"))
    if df.empty:
        raise HTTPException(422, "No valid device rows were found.")
    with connect() as c:
        _upsert_catalog_devices(c, df.to_dict("records"))
    return {"imported": int(len(df))}


@app.post("/api/library/devices/sync-mtel")
def sync_mtel_library():
    if not DEFAULT_LIB_PATH.exists():
        raise HTTPException(404, "MTEL.lib not found in workspace root.")
    df = parse_ancillary_lib(DEFAULT_LIB_PATH.read_text(encoding="latin1"))
    if df.empty:
        raise HTTPException(422, "No valid device rows found in MTEL.lib.")
    with connect() as c:
        _upsert_catalog_devices(c, df.to_dict("records"))
    return {"imported": int(len(df)), "source": DEFAULT_LIB_PATH.name}


@app.get("/api/library/devices")
def list_devices(q: str = ""):
    like = f"%{q.strip()}%"
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM catalog_devices WHERE device_name LIKE ? OR category LIKE ? OR remark LIKE ? "
            "ORDER BY category, device_name LIMIT 1000",
            (like, like, like),
        ).fetchall()
        return [dict(r) for r in rows]


@app.post("/api/library/devices", status_code=201)
def upsert_library_device(body: LibraryDeviceIn):
    shape = body.shape_type.strip().upper()
    ca = body.ca_factor if body.ca_factor is not None else compute_tia_ca(shape, body.dim_m, body.af_m2)
    epa = round(body.af_m2 * ca, 4)
    rec = {
        "category": body.category.strip().upper(),
        "device_name": body.device_name.strip(),
        "shape_type": shape,
        "dim_m": body.dim_m,
        "mass_kg": body.mass_kg,
        "af_m2": body.af_m2,
        "asf_m2": body.asf_m2,
        "ca_factor": round(ca, 3),
        "epa_m2": epa,
        "remark": (body.remark or "").strip(),
    }
    with connect() as c:
        _upsert_catalog_devices(c, [rec])
        row = c.execute(
            "SELECT * FROM catalog_devices WHERE device_name = ?", (rec["device_name"],)
        ).fetchone()

    # Write back to MTEL.lib when running outside unit tests
    if not os.environ.get("TOWER_DB_PATH"):
        try:
            upsert_device_in_lib_file(DEFAULT_LIB_PATH, rec)
        except Exception:
            pass
    return dict(row)


@app.delete("/api/library/devices/{device_name}", status_code=204)
def delete_library_device(device_name: str):
    with connect() as c:
        c.execute("DELETE FROM catalog_devices WHERE device_name = ?", (device_name,))


@app.get("/api/library/devices/export")
def export_library():
    with connect() as c:
        rows = c.execute("SELECT * FROM catalog_devices ORDER BY category, device_name").fetchall()
        devices = [dict(r) for r in rows]
    text = export_devices_as_lib(
        devices,
        source_lib_path=DEFAULT_LIB_PATH if DEFAULT_LIB_PATH.exists() else None,
    )
    return Response(
        content=text.encode("latin1", errors="replace"),
        media_type="text/plain; charset=latin1",
        headers={"Content-Disposition": 'attachment; filename="MTEL.lib"'},
    )


class ApplySuggestionIn(BaseModel):
    target_device_name: str = Field(min_length=1, max_length=80)
    mode: Literal["replace", "clone_to_lib"] = "clone_to_lib"


# ---------- site inventory ---------------------------------------------------
@app.get("/api/sites/{site}/devices")
def list_site_devices(site: str):
    with connect() as c:
        t_row = _tower_row(c, site)
        tid = t_row["tower_id"]
        height_m = float(t_row["height_m"] or 25.0)
        top_w = float(t_row["top_width_m"] or 1.2)
        bot_w = float(t_row["bot_width_m"] or 2.7)
        rows = c.execute(
            """SELECT s.id, s.status, s.tenant, s.device_name, s.mounting_name, s.elev_z_m, s.qty,
                      d.device_id IS NOT NULL AS in_library, d.epa_m2, d.mass_kg,
                      d.shape_type, d.dim_m, d.af_m2, d.asf_m2
               FROM site_devices s
               LEFT JOIN catalog_devices d ON d.device_name = s.device_name
               WHERE s.tower_id = ? ORDER BY s.elev_z_m DESC, s.id""",
            (tid,),
        ).fetchall()

        all_cat = [
            dict(r)
            for r in c.execute(
                "SELECT category, device_name, shape_type, dim_m, mass_kg, af_m2, asf_m2, epa_m2 FROM catalog_devices"
            ).fetchall()
        ]

        out = []
        suggestion_cache: dict[str, list[dict]] = {}
        for idx, r in enumerate(rows):
            d = dict(r)
            in_lib = bool(d["in_library"])
            dims = compute_device_dimensions(d if in_lib else None, d["device_name"])
            place = infer_device_placement(d["mounting_name"], float(d["elev_z_m"]), height_m, top_w, bot_w, idx)
            suggestions: list[dict] = []
            if not in_lib:
                dev_name = d["device_name"]
                if dev_name not in suggestion_cache:
                    suggestion_cache[dev_name] = suggest_similar_devices(dev_name, all_cat, top_k=3)
                suggestions = suggestion_cache[dev_name]
            out.append(
                {
                    "id": d["id"],
                    "status": d["status"],
                    "tenant": d["tenant"],
                    "device_name": d["device_name"],
                    "mounting_name": d["mounting_name"],
                    "elev_z_m": d["elev_z_m"],
                    "qty": d["qty"],
                    "in_library": in_lib,
                    "epa_m2": d["epa_m2"],
                    "mass_kg": d["mass_kg"],
                    **dims,
                    **place,
                    "suggestions": suggestions,
                }
            )
        return out


@app.post("/api/sites/{site}/devices/{device_id}/apply-suggestion")
def apply_device_suggestion(site: str, device_id: int, body: ApplySuggestionIn):
    with connect() as c:
        tid = _tower_row(c, site)["tower_id"]
        site_row = c.execute(
            "SELECT * FROM site_devices WHERE id = ? AND tower_id = ?", (device_id, tid)
        ).fetchone()
        if site_row is None:
            raise HTTPException(404, "Site device row not found.")

        cand = c.execute(
            "SELECT * FROM catalog_devices WHERE device_name = ?", (body.target_device_name.strip(),)
        ).fetchone()
        if cand is None:
            raise HTTPException(404, "Suggested library device not found.")

        missing_name = site_row["device_name"]
        if body.mode == "replace":
            c.execute(
                "UPDATE site_devices SET device_name = ? WHERE tower_id = ? AND device_name = ?",
                (cand["device_name"], tid, missing_name),
            )
            return {"mode": "replace", "old_name": missing_name, "new_name": cand["device_name"]}

        # mode == "clone_to_lib": register missing_name in catalog_devices & MTEL.lib scaled to its dimension suffix
        _pre, num = _extract_prefix_and_dim(missing_name)
        cand_dim = float(cand["dim_m"] or 0.5)
        target_dim = num if (num and 0.1 <= num <= 6.0) else cand_dim
        scale = (target_dim / cand_dim) if cand_dim > 0 else 1.0
        af = round(float(cand["af_m2"] or 0.2) * scale, 4)
        asf = round(float(cand["asf_m2"] or 0.1) * scale, 4)
        ca = float(cand["ca_factor"] or compute_tia_ca(cand["shape_type"], target_dim, af))
        rec = {
            "category": cand["category"] or "SUGGESTED",
            "device_name": missing_name,
            "shape_type": cand["shape_type"] or "BOX",
            "dim_m": round(target_dim, 3),
            "mass_kg": round(float(cand["mass_kg"] or 15.0) * scale, 1),
            "af_m2": af,
            "asf_m2": asf,
            "ca_factor": round(ca, 3),
            "epa_m2": round(af * ca, 4),
            "remark": f"Auto-registered from similar .lib device {cand['device_name']}",
        }
        _upsert_catalog_devices(c, [rec])
        if not os.environ.get("TOWER_DB_PATH"):
            try:
                upsert_device_in_lib_file(DEFAULT_LIB_PATH, rec)
            except Exception:
                pass
        return {"mode": "clone_to_lib", "device_name": missing_name, "based_on": cand["device_name"]}


@app.post("/api/sites/{site}/devices", status_code=201)
def add_site_device(site: str, body: SiteDeviceIn):
    with connect() as c:
        tid = _tower_row(c, site)["tower_id"]
        cur = c.execute(
            "INSERT INTO site_devices (tower_id, status, tenant, device_name, mounting_name, elev_z_m, qty) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (tid, body.status, body.tenant.strip(), body.device_name.strip(),
             (body.mounting_name or "").strip() or None, body.elev_z_m, body.qty),
        )
        return {"id": cur.lastrowid}


@app.delete("/api/sites/{site}/devices/{device_id}", status_code=204)
def delete_site_device(site: str, device_id: int):
    with connect() as c:
        tid = _tower_row(c, site)["tower_id"]
        c.execute("DELETE FROM site_devices WHERE id = ? AND tower_id = ?", (device_id, tid))


# ---------- analysis ---------------------------------------------------------
def _load_tower_inputs(c, tid: int, raw_mst_data: bytes | None):
    node_rows = c.execute(
        "SELECT seq_id, label, x, y, z, restraint, flag FROM tower_nodes WHERE tower_id = ?", (tid,)
    ).fetchall()
    member_rows = c.execute(
        "SELECT member_id, ni, nj, sec_id, length FROM tower_members WHERE tower_id = ?", (tid,)
    ).fetchall()
    dev_rows = c.execute(
        """SELECT s.status, s.tenant, s.device_name, s.elev_z_m, s.qty, d.epa_m2, d.mass_kg
           FROM site_devices s LEFT JOIN catalog_devices d ON d.device_name = s.device_name
           WHERE s.tower_id = ?""",
        (tid,),
    ).fetchall()

    nodes = {r["seq_id"]: {k: r[k] for k in ("label", "x", "y", "z", "restraint", "flag")} for r in node_rows}
    members = [{"id": r["member_id"], "ni": r["ni"], "nj": r["nj"],
                "sec_id": r["sec_id"], "length": r["length"]} for r in member_rows]

    # Attach real section properties if raw_mst_data has a section table
    if raw_mst_data:
        try:
            _n, parsed_members = parse_mst_content(raw_mst_data)
            sec_by_id = {m["sec_id"]: m for m in parsed_members if "sec_name" in m}
            for m in members:
                s = sec_by_id.get(m["sec_id"])
                if s:
                    for k in ("sec_name", "a_m2", "iy_m4", "iz_m4", "j_m4"):
                        if k in s:
                            m[k] = s[k]
        except Exception:
            pass

    devices = [dict(r) for r in dev_rows]
    return nodes, members, devices


def _load_run(
    c,
    run_row,
    site: str,
    tower_row=None,
    exposure: str | None = None,
    struct_class: int = 2,
    kzt: float = 1.0,
) -> dict:
    from opensees_model import build_engineering_report

    reactions_rows = c.execute(
        "SELECT node_label, pu_kn, tu_kn, vu_kn FROM analysis_reactions WHERE run_id = ? ORDER BY node_label",
        (run_row["run_id"],),
    ).fetchall()
    reactions = [dict(r) for r in reactions_rows]

    t_row = tower_row or _tower_row(c, site)
    raw_mst = t_row["raw_mst_data"]
    nodes, members, devices = _load_tower_inputs(c, t_row["tower_id"], raw_mst)
    emb = parse_mst_embedded_results(raw_mst) if raw_mst else {"z_base_m": 0.0, "rpt_by_member": {}}
    twr_meta = parse_mst_twr_block(raw_mst) if raw_mst else {"vb_ms": 32.10, "exposure": "C"}
    ref_vb = twr_meta.get("vb_ms") or 32.10
    ref_exp = twr_meta.get("exposure") or "B"
    eff_exposure = exposure or ref_exp

    engineering = build_engineering_report(
        nodes=nodes,
        members=members,
        devices=devices,
        reactions=reactions,
        wind_speed_ms=run_row["wind_speed_ms"],
        exposure=eff_exposure,
        struct_class=struct_class,
        kzt=kzt,
        z_base_m=emb["z_base_m"],
        rpt_by_member=emb["rpt_by_member"],
        mst_embedded=emb,
        ref_vb_ms=ref_vb,
        ref_exposure=ref_exp,
    )
    return {
        "run_id": run_row["run_id"],
        "site_name": site,
        "wind_speed_ms": run_row["wind_speed_ms"],
        "created_at": run_row["created_at"],
        "max_pu_kn": run_row["max_pu_kn"],
        "max_tu_kn": run_row["max_tu_kn"],
        "max_vu_kn": run_row["max_vu_kn"],
        "reactions": reactions,
        "warnings": [],
        "engineering": engineering,
    }


@app.get("/api/sites/{site}/preflight")
def preflight_analysis(site: str):
    """Inspect .mst and site_devices for any missing .lib references (devices, linear ancillaries, sections) before analysis."""
    with connect() as c:
        t_row = _tower_row(c, site)
        tid = t_row["tower_id"]
        raw_mst = t_row["raw_mst_data"]
        nodes, members, _devs = _load_tower_inputs(c, tid, raw_mst)
        site_devs = list_site_devices(site)

        missing_devices = [
            {
                "id": d["id"],
                "kind": "DEVICE",
                "name": d["device_name"],
                "tenant": d["tenant"],
                "status": d["status"],
                "elev_z_m": d["elev_z_m"],
                "qty": d["qty"],
                "suggestions": d.get("suggestions") or [],
            }
            for d in site_devs
            if not d["in_library"]
        ]

        twr_info = parse_mst_twr_block(raw_mst) if raw_mst else {"vb_ms": 33.33, "exposure": "C", "linear_ancillaries": []}
        emb = parse_mst_embedded_results(raw_mst) if raw_mst else {"z_base_m": 0.0}

        cat_names = {
            r["device_name"].upper()
            for r in c.execute("SELECT device_name FROM catalog_devices").fetchall()
        }
        missing_linear = []
        for la in twr_info.get("linear_ancillaries", []):
            lname = la["lib_name"]
            if not la.get("in_inline_lib") and lname.upper() not in cat_names:
                missing_linear.append(
                    {
                        "kind": "LINEAR",
                        "tag": la["tag"],
                        "name": lname,
                        "zb_m": la.get("zb_m", 0.0),
                        "zt_m": la.get("zt_m", 25.0),
                        "qty": la.get("qty", 1),
                        "suggested_lib": "CB-TRAY-40" if "F" in lname.upper() else "TANGGA-40",
                        "note": "Referensi linear feeder tidak ada di MTEL.lib; diestimasi via beban linear terkalibrasi (12.93 kN)",
                    }
                )

        missing_sections = []
        seen_sec = set()
        for m in members:
            sname = m.get("sec_name")
            if not sname and m["sec_id"] not in seen_sec:
                seen_sec.add(m["sec_id"])
                missing_sections.append(
                    {
                        "kind": "MEMBER_SECTION",
                        "sec_id": m["sec_id"],
                        "name": f"SEC-{m['sec_id']}",
                        "suggested_lib": "EA70X70X7",
                    }
                )

        return {
            "site_name": site,
            "default_vb_ms": twr_info.get("vb_ms") or 32.10,
            "default_exposure": twr_info.get("exposure") or "B",
            "z_base_m": emb.get("z_base_m") or 0.0,
            "has_missing_references": bool(missing_devices or missing_linear or missing_sections),
            "missing_devices": missing_devices,
            "missing_linear": missing_linear,
            "missing_sections": missing_sections,
        }


@app.post("/api/sites/{site}/analysis")
def run_analysis(site: str, body: AnalysisIn):
    from opensees_model import run_tia222g_analysis

    with connect() as c:
        t_row = _tower_row(c, site)
        tid = t_row["tower_id"]
        raw_mst = t_row["raw_mst_data"]
        nodes, members, devices = _load_tower_inputs(c, tid, raw_mst)

    if not nodes:
        raise HTTPException(409, "Tower has no structural nodes.")

    emb = parse_mst_embedded_results(raw_mst) if raw_mst else {"z_base_m": 0.0, "rpt_by_member": {}}
    twr_meta = parse_mst_twr_block(raw_mst) if raw_mst else {"vb_ms": 32.10, "exposure": "B"}
    ref_vb = twr_meta.get("vb_ms") or 32.10
    ref_exp = twr_meta.get("exposure") or "B"
    warnings = sorted({f"Device '{d['device_name']}' not found in library; EPA treated as 0."
                       for d in devices if d["epa_m2"] is None})

    try:
        with FEM_LOCK:
            reactions = run_tia222g_analysis(
                nodes,
                members,
                devices,
                body.wind_speed_ms,
                exposure=body.exposure,
                struct_class=body.struct_class,
                kzt=body.kzt,
                z_base_m=emb["z_base_m"],
                mst_embedded=emb,
                ref_vb_ms=ref_vb,
                ref_exposure=ref_exp,
            )
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except RuntimeError as exc:
        raise HTTPException(500, str(exc))

    max_pu = max(r["pu_kn"] for r in reactions)
    max_tu = max(r["tu_kn"] for r in reactions)
    max_vu = max(r["vu_kn"] for r in reactions)

    with connect() as c:
        cur = c.execute(
            "INSERT INTO analysis_runs (tower_id, wind_speed_ms, max_pu_kn, max_tu_kn, max_vu_kn) "
            "VALUES (?, ?, ?, ?, ?)",
            (tid, body.wind_speed_ms, max_pu, max_tu, max_vu),
        )
        run_id = cur.lastrowid
        c.executemany(
            "INSERT INTO analysis_reactions (run_id, node_label, pu_kn, tu_kn, vu_kn) VALUES (?, ?, ?, ?, ?)",
            [(run_id, r["node_label"], r["pu_kn"], r["tu_kn"], r["vu_kn"]) for r in reactions],
        )
        run_row = c.execute("SELECT * FROM analysis_runs WHERE run_id = ?", (run_id,)).fetchone()
        result = _load_run(
            c,
            run_row,
            site,
            tower_row=t_row,
            exposure=body.exposure,
            struct_class=body.struct_class,
            kzt=body.kzt,
        )
    result["warnings"] = warnings
    return result


@app.get("/api/sites/{site}/analysis/latest")
def latest_analysis(site: str):
    with connect() as c:
        t_row = _tower_row(c, site)
        tid = t_row["tower_id"]
        row = c.execute(
            "SELECT * FROM analysis_runs WHERE tower_id = ? ORDER BY run_id DESC LIMIT 1", (tid,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "No analysis has been run for this site.")
        return _load_run(c, row, site, tower_row=t_row)


# ---------- production: serve the built SPA (TRD 2.11) -------------------------
if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404, "Not found.")
        target = FRONTEND_DIST / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(FRONTEND_DIST / "index.html")
