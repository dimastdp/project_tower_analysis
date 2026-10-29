# Changelog

Semua perubahan penting pada proyek **Tower Dashboard (Structural Tower Catalog & TIA-222-G Analysis)** didokumentasikan dalam berkas ini.

Format berkas ini mengacu pada [Keep a Changelog](https://keepachangelog.com/id/1.1.0/), dan proyek ini mematuhi prinsip [Semantic Versioning](https://semver.org/lang/id/).

---

## [Unreleased]
### Planned
- Export laporan analisis struktural format PDF profesional dengan ringkasan 3-parameter MS Tower.
- Integrasi perkuatan member (*reinforcement*) otomatis pada member berstatus overstress ($SR > 1.0$).

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
