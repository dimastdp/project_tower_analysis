# Tower Dashboard — Structural Tower Catalog & TIA-222-G Analysis (v2.0)

Local-first web application for telecom structural engineering:
- **Microstran (`.mst`) parser**: extracts the `DAT~` ASCII block (nodes, supports, members) and computes tower height, top width, and bottom width.
- **3D Wireframe Viewer**: interactive Plotly 3D model with equal aspect ratio and highlighted fixed supports (`111111`).
- **Ancillary Device Library (`ANCILLARY.lib`)**: imports operator antennas, microwave dishes, and mountings with computed drag coefficient $C_a$ and effective projected area ($\text{EPA} = A_f \times C_a$).
- **Site Inventory (`EXISTING` / `PROPOSED`)**: per-site equipment tracking with elevation profile visualization and library cross-checking.
- **TIA-222-G Static P-Delta Analysis**: 3D space-frame FEM analysis computing per-support compression ($P_u$), uplift ($T_u$), and horizontal shear ($V_u$), persisted in SQLite.

> **Engineering Notice:** Results are screening-level (placeholder member sections and self-wind area, single 45° resultant wind direction under $1.2D + 1.6W$) and are not a substitute for a licensed engineer's full code check.

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

