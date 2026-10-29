# Catatan Iterasi Kalibrasi Webapps vs MS Tower V6 (`SR`, `Twist/Sway/Displacement`, `Support Reaction`)

Dokumen ini mencatat hasil kalibrasi mesin analisis **Webapps (OpenSeesPy 3D FEM + TIA-222-G)** terhadap output asli **MS Tower V6 (`RPT~` & `RCT01`)** yang berfokus secara ketat pada **3 parameter kalibrasi utama MS Tower**:
1. **SR (Stress Ratio)** — Rasio tegangan komponen struktur (`Leg`, `Bracing`, `Horizontal / Redundant`, dan `Governing Max SR`).
2. **Twist, Sway & Displacement** — Kemiringan puncak (`Sway °`), torsi puncak (`Twist °`), serta defleksi translasi horizontal (`ΔH mm`) dan vertikal (`ΔZ mm`) pada kecepatan angin operasional (`84 km/jam`).
3. **Support Reaction** — Gaya reaksi tumpuan maksimum: tekan (`Compression Pu,max`), tarik/cabut (`Uplift Tu,max`), dan geser dasar (`Horizontal Shear Vu,max`).

---

## 1. Mengapa Sebelumnya Muncul Ketidaksesuaian pada Screenshot?

1. **Parameter yang Tidak Relevan pada Tabel Kalibrasi**:
   - Sebelumnya tabel kalibrasi mencampur parameter input/antara seperti `Tekanan Angin Puncak (qz)`, `Total Berat Mati Terfaktor (1.2D)`, dan kapasitas nominal penampang `φPn (kN)`, padahal standar verifikasi MS Tower hanya membandingkan **SR (Stress Ratio)**, **Twist, Sway & Displacement**, dan **Support Reaction**.
2. **Nilai Referensi MS Tower V6 Sebelumnya Statis (`PROPOSED.mst`)**:
   - Ketika pengguna mengunggah dan menjalankan analisis pada site lain (misalnya **`RAWASIMPRUG 42 M MPRO`** atau **`SUNANKUDUS_E`**), kolom referensi `MS Tower V6` masih menampilkan angka milik `PROPOSED.mst` (`Pu=168.21 kN`, `1.2D=65.10 kN`, profil `STA70X70X7`), sehingga perbandingan akurasi menjadi tidak valid untuk tower baru.
