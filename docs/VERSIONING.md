# Panduan Versioning & Dokumentasi Perubahan Proyek

Dokumen ini menjelaskan standar rekayasa perangkat lunak (*software engineering standards*) yang diterapkan pada proyek **Tower Dashboard**, meliputi skema penomoran versi (Semantic Versioning), konvensi commit Git (Conventional Commits), pemeliharaan Changelog, serta alur rilis (*release workflow*).

---

## 1. Skema Penomoran Versi (Semantic Versioning 2.0.0)

Format versi yang digunakan adalah:

$$\text{v}\mathbf{MAJOR}.\mathbf{MINOR}.\mathbf{PATCH}$$

Contoh: `v2.0.0`

### Aturan Kenaikan Versi:
1. **MAJOR (X.0.0)**:
   - Ditingkatkan saat terdapat perubahan struktural besar, perombakan arsitektur, *breaking changes* pada API, atau perombakan total desain antarmuka (misalnya: transisi ke Apple Cupertino Design System & kalibrasi ulang dinamis pada `v2.0.0`).
2. **MINOR (x.Y.0)**:
   - Ditingkatkan saat penambahan fitur baru yang *backward-compatible* (misalnya: penambahan elevasi 4 sisi, modal preflight check, atau penambahan role DevOps/PM).
3. **PATCH (x.y.Z)**:
   - Ditingkatkan saat perbaikan *bug*, perbaikan formula kecil, optimasi performa, atau pembaruan dokumentasi tanpa mengubah fungsionalitas yang ada.

---

## 2. Standar Konvensi Git Commit (Conventional Commits)

Format penulisan pesan commit:

```
<type>(<scope>): <deskripsi singkat imperatif>

[opsional: body penjelasan teknis mendalam]
[opsional: footer issue/breaking change]
```

### Kategori `<type>`:
- `feat`: Penambahan fitur fungsional baru (memicu kenaikan versi MINOR).
- `fix`: Perbaikan bug atau galat perhitungan (memicu kenaikan versi PATCH).
- `docs`: Perubahan atau penambahan berkas dokumentasi (`README`, `CHANGELOG`, dll).
- `style`: Perubahan gaya visual UI/UX (CSS, styling) tanpa mengubah logika backend.
- `refactor`: Restrukturisasi kode tanpa mengubah fungsionalitas eksternal.
- `perf`: Optimasi performa komputasi atau waktu render.
- `test`: Penambahan atau perbaikan unit test / integration test.
- `chore`: Pemeliharaan dependensi, berkas build, atau konfigurasi repositori.

### Contoh Pesan Commit:
```bash
feat(calibration): extract 3 core ms tower parameters dynamically from rpt and rct blocks
style(ui): redesign frontend workbench following apple cupertino hig
fix(parsers): resolve member section names from rpt when dat pattern is missing
docs(changelog): document release v2.0.0 with keep-a-changelog format
```

---

## 3. Pemeliharaan Berkas `CHANGELOG.md`

Setiap pengembang yang menambahkan fitur atau memperbaiki bug **wajib** memperbarui `CHANGELOG.md` di direktori *root*.

Gunakan kategori standar Keep a Changelog:
- `### Added`: Untuk fitur baru.
- `### Changed`: Untuk perubahan fungsionalitas yang sudah ada.
- `### Deprecated`: Untuk fitur yang akan dihapus pada versi mendatang.
- `### Removed`: Untuk fitur yang telah dihapus.
- `### Fixed`: Untuk perbaikan bug.
- `### Security`: Untuk penambalan celah keamanan.

Setiap perubahan yang belum dirilis dimasukkan ke dalam seksi `## [Unreleased]`.

---

## 4. Single Source of Truth untuk Versi

Versi aplikasi dijaga konsistensinya di 3 titik utama:
1. Berkas plain-text di root: [`VERSION`](file:///c:/Users/tgrdi/Documents/Data_mstower/VERSION) (`2.0.0`).
2. Backend API: [`main.py`](file:///c:/Users/tgrdi/Documents/Data_mstower/tower_dashboard/backend/main.py) (`__version__ = "2.0.0"`, exposed via `GET /api/version` dan `GET /api/health`).
3. Frontend Client: [`package.json`](file:///c:/Users/tgrdi/Documents/Data_mstower/tower_dashboard/frontend/package.json) (`"version": "2.0.0"`).

---

## 5. Alur Rilis (*Release Workflow*)

Langkah-langkah pembuatan rilis baru:
```bash
# 1. Pastikan seluruh unit test lolos
pytest -q

# 2. Perbarui versi di VERSION, main.py, dan package.json
# 3. Pindahkan entri dari [Unreleased] ke [X.Y.Z] di CHANGELOG.md
# 4. Commit perubahan
git add .
git commit -m "chore(release): bump version to vX.Y.Z"

# 5. Buat Git Tag beranotasi
git tag -a vX.Y.Z -m "Release vX.Y.Z: <Ringkasan Rilis>"
```

