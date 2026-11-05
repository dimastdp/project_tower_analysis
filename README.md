# Tower Dashboard — Structural Tower Catalog & TIA-222-G Analysis (v2.4.0)

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![React 18](https://img.shields.io/badge/React-18-61dafb.svg)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178c6.svg)](https://www.typescriptlang.org/)
[![Vite](https://img.shields.io/badge/Vite-5.4-646cff.svg)](https://vitejs.dev/)
[![License](https://img.shields.io/badge/License-Proprietary-red.svg)]()

Aplikasi web *desktop-grade* (local-first) terpadu untuk analisis struktur menara telekomunikasi (Greenfield 3-Leg/4-Leg Lattice SST, Guyed Mast, & Rooftop Pole), komparasi langsung output **MS Tower V6 / Microstran (`.mst`)**, solver FEM **OpenSeesPy 3D Truss & Beam-Column**, ekstraksi otomatis dokumen laporan **SDA PDF**, dan ekspor laporan rekayasa berformula dinamis **Microsoft Excel (`.xlsx`)** serta format laporan teks native MS-Tower (`.rpt`).

---

## 🚀 Fitur Utama

### 1. 3-Pane macOS Finder Workspace & Apple HIG Minimalist UI
- **Left Pane (Directory Tree)**: Navigasi berkas virtual per site (`.mst`, `.td`, `.twr`, `.rpt`) serta folder inventori perangkat berbasis status (`EXISTING`, `PROPOSED`, `Missing .lib`) dan sektor/sisi menara (`Face A (0°)` s/d `Face D (270°)`).
- **Center Pane (High-Density Analysis Workbench)**: Tabel data berkepadatan tinggi dengan *semantic status dots* (`OK`, `WARNING`, `OVERSTRESS`), tombol aksi ganda (**Tombol A** vs **Tombol B**), dan ringkasan evaluasi per panel.
- **Right Pane (3D CAD Studio & Elevation Blueprint)**: Kanvas 3D interaktif `TowerViewer` (Plotly) dengan kontrol sudut pandang `ViewportFaceToolbar`, blueprint potongan 4 sisi `ElevationStrip`, dan kartu rekomendasi struktural *Go/No-Go*.

### 2. Dual-Engine Analisis Struktur TIA-222-G
- **Tombol A: "Bandingkan MST vs OpenSeesPy" (Cross-Validation)**:
  - Benchmark dan kalibrasi otomatis model OpenSeesPy terhadap gaya dalam dan kapasitas MS Tower V6 (`.rpt`).
  - Auto-complying perangkat inventori unmapped ke referensi library terdekat.
- **Tombol B: "Analisa OpenSeesPy Saja" (Standalone Engine)**:
  - Solver FEM mandiri OpenSeesPy 3D Corotational/Linear Space Truss.
  - Perhitungan beban angin antena & menara ANSI/TIA-222-G ($q_z = 0.613 \cdot K_z \cdot K_{zt} \cdot K_d \cdot V^2 \cdot I$).
  - Evaluasi kapasitas tekan & tekuk elastik/inelastik batang siku tunggal (*Single Angle Member Buckling*) sesuai **TIA-222-G Section 4.5.4** ($L_{eff}/r_{min}$, kurva kelangsingan eksentrisitas $KL/r$, faktor tekuk lokal $Q$, tegangan Euler $F_e$, tegangan tekuk kritis $F_{cr}$, dan $\phi P_n = 0.90 P_n$).
  - Pemeriksaan reaksi tumpuan kaki menara ($P_u, T_u, V_u = \sqrt{V_x^2 + V_y^2}$), verifikasi baut angkur (*anchor bolts*), dan pelat dasar (*base plate*).
  - Evaluasi lendutan operasional kecepatan angin 84 km/h (*Microwave Twist & Sway limit $\le 0.50^\circ$*).

### 3. Ekspor Laporan Excel Berformula Dinamis (`openpyxl`)
- **Sheet "Load Combinations"**: Kamus lengkap 42 kombinasi pembebanan standar (*Cases 100–3140*):
  - Primary Cases (`100` Dead Load, `200–340` Wind 8 arah mata angin).
  - Ultimate Compression (`500–660`: $1.20D + 1.60W$).
  - Ultimate Uplift / Tension (`1000–1140`: $0.90D + 1.60W$).
  - Serviceability Deflection (`2000–2140`: $1.00D + 1.00W$).
  - Operational 84 km/h Twist/Sway (`3000–3140`: $1.20D + 0.49W$).
- **Sheet "Member Check"**: Formula Excel aktif (tanpa nilai statis/hardcoded) untuk `VLOOKUP` kasus pembebanan penentu, kelangsingan, $KL/r$, $F_{cr}$, $\phi P_n$, $SR = |P_u|/\phi P_n$, status `IF(SR<=1, "OK", "OVER")`, $\Delta SR = SR_{OpenSees} - SR_{MST}$, dan rasio kapasitas tekuk $\phi P_{n,OS} / \phi P_{n,MST}$.
- **Sheet "Support Reactions" & "Tower Rotations"**: Formula resultan geser $= \sqrt{V_x^2 + V_y^2}$ dan logika verifikasi batas rotasi antena microwave $= \text{IF}(Sway \le Limit, "OK", "OVER")$.

### 4. Ekstraktor Dokumen PDF Laporan SDA (Special Data Assessment)
- Engine PyMuPDF (`pymupdf`) dengan dekoder font PUA (*Private Use Area*) untuk mengekstrak geometri `.td`, beban `.twr`, dan desain `.rpt` dari hasil cetakan printer driver MStower [V6.02.002].
- Ekspor satu klik ke paket arsip ZIP berkas native MS Tower (`.td`, `.twr`, `.rpt`, `.p1`, metadata JSON, dan inventori CSV).
- Konversi model ke berkas native `.mst` siap pakai.

---

## 🛠️ Arsitektur & Teknologi

| Lapisan | Komponen & Pustaka | Deskripsi |
|---|---|---|
| **Frontend** | React 18, TypeScript, Vite, TanStack Query v5, Plotly.js | Antarmuka pengguna responsif desktop Apple HIG, render CAD 3D, dan state management server-cache |
| **Backend** | Python 3.10+, FastAPI, Uvicorn, SQLite3 | REST API controller, serialisasi Pydantic v2, session thread-safe `FEM_LOCK` |
| **FEM Engine** | OpenSeesPy, NumPy, SciPy | 3D space frame/truss stiffness solver, analisa $P\text{-}\Delta$, kalkulasi gaya batang aksial |
| **Parsers & Report** | PyMuPDF, OpenPyXL, Regex Engine | Parser format Microstran/MS-Tower (`DAT~`, `TWR~`, `RPT~`), generator Excel dinamis |

---

## ⚡ Panduan Menjalankan Aplikasi (Quick Start)

### 1. Persiapan Backend (FastAPI + OpenSeesPy)

```powershell
cd tower_dashboard\backend

# Buat dan aktifkan virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Pasang dependensi
pip install -r requirements.txt

# Inisialisasi basis data SQLite
python db.py

# Jalankan server FastAPI backend (port 8000)
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

- **Health check**: `http://127.0.0.1:8000/api/health`
- **Swagger / OpenAPI docs**: `http://127.0.0.1:8000/docs`
- **Menjalankan Unit Test (Pytest)**:
  ```powershell
  pytest -q
  ```

### 2. Persiapan Frontend (React + Vite)

Buka terminal baru:

```powershell
cd tower_dashboard\frontend

# Pasang dependensi Node.js
npm install

# Jalankan Vite development server (port 5173)
npm run dev
```

Buka peramban ke **`http://localhost:5173`**. Vite dikonfigurasi secara otomatis mem-proxy panggilan `/api/*` ke `http://127.0.0.1:8000`.

### 3. Production Build (Single Server)

Aplikasi dapat dikompilasi menjadi satu server tunggal terpadu di mana FastAPI melayani static file build React:

```powershell
# 1. Build frontend
cd tower_dashboard\frontend
npm run build

# 2. Jalankan backend production
cd ..\backend
.\.venv\Scripts\uvicorn.exe main:app --host 127.0.0.1 --port 8000
```

Aplikasi siap diakses langsung di **`http://127.0.0.1:8000`**.

---

## 📂 Struktur Proyek

```text
Data_mstower/
├── .agents/                               # Panduan agen AI & skill domain teknik struktur
│   ├── skills/frontend-design/SKILL.md    # Apple HIG minimalist styling & 3-pane finder specs
│   └── tower-structural-analyst/SKILL.md  # Standar TIA-222-G, OpenSeesPy, & formula Excel
├── tower_dashboard/
│   ├── backend/
│   │   ├── main.py                        # FastAPI routes & controller endpoints
│   │   ├── opensees_model.py              # OpenSeesPy 3D FEM solver & TIA-222-G math
│   │   ├── report_export.py               # Generator workbook Excel dinamis (openpyxl)
│   │   ├── parsers.py                     # Parser file .mst, .lib, .td, .twr, .rpt
│   │   ├── pdf_sda_extractor.py           # Ekstraktor PDF SDA (PyMuPDF PUA decoder)
│   │   ├── db.py                          # Skema SQLite3 & helper query
│   │   └── tests/test_api.py              # 23 automated regression pytest suites
│   └── frontend/
│       ├── src/
│       │   ├── pages/
│       │   │   ├── TowersPage.tsx         # Katalog struktur, 3D viewer, & virtual file tree
│       │   │   ├── InventoryPage.tsx      # Inventori antena, sektor A-D, & 4-face blueprint
│       │   │   ├── AnalysisPage.tsx       # TIA-222-G workbench, Tombol A & B, export Excel
│       │   │   └── LibraryPage.tsx        # Katalog perangkat master MTEL.lib & project .lib
│       │   ├── components/
│       │   │   ├── TowerViewer.tsx        # Plotly 3D wireframe & stress ratio stage
│       │   │   ├── ElevationStrip.tsx     # Blueprint elevasi proporsional 4 sisi
│       │   │   └── ViewportFaceToolbar.tsx# Kontrol kamera sudut pandang Face A/B/C/D
│       │   ├── api.ts                     # Klien tunggal fetch API
│       │   └── index.css                  # Apple HIG minimalist design tokens & 3-pane layout
├── CHANGELOG.md                           # Riwayat versi rilis (Keep a Changelog)
├── VERSION                                # Single source of truth nomor versi (2.4.0)
└── MTEL.lib                               # Master library perangkat antena, microwave, & mounting
```

---

## 📄 Standar Dokumentasi & Riwayat Perubahan

- [CHANGELOG.md](CHANGELOG.md) — Riwayat lengkap perubahan versi fitur dan perbaikan bug.
- [VERSION](VERSION) — Nomor versi rilis aktif saat ini.
- [docs/VERSIONING.md](docs/VERSIONING.md) — Konvensi Semantic Versioning & Conventional Commits.
- [CATATAN_ITERASI_ANALISA_VS_MSTOWER.md](CATATAN_ITERASI_ANALISA_VS_MSTOWER.md) — Catatan teknis kalibrasi formula vs MS Tower V6.

---

## ⚖️ Lisensi
Hak Cipta © 2026 Dimas T. D. P. Seluruh hak cipta dilindungi undang-undang.
Dilisensikan untuk keperluan rekayasa struktur internal telekomunikasi.
