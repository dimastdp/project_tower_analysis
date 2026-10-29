# Changelog

Semua perubahan penting pada proyek **Tower Dashboard (Structural Tower Catalog & TIA-222-G Analysis)** didokumentasikan dalam berkas ini.

Format berkas ini mengacu pada [Keep a Changelog](https://keepachangelog.com/id/1.1.0/), dan proyek ini mematuhi prinsip [Semantic Versioning](https://semver.org/lang/id/).

---

## [Unreleased]
### Planned
- Export laporan analisis struktural format PDF profesional dengan ringkasan 3-parameter MS Tower.
- Integrasi perkuatan member (*reinforcement*) otomatis pada member berstatus overstress ($SR > 1.0$).

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

