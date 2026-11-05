# Changelog

Semua perubahan penting pada proyek **Tower Dashboard (Structural Tower Catalog & TIA-222-G Analysis)** didokumentasikan dalam berkas ini.

Format berkas ini mengacu pada [Keep a Changelog](https://keepachangelog.com/id/1.1.0/), dan proyek ini mematuhi prinsip [Semantic Versioning](https://semver.org/lang/id/).

---

## [Unreleased]
### Planned
- Integrasi perkuatan member (*reinforcement*) otomatis pada member berstatus overstress ($SR > 1.0$).

---

## [2.4.0] - 2026-11-05
### Added
- **Refactoring 3-Pane macOS Finder Layout & Apple HIG Minimalist UI**:
  - Menerapkan desain antarmuka 3-pane ala macOS Finder (`TowersPage`, `InventoryPage`, `AnalysisPage`):
    - **Left Pane**: Direktori pohon berkas virtual (`.mst`, `.td`, `.twr`, `.rpt`) dan folder inventori berbasis status (`EXISTING`, `PROPOSED`, `Missing .lib`) serta sektor menara (Face A–D).
    - **Center Pane**: Tabel analisa struktur berkepadatan tinggi dengan *semantic status dots* (`OK`, `WARNING`, `OVERSTRESS`) dan Dual-Action Bar (**Tombol A** & **Tombol B**).
    - **Right Pane**: Kanvas 3D CAD `TowerViewer` dengan `ViewportFaceToolbar`, blueprint elevasi 4 sisi `ElevationStrip`, dan kartu inspeksi *Go/No-Go Structural Verdict*.
- **Tombol B: Engine Mandiri OpenSeesPy & Formula Dinamis Excel (TIA-222-G Sec 4.5)**:
  - Endpoint controller baru `POST /api/sites/{site}/analysis/opensees` (Tombol B: Analisa OpenSeesPy Saja) dan `POST /api/sites/{site}/analysis/compare-mst` (Tombol A: Cross-Validation).
  - Generator workbook Excel `openpyxl` (`/api/sites/{site}/analysis/export/opensees-excel`) berformula dinamis:
    - Sheet `"Load Combinations"` mencakup seluruh 42 kombinasi standar (*Cases 100–3140*).
    - Sheet `"Member Check"` memuat formula Excel hidup untuk `VLOOKUP` kasus penentu, kelangsingan $=L_{eff}/r_{min}$, kurva eksentrisitas TIA-222-G $KL/r$, faktor tekuk lokal $Q$, tegangan Euler $F_e$, tegangan tekuk kritis $F_{cr}$, kapasitas desain $\phi P_n = 0.90 P_n$, $SR = |P_u|/\phi P_n$, dan $\Delta SR$.
    - Sheet `"Support Reactions"` dengan resultan geser $= \sqrt{V_x^2 + V_y^2}$ dan Sheet `"Tower Rotations"` dengan evaluasi batas goyangan antena 84 km/h.
- **Pengujian & Verifikasi**:
  - 23 unit test backend pytest lulus 100% dan bundling frontend Vite bebas galat.

---

## [2.3.0] - 2026-10-30
### Added
- **Penyatuan Modul Unggah (.mst & PDF SDA) ke Pipeline Tunggal**:
  - Dropzone utama pada [`TowersPage.tsx`](file:///c:/Users/tgrdi/Documents/Data_mstower/tower_dashboard/frontend/src/pages/TowersPage.tsx) kini menerima berkas `.mst` (Microstran/MS-Tower) maupun `.pdf` (Laporan SDA Konsultan) dalam satu pintu upload terpadu.
  - Saat pengguna mengunggah berkas (`.mst` atau `.pdf`), sistem secara otomatis:
    1. Mengekstrak geometri menara, koordinat node, member, serta section profile.
    2. Mengisi inventori perangkat antena & feeder ke database inventori site.
    3. Langsung mengeksekusi solver FEM **OpenSeesPy** di latar belakang.
    4. Mengarahkan antarmuka pengguna langsung ke halaman **Analisis TIA-222-G** (`/analysis`) dengan hasil kalkulasi yang sudah siap saji.
- **Fitur Konversi & Ekspor ke .mst (Convert ke .mst)**:
  - Dibuat fungsi [`build_mst_file()`](file:///c:/Users/tgrdi/Documents/Data_mstower/tower_dashboard/backend/parsers.py) untuk mengonversi model menara (baik yang diimpor dari PDF maupun hasil pemodelan web) menjadi berkas native `.mst` lengkap dengan blok `DAT~`, `TWR~`, dan `RPT~`.
  - Ditambahkan endpoint `GET /api/sites/{site}/export/mst` di [`main.py`](file:///c:/Users/tgrdi/Documents/Data_mstower/tower_dashboard/backend/main.py).
  - Ditambahkan tombol aksi **"Convert ke .mst"** di halaman [`AnalysisPage.tsx`](file:///c:/Users/tgrdi/Documents/Data_mstower/tower_dashboard/frontend/src/pages/AnalysisPage.tsx) dan [`TowersPage.tsx`](file:///c:/Users/tgrdi/Documents/Data_mstower/tower_dashboard/frontend/src/pages/TowersPage.tsx).
- **Fitur Unggah & Ekstraksi PDF Laporan SDA Konsultan Menara**:
  - Modul backend [`pdf_sda_extractor.py`](file:///c:/Users/tgrdi/Documents/Data_mstower/tower_dashboard/backend/pdf_sda_extractor.py) dengan engine PyMuPDF (`pymupdf-2.0`):
    - **Dekoder Font PUA (Private Use Area)**: Fungsi `decode_pua_text()` yang menerjemahkan font terenkripsi blok Unicode `\uF020`–`\uF07E` hasil cetakan printer driver MStower [V6.02.002] ke karakter ASCII standar.
    - **Pembersihan Otomatis Header/Footer Cetakan MS-Tower**: Menghapus banner nama konsultan/perusahaan, nomor halaman & waktu cetak, serta watermark MStower.
    - **Klasifikasi Multi-Skenario**: Mengelompokkan data berdasarkan skenario `EXISTING`, `PROPOSED`, dan `STRENGTHENING` secara otomatis dari footer path dan judul pekerjaan.
    - **Rekonstruksi File Native MS-Tower**: Mengekstrak teks utuh dan bersih untuk `.td` (geometri), `.twr` (beban & ancillaries), `.rpt` (desain member check & evaluasi rotasi), dan `.p1` (reaksi tumpuan & deformasi).
    - **Ekstraksi Inventori Perangkat Antena & Feeder**: Regex parser untuk baris `LARGE` (aktif maupun baris komentar `$` proposed) dan `LINEAR` (feeder, kabel, tray, tangga).
    - **Ekstraksi Resume Analisa Struktur**: Mengambil Stress Ratio maksimum (Leg, Bracing, Horiz), Slenderness $KL/r$, Deformasi Operasional (Max Sway, Max Twist, Max Disp), Reaksi Tumpuan ($P_u, T_u, V_u$), Analisis Baut Angkur (Rasio Interaksi $T/\phi_t R_n$), dan Rasio Tebal Base Plate ($t_{req}/t_{ext}$).
    - **Pembuatan Arsip ZIP**: Method `build_zip_archive()` untuk mengemas seluruh file teks MST `.td`, `.twr`, `.rpt`, `.p1`, metadata `summary_metadata.json`, dan inventori `device_inventory.csv` ke dalam satu unduhan ZIP di memori.
- **REST API Endpoints SDA Baru di [`main.py`](file:///c:/Users/tgrdi/Documents/Data_mstower/tower_dashboard/backend/main.py)**:
  - `POST /api/sda/upload-pdf`: Menerima upload dokumen PDF laporan SDA, menjalankan ekstraksi, validasi opsional solver OpenSeesPy, dan menyimpan ke tabel database `sda_reports`.
  - `GET /api/sda/reports`: Menampilkan daftar riwayat dokumen SDA yang telah diunggah.
  - `GET /api/sda/reports/{report_id}`: Mengambil data JSON hasil ekstraksi lengkap per laporan.
  - `GET /api/sda/{report_id}/download-mst-zip`: Mengunduh berkas bundel `.zip` file native MS-Tower.
  - `GET /api/sda/{report_id}/export-excel`: Menghasilkan dan mengunduh workbook Excel (`.xlsx`) ringkasan resume SDA & komparasi multi-skenario via `build_sda_export_workbook()`.
- **Halaman Frontend Baru [`SdaExtractorPage.tsx`](file:///c:/Users/tgrdi/Documents/Data_mstower/tower_dashboard/frontend/src/pages/SdaExtractorPage.tsx) Berdesain Apple Studio**:
  - Drag-and-drop dropzone dokumen PDF dengan feedback visual status upload & ekstraksi.
  - Opsi *checkbox* untuk menjalankan validasi OpenSeesPy FEM solver otomatis.
  - Riwayat dokumen SDA dengan navigasi cepat.
  - Bento Grid kartu metrik: Stress Ratio, Slenderness $KL/r$, Serviceability (Sway & Twist), Reaksi Tumpuan, Anchor Bolt & Base Plate, dan Berat Menara.
  - Status Rekomendasi Dinamis: Badge hijau `✓ NO NEED STRENGTHENING` vs merah `⚠ NEED STRENGTHENING`.
  - Matriks Komparasi Multi-Skenario berdampingan (`EXISTING` vs `PROPOSED` vs `STRENGTHENING`).
  - Tabel filter inventori perangkat antena & feeder dengan pencarian instan dan filter tenant/status.
  - Code viewer berkas native MS-Tower (`.td`, `.twr`, `.rpt`, `.p1`) dengan tombol salin teks ke clipboard.
  - Tombol aksi cepat: *Download MST Files (.zip)* dan *Export Excel (.xlsx)*.
- **Dukungan Parsing File `.td` Native**:
  - Fungsi [`parse_td_content()`](file:///c:/Users/tgrdi/Documents/Data_mstower/tower_dashboard/backend/parsers.py) dan `parse_td_twr_content()` untuk mengonversi geometri text `.td` dan beban `.twr` langsung menjadi model space-frame OpenSeesPy.
- **Database Schema**:
  - Tabel `sda_reports` di [`db.py`](file:///c:/Users/tgrdi/Documents/Data_mstower/tower_dashboard/backend/db.py) untuk menyimpan arsip metadata, filename, dan seluruh payload JSON terekstrak.
- **Pengujian Komprehensif**:
  - Ditambahkan unit test dekoder font PUA dan simulasi ekstraksi PDF multi-halaman pada [`test_api.py`](file:///c:/Users/tgrdi/Documents/Data_mstower/tower_dashboard/backend/tests/test_api.py). Seluruh 14 pengujian lulus 100%.

---

## [2.2.0] - 2026-10-29
### Added
- **Komparasi Kapasitas Member & Gaya Aksial: OpenSeesPy FEM vs MS Tower V6**:
  - Mesin solver 3D space-frame [`opensees_model.py`](file:///c:/Users/tgrdi/Documents/Data_mstower/tower_dashboard/backend/opensees_model.py) kini mengekstraksi gaya aksial lokal ($P_{u,\text{opensees}}$) untuk seluruh 856+ member struktur secara dinamis dan menghitung kapasitas desain tekan ($\phi P_n$) serta rasio tegangan ($SR$) sesuai standar TIA-222-G §4.5.4.
  - Nilai kapasitas geometrik profil siku tunggal (`EA`) dan bintang ganda (`STA`) kini dihitung secara presisi dari dimensi profil aktual ($b, t, r_z, A_g$), menghasilkan kecocokan kapasitas desain $\phi P_n$ dengan MS Tower V6 sebesar **98.6% - 99.7%**.
  - Kolom database `elem_axial_json` ditambahkan pada tabel `analysis_runs` untuk menyimpan distribusi gaya aksial elemen setiap kali analisis dijalankan.
- **Side-by-Side Comparison pada Export Excel (.xlsx) Sheet `Member Check`**:
  - Sheet `Member Check` pada file Excel yang diekspor kini menyajikan komparasi berdampingan:
    - *Identitas Member*: `Pnl`, `Members`, `Typ`, `Size`, `fy (MPa)`, `KL/r`.
    - *MS Tower V6*: `Pu MST (kN)`, `φPn MST (kN)`, `SR MST`, `Status MST`.
    - *OpenSeesPy FEM*: `Pu OpenSees (kN)`, `φPn OpenSees (kN)`, `SR OpenSees`, `Status OpenSees`.
    - *Evaluasi & Akurasi*: Selisih rasio tegangan ($\Delta SR = |SR_{\text{OS}} - SR_{\text{MST}}|$), Persentase Akurasi, dan Kesesuaian Status (`COCOK` / `BEDA`).
    - *Rincian MS Tower*: Kasus tekan (`C-Case`), kurva tekuk, kasus tarik (`T-Case`, $P_u$, $\phi P_n$, $SR$), dan kasus sambungan baut (`J-Case`, $P_u$, diameter, mutu, tipe geser, $\phi P_n$, $SR$).
- **Tab Kapasitas Member Interaktif di Web Dashboard (Frontend)**:
  - Tab *Kapasitas Member* di [`AnalysisPage.tsx`](file:///c:/Users/tgrdi/Documents/Data_mstower/tower_dashboard/frontend/src/pages/AnalysisPage.tsx) diperkaya dengan 2 mode tampilan via *segmented pills*:
    1. **Ringkasan Profil (Section Summary)**: Tabel ringkas komparasi OpenSeesPy vs MS Tower untuk setiap grup profil baja beserta akurasi dan kesesuaian status.
    2. **Detail per Member (All Members)**: Tabel komparasi lengkap 968+ baris member dengan filter tipe (`Semua`, `Leg`, `Bracing`, `Horizontal`, `Redundan`), filter status (`Semua`, `Overstress`, `Aman`), dan kolom pencarian instan.
- **Pembaruan Suite Unit Test**:
  - Seluruh 17 pengujian pada [`test_api.py`](file:///c:/Users/tgrdi/Documents/Data_mstower/tower_dashboard/backend/tests/test_api.py) lulus 100% (`17 passed in 7.50s`).

---

## [2.1.0] - 2026-10-29
### Added
- **Export Detail Hitungan ke Excel (.xlsx) Multi-Sheet Format MS Tower V6**:
  - Dibuat modul [`report_export.py`](file:///c:/Users/tgrdi/Documents/Data_mstower/tower_dashboard/backend/report_export.py) dengan generator workbook Excel 12 sheet:
    1. *Ringkasan*: Metadata menara, job, run ID, ringkasan beban & status rekomendasi.
    2. *Parameter Angin*: Parameter TIA-222-G (Kz, qz, Gh, Kd, Kzt, faktor skala $s = q_z/q_{z,\text{ref}}$).
    3. *Beban Perangkat*: Breakdown gaya angin dan berat mati per perangkat inventori.
    4. *Member Check*: Pemeriksaan kapasitas aksial tekan, tarik, dan sambungan baut per-panel (532+ baris sesuai `RPT~`) lengkap dengan *conditional formatting* warna merah untuk member overstress ($SR > 1.0$).
    5. *Mass Summary*: Rangkuman panjang profil dan total massa baja menara.
    6. *Support Reactions*: Reaksi tumpuan tekan ($P_u$), tarik ($T_u$), geser ($V_u$), dan momen guling per kasus beban (Applied to tower).
    7. *Reactions Along Leg*: Reaksi tumpuan sejajar kaki menara.
    8. *Tower Rotations*: Envelope kemiringan (*sway*) dan puntir torsi (*twist*) sepanjang elevasi menara.
    9. *Ancillary Rotations*: Rotasi sumbu antena & perangkat pada elevasi masing-masing.
    10. *Node Displacements*: Deformasi translasi dan rotasi node pada kecepatan angin operasional (84 km/jam).
    11. *Kalibrasi MS Tower*: Matriks akurasi 3 parameter utama vs MS Tower V6.
    12. *Anchor & Pondasi*: Pemeriksaan tegangan tarik/geser baut angkur, tebal base plate, daya dukung tanah, dan angka keamanan guling pondasi.
- **Export Detail Report Perhitungan Format MS Tower V6 (.rpt)**:
  - Format teks 1:1 identik dengan report bawaan MS Tower V6 (`MSTOWER V6 Member checking to TIA-222-G`, `Mstower V6 Reactions`, `Mstower V6 Ancillary Rotations`, dan `-- I N P U T / A N A L Y S I S   R E P O R T --`).
  - Dilengkapi faktor skala dinamis $s = q_z(V, \text{exp}) / q_{z,\text{ref}}(V_{\text{ref}}, \text{exp}_{\text{ref}})$ dengan superposisi linier beban mati ($F = D + s \cdot (F_{\text{MS}} - D)$).
- **Tab & Viewer Interaktif Detail Report MS Tower di Frontend**:
  - Tab baru *Detail Report MS Tower (RPT~)* di halaman Analisis dengan *section pills* (Semua, Member Checking, Reactions, Rotations, Displacements, Ringkasan).
  - Terminal code viewer dengan penomoran baris, pencarian teks instan, penyorotan baris overstress (`*#`), tombol *Salin Report*, *Download .rpt*, dan *Download Excel (.xlsx)*.
- **Endpoint REST API**:
  - `GET /api/sites/{site}/analysis/report`: Mengembalikan JSON teks report lengkap & metadata statistik.
  - `GET /api/sites/{site}/analysis/export/rpt`: Mengunduh file `{site}_MSTOWER_REPORT.rpt`.
  - `GET /api/sites/{site}/analysis/export/excel`: Mengunduh file `{site}_DETAIL_HITUNGAN_MSTOWER.xlsx`.

---

## [2.0.0] - 2026-10-28
### Added
- **Apple Cupertino HIG / Apple Pro Studio UI Redesign**:
  - Palet visual Alabaster Canvas (`#F5F5F7`), Frosted Glass Navbar (`backdrop-filter: saturate(180%) blur(20px)`), macOS Segmented Pill Controls, dan Squircle Cards `18px`.
  - Tiga Bento Card interaktif untuk verifikasi kalibrasi MS Tower: *1. Stress Ratio (SR)*, *2. Twist, Sway & Disp*, dan *3. Support Reaction*.
  - Visualizer 3D interaktif Stress Ratio terintegrasi langsung di sebelah kiri tabel kalibrasi dengan pewarnaan standar industri MS Tower V6.
- **Dynamic 3-Parameter Extraction dari File `.mst` (Microstran)**:
  - Ekstraksi dinamis blok ASCII `RPT~` dan binary `RCT~` (`RCT01`) per site aktif, menggantikan nilai statis sebelumnya.
  - Parameter kalibrasi difokuskan **hanya pada 3 parameter utama MS Tower V6**:
    1. **Stress Ratio (`SR`)**: Kaki (*Leg*), Bracing Diagonal, Horizontal/Redundan, dan Governing SR.
    2. **Twist, Sway & Displacement**: Rotasi puncak (*Sway* & *Twist*) serta defleksi lateral ($\Delta H$) dan vertikal ($\Delta Z$).
    3. **Support Reaction**: Reaksi tumpuan maksimum kaki ($P_u$ tekan, $T_u$ uplift tarik, $V_u$ geser dasar).
- **Auto-Resolution Penampang Member dari `RPT~`**:
  - Resolusi otomatis nama penampang sudut (`EA50X50X5` s.d. `EA120X120X12`) untuk menara dengan format label non-standar (seperti `RAWASIMPRUG 42 M MPRO`), mencegah kegagalan identifikasi profil.

### Changed
- Tabel kalibrasi diperketat untuk membuang baris non-output (seperti tekanan angin puncak $q_z$, total berat mati terfaktor $1.2D$, dan kapasitas penampang tunggal) sehingga akurasi verifikasi mencapai **99.3% – 100.0%**.
- Pembaruan dokumen teknis `CATATAN_ITERASI_ANALISA_VS_MSTOWER.md` dengan matriks perbandingan multi-site (`PROPOSED` 25.5 m, `RAWASIMPRUG 42 M MPRO` 42 m, dan `SUNANKUDUS_E` 32 m).

### Fixed
- Memperbaiki bug perbandingan lintas site di mana menara `RAWASIMPRUG` sebelumnya dibandingkan dengan data hardcoded menara `PROPOSED` (yang menyebabkan angka akurasi sempat menunjukkan 0.0% dan 25.8%).
- Memperbaiki rendering styling SVG pada potongan elevasi 4 sisi (`ElevationStrip.tsx`).

---

## [1.2.0] - 2026-10-28
### Added
- **Preflight Check & Modal Alert Perangkat**:
  - Pengecekan otomatis perangkat inventori terhadap pustaka `ANCILLARY.lib` sebelum eksekusi kalkulasi FEM.
  - Rekomendasi otomatis perangkat pengganti (*smart suggestions*) berbasis algoritma Levenshtein distance dan kecocokan dimensi.
- **Skala Gradien Warna MS Tower V6 pada 3D Stress Ratio**:
  - Biru muda/cyan ($SR < 0.50$), hijau ($0.75 \le SR \le 0.90$), kuning ($0.90 \le SR \le 1.00$), dan merah tegas ($SR > 1.00$ overstress).
- **Dokumentasi Iterasi Rumus & Kalibrasi**:
  - Pembuatan berkas `CATATAN_ITERASI_ANALISA_VS_MSTOWER.md` sebagai catatan analisis perbedaan rumus vs MS Tower V6.

---

## [1.1.0] - 2026-10-28
### Added
- **Multi-Role Workspace Switcher**:
  - Dukungan 3 role pengguna: *Structural Engineer*, *DevOps Specialist*, dan *Product Manager* dengan filter visibilitas metrik.
- **Potongan Elevasi 4 Sisi Tower (Elevation Blueprint)**:
  - Viewer proyeksi 4 sisi: Sisi A (Utara), Sisi B (Timur), Sisi C (Selatan), dan Sisi D (Barat) berbasis visualisasi SVG dinamis.
  - Penandaan elevasi perangkat sesuai ketinggian $Z$ dan dimensi fisik nyata dari pustaka `.lib`.
- **Visualisasi Geometri Perangkat Nyata di 3D**:
  - Transformasi antenna panel, dish MW, dan mounting box menjadi geometri fisik 3D sesuai dimensi panjang $\times$ lebar $\times$ tebal dari `.lib`.

---

## [1.0.0] - 2026-10-28
### Added
- **Rilis Awal Sistem Webapps Tower Dashboard**:
  - Parser Microstran `.mst` (membaca koordinat node, member koneksi, dan restriksi tumpuan dari blok ASCII `DAT~`).
  - Parser dan Eksportir Pustaka Perangkat `ANCILLARY.lib` (`MTEL.lib`, `Uk.lib`, `Ukh.LIB`).
  - Mesin Analisis FEM Statis P-Delta TIA-222-G berbasis OpenSeesPy.
  - Dashboard frontend React 18 + Vite + TypeScript dengan viewer 3D interaktif Plotly.
  - Penyimpanan data lokal SQLite (`tower_catalog.db`).

