import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(scope="session")
def samples(tmp_path_factory):
    from make_samples import write_lib, write_mst

    d = tmp_path_factory.mktemp("samples")
    write_mst(d / "SAMPLE-4LEG.mst")
    write_lib(d / "ANCILLARY.lib")
    return d


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TOWER_DB_PATH", str(tmp_path / "test.db"))
    import db

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as c:
        yield c