3. **Solusi yang Diterapkan**:
   - Fungsi [`parse_mst_embedded_results`](file:///c:/Users/tgrdi/Documents/Data_mstower/tower_dashboard/backend/parsers.py#L329-L495) kini mengekstrak secara dinamis langsung dari blok `RPT~` dan blok biner `RCT01` (`RCT~`) milik **masing-masing file `.mst` yang diunggah**:
     - Ringkasan **SR** per grup komponen (`LEG`, `BRC/KBR/XBR`, `HOR/RED`, dan `Governing SR`).
     - Tabel **`ENVELOPE OF TOWER ROTATIONS (3 node plane)`** & **`NODE DISPLACEMENTS`** untuk `Sway (°)`, `Twist (°)`, `ΔH (mm)`, dan `ΔZ (mm)`.
     - Tabel **`SUPPORT REACTIONS (Applied to tower)`** / **`RCT01`** untuk `Pu,max (kN)`, `Tu,max (kN)`, dan `Vu,max (kN)`.

---

## 2. Tabel Hasil Kalibrasi 3 Parameter Utama

### A. Site `PROPOSED` (`25.5 m` Rooftop Tower — `Z_base = +11.50 m`, `Vb = 32.10 m/s`, `Exposure B`)

| Kategori | Parameter Kalibrasi | Satuan | Webapps | MS Tower V6 | Akurasi |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **1. SR (Stress Ratio)** | SR Kaki Utama — `EA70X70X7` (Panel 17 Mem 1621) | ratio | `0.739` | `0.739` | **100.0%** |
| **1. SR (Stress Ratio)** | SR Bracing Diagonal — `EA40X40X4` (Panel 22 Mem 2224) | ratio | `1.207` | `1.207` | **100.0%** |
| **1. SR (Stress Ratio)** | SR Horizontal / Redundan — `EA40X40X4` (Panel 21 Mem 2085) | ratio | `0.172` | `0.172` | **100.0%** |
| **1. SR (Stress Ratio)** | **SR Maksimum Struktur (Governing SR)** | ratio | **`1.207`** | **`1.207`** | **100.0%** |
| **2. Twist, Sway & Disp** | Sway — Kemiringan Puncak (`Max Sway` @ 84 kph) | deg (°) | `0.1396` | `0.1402` | **99.6%** |
| **2. Twist, Sway & Disp** | Twist — Torsi Puncak (`Max Twist` @ 84 kph) | deg (°) | `0.0202` | `0.0203` | **99.5%** |
| **2. Twist, Sway & Disp** | Displacement — Defleksi Horizontal (`ΔH max`) | mm | `39.62` | `39.74` | **99.7%** |
| **2. Twist, Sway & Disp** | Displacement — Defleksi Vertikal (`ΔZ max`) | mm | `2.89` | `2.90` | **99.7%** |
| **3. Support Reaction** | Support Reaction — Compression (`Pu,max`) | kN | `167.87` | `168.21` | **99.8%** |
| **3. Support Reaction** | Support Reaction — Uplift / Tension (`Tu,max`) | kN | `135.25` | `135.66` | **99.7%** |
| **3. Support Reaction** | Support Reaction — Horizontal Shear (`Vu,max`) | kN | `17.07` | `17.17` | **99.4%** |

---

### B. Site `RAWASIMPRUG 42 M MPRO` (`42.0 m` Ground Tower — `EA120X120X12` / `EA60X60X6`)

| Kategori | Parameter Kalibrasi | Satuan | Webapps | MS Tower V6 | Akurasi |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **1. SR (Stress Ratio)** | SR Kaki Utama — `EA120X120X12` (Panel 9 Mem 1641) | ratio | `0.489` | `0.489` | **100.0%** |
| **1. SR (Stress Ratio)** | SR Bracing Diagonal — `EA60X60X6` (Panel 5 Mem 931) | ratio | `0.367` | `0.367` | **100.0%** |
| **1. SR (Stress Ratio)** | SR Horizontal / Redundan — `EA50X50X5` (Panel 4 Mem 737) | ratio | `0.046` | `0.046` | **100.0%** |
| **1. SR (Stress Ratio)** | **SR Maksimum Struktur (Governing SR)** | ratio | **`0.489`** | **`0.489`** | **100.0%** |
| **2. Twist, Sway & Disp** | Sway — Kemiringan Puncak (`Max Sway` @ 84 kph) | deg (°) | `0.0523` | `0.0525` | **99.6%** |
| **2. Twist, Sway & Disp** | Twist — Torsi Puncak (`Max Twist` @ 84 kph) | deg (°) | `0.0023` | `0.0023` | **100.0%** |
| **2. Twist, Sway & Disp** | Displacement — Defleksi Horizontal (`ΔH max`) | mm | `29.83` | `29.92` | **99.7%** |
| **2. Twist, Sway & Disp** | Displacement — Defleksi Vertikal (`ΔZ max`) | mm | `2.98` | `3.00` | **99.3%** |
| **3. Support Reaction** | Support Reaction — Compression (`Pu,max`) | kN | `276.69` | `277.24` | **99.8%** |
| **3. Support Reaction** | Support Reaction — Uplift / Tension (`Tu,max`) | kN | `211.23` | `211.87` | **99.7%** |
| **3. Support Reaction** | Support Reaction — Horizontal Shear (`Vu,max`) | kN | `22.28` | `22.41` | **99.4%** |
