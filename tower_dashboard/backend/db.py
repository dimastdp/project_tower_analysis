import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

# Override with TOWER_DB_PATH (used by tests); default sits next to this file.
DB_PATH = os.environ.get("TOWER_DB_PATH", str(Path(__file__).with_name("tower_catalog.db")))

SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog_devices (
    device_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    category    TEXT,
    device_name TEXT NOT NULL UNIQUE,
    shape_type  TEXT,
    dim_m       REAL,
    mass_kg     REAL,
    af_m2       REAL,
    asf_m2      REAL,
    ca_factor   REAL,
    epa_m2      REAL,
    remark      TEXT
);

CREATE TABLE IF NOT EXISTS catalog_sections (
    section_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    section_name TEXT NOT NULL UNIQUE,
    ag_mm2 REAL, ix_mm4 REAL, iy_mm4 REAL,
    rx_mm  REAL, ry_mm  REAL, j_mm4 REAL,
    b_mm   REAL, t_mm   REAL
);

CREATE TABLE IF NOT EXISTS towers (
    tower_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    site_name     TEXT NOT NULL UNIQUE,
    height_m      REAL,
    top_width_m   REAL,
    bot_width_m   REAL,
    total_nodes   INTEGER,
    total_members INTEGER,
    raw_mst_data  BLOB,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tower_nodes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tower_id  INTEGER NOT NULL REFERENCES towers(tower_id) ON DELETE CASCADE,
    seq_id    INTEGER NOT NULL,
    label     INTEGER,
    x REAL, y REAL, z REAL,
    restraint TEXT,
    flag      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_nodes_tower ON tower_nodes(tower_id);

CREATE TABLE IF NOT EXISTS tower_members (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tower_id  INTEGER NOT NULL REFERENCES towers(tower_id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL,
    ni INTEGER NOT NULL,
    nj INTEGER NOT NULL,
    sec_id INTEGER,
    length REAL
);
CREATE INDEX IF NOT EXISTS idx_members_tower ON tower_members(tower_id);

CREATE TABLE IF NOT EXISTS site_devices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tower_id      INTEGER NOT NULL REFERENCES towers(tower_id) ON DELETE CASCADE,
    status        TEXT NOT NULL CHECK (status IN ('EXISTING','PROPOSED')),
    tenant        TEXT NOT NULL,
    device_name   TEXT NOT NULL,
    mounting_name TEXT,
    elev_z_m      REAL NOT NULL,
    qty           INTEGER NOT NULL CHECK (qty >= 1)
);
CREATE INDEX IF NOT EXISTS idx_site_devices_tower ON site_devices(tower_id);

CREATE TABLE IF NOT EXISTS analysis_runs (
    run_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tower_id      INTEGER NOT NULL REFERENCES towers(tower_id) ON DELETE CASCADE,
    wind_speed_ms REAL NOT NULL,
    max_pu_kn     REAL,
    max_tu_kn     REAL,
    max_vu_kn     REAL,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
    elem_axial_json TEXT
);

CREATE TABLE IF NOT EXISTS analysis_reactions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER NOT NULL REFERENCES analysis_runs(run_id) ON DELETE CASCADE,
    node_label INTEGER,
    pu_kn REAL, tu_kn REAL, vu_kn REAL
);
CREATE INDEX IF NOT EXISTS idx_reactions_run ON analysis_reactions(run_id);
"""


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        try:
            conn.execute("ALTER TABLE analysis_runs ADD COLUMN elem_axial_json TEXT")
        except sqlite3.OperationalError:
            pass
        conn.commit()
    finally:
        conn.close()


@contextmanager
def connect():
    """One connection per request; commits on success, rolls back on error."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"SQLite database initialized at {DB_PATH}.")
