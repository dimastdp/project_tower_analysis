# Tower Dashboard — Structural Tower Catalog & TIA-222-G Analysis (v2.0.0)

Local-first web application for telecom structural engineering:
- **Microstran (`.mst`) parser**: extracts the `DAT~` ASCII block (nodes, supports, members) and computes tower height, top width, and bottom width.
- **3D Wireframe & Stress Ratio Viewer**: interactive Plotly 3D model with equal aspect ratio and MS Tower V6 stress ratio coloring.
- **Ancillary Device Library (`ANCILLARY.lib`)**: imports operator antennas, microwave dishes, and mountings with computed drag coefficient $C_a$ and effective projected area ($\text{EPA} = A_f \times C_a$).
- **Site Inventory (`EXISTING` / `PROPOSED`)**: per-site equipment tracking with 4-face elevation blueprints (A/B/C/D) and library cross-checking.
- **TIA-222-G Static P-Delta Analysis & MS Tower Calibration**: 3D space-frame FEM analysis with dynamic calibration against the 3 core MS Tower V6 outputs (Stress Ratio, Twist/Sway/Disp, Support Reaction).

> **Documentation & Versioning Standards:**
> - [CHANGELOG.md](../CHANGELOG.md) — Riwayat lengkap perubahan versi (Keep a Changelog format).
> - [VERSION](../VERSION) — Single source of truth versi aktif (`2.0.0`).
> - [docs/VERSIONING.md](../docs/VERSIONING.md) — Standar Semantic Versioning, Conventional Commits, dan alur rilis.
> - [CATATAN_ITERASI_ANALISA_VS_MSTOWER.md](../CATATAN_ITERASI_ANALISA_VS_MSTOWER.md) — Catatan teknis kalibrasi formula vs MS Tower V6.

---

## Quick Start

### 1. Backend (FastAPI + SQLite)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python db.py
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

- Health check: `http://127.0.0.1:8000/api/health`
- Interactive OpenAPI docs: `http://127.0.0.1:8000/docs`
- Run test suite:
  ```powershell
  pytest -q
  ```

### 2. Frontend (React 18 + TypeScript + Vite)

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api/*` requests to `http://127.0.0.1:8000`.

### 3. Single-Server Production Build

When `frontend/dist` exists, FastAPI serves the built SPA directly on `http://127.0.0.1:8000`:

```powershell
cd frontend
npm run build
cd ..\backend
.\.venv\Scripts\uvicorn.exe main:app --host 127.0.0.1 --port 8000
```

