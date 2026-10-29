---
name: tower-dashboard-webapp
description: >-
  Use this skill whenever building, modifying, debugging, reviewing or testing the
  Tower Dashboard web application (Structural Tower Catalog & TIA-222-G Analysis):
  React 18 + Vite + TypeScript frontend, FastAPI + SQLite backend, Microstran .mst /
  ANCILLARY.lib parsers, and the OpenSeesPy FEM analysis. Trigger on mentions of
  towers, sites, .mst, ANCILLARY.lib, device library, inventory (EXISTING/PROPOSED),
  wind analysis, reactions (Pu/Tu/Vu), TIA-222-G, OpenSeesPy, or the webapps blueprint.
---

# Tower Dashboard Web App

The single source of truth is the blueprint:
[webapps_development_blueprint_v2_en.md](../../../webapps_development_blueprint_v2_en.md)
(workspace root). Read only the section you need — use the line map below.

## Blueprint Section Map

| Need | Section | Lines (approx.) |
|------|---------|-----------------|
| Goals, user stories, FR/NFR | 1. PRD | 39–153 |
| Architecture, stack, layout, FEM rules, TIA-222-G loads, errors, security, tests | 2. TRD | 156–320 |
| Routes, screens, user flows, cross-cutting UI behavior | 3. AFD | 323–422 |
| Design tokens, layout, components, 3D viewer, a11y | 4. DBD | 425–544 |
| ERD, SQLite DDL, data rules, REST API contract | 5. BSD | 547–836 |
| Phases, tasks, Definition of Done, release checklist | 6. IPD | 839–942 |
| Reference code (backend) | 7.1 | 948–1692 |
| Reference code (frontend) | 7.2 | 1693–2676 |
| Quick start, known limitations | 7.3–7.4 | 2677–end |

Locate exact lines quickly:
`Select-String -Path webapps_development_blueprint_v2_en.md -Pattern '^#{1,3} '`

## Non-Negotiable Rules

**Architecture (TRD 2.4)**
- `parsers.py` never touches the DB; `opensees_model.py` never reads files or DB;
  `main.py` holds no FEM math; `db.py` holds no business rules.
- Frontend: `src/api.ts` is the ONLY place that calls `fetch`. Pages do not parse
  engineering data. Server state goes through TanStack Query.
- Active site is global (header selector, `SiteContext`, persisted in `localStorage`).

**Backend**
- All SQL parameterized — never f-strings in queries.
- Do not list `sqlite3` in `requirements.txt`.
- Re-upload of a `.mst` = upsert tower, replace nodes/members, KEEP `site_devices` and runs.
- `site_name` = uppercased `.mst` filename without extension.
- Every OpenSeesPy run inside one process-wide `threading.Lock`; check `ops.analyze` return code.
- Error responses use `{"detail": "..."}` with the HTTP codes in TRD 2.8.
- Bind to `127.0.0.1`; upload limits 50 MB `.mst`, 5 MB `.lib`.

**FEM / TIA-222-G (TRD 2.5–2.6)**
- Units m, kN, kN/m²; `ndm=3, ndf=6`; skip nodes with `flag == -1` or `abs(x) > 1e5`.
- Supports = restraint `111111`. `elasticBeamColumn` + `PDelta`; Y-parallel members use `vecxz=(0,0,1)`.
- `Kz = 2.01·(max(z,4.6)/274.32)^(2/9.5)`, `qz = 0.613·Kz·Kzt·Kd·V²·I/1000`,
  Kd 0.85, Kzt 1.0, I 1.0, Gh 0.85, 1.2D + 1.6W, 45° resultant (0.707).
- Device loads come from inventory EPA/mass × qty, distributed to free nodes at the nearest level.
- Unknown device names → EPA 0 plus a `warnings[]` entry; never silently fake results.

**Frontend / Design (DBD)**
- Plain CSS with the DBD tokens (`--bg`, `--surface`, `--primary`, `--existing`,
  `--proposed`, `--danger`, …) for light and dark themes. Inter for UI, JetBrains Mono
  for numbers (tabular figures, right-aligned).
- Every page has loading (skeleton), empty and error (`role="alert"`) states.
- Always show units (m, kN, m/s). Destructive deletes ask for confirmation.
- 3D viewer: Plotly, equal aspect, supports highlighted, text summary beside it.

**Never**: hard-code demo numbers in user-visible output (e.g. `42.0 / 1.30 / 4.00`,
leg ratio `0.54`, dummy 3D points). Phase-2 features are marked as such, not faked.

## Workflow

1. Identify the IPD phase/task (Section 6.2) the request belongs to.
2. Read the relevant PRD/AFD/DBD/BSD section(s) and the matching reference file in Section 7.
3. Implement under the layout in TRD 2.3 (`backend/`, `frontend/src/...`).
4. If the API or schema changes, update the BSD section of the blueprint too.
5. Verify (below) and check the Definition of Done (IPD 6.4).

## Run & Verify

```powershell
# Backend (from backend/)
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python db.py                       # init schema
uvicorn main:app --reload --host 127.0.0.1 --port 8000
pytest -q                          # parser, route and analysis tests

# Frontend (from frontend/)
npm install
npm run dev                        # Vite proxies /api -> :8000
npm run build                      # type-check + production build
```

- Health check: `GET http://127.0.0.1:8000/api/health`; API docs at `/docs`.
- UI happy path (use the `webapp-testing` skill / browser): upload `.mst` → 3D view
  renders → import `ANCILLARY.lib` → add PROPOSED device → run analysis → reactions
  shown and persisted on reload.
- Same inputs must give the same reactions; adding a proposed device must increase loads.

> Engineering notice: results are screening-level, not a substitute for a licensed engineer's code check.
