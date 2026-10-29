import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import FileDrop from "../components/FileDrop";
import { useToast } from "../components/Toast";
import type { LibraryDevice } from "../types";

const SHAPES = ["BOX", "CYL", "SH1", "SHIELDED", "GRID", "UNITY"];
const CATEGORIES = ["TELKOMSEL", "IOH", "XL", "SMARTFREN", "SURGE", "MW DISHES", "MOUNTING", "GENERAL"];

export default function LibraryPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [catFilter, setCatFilter] = useState("ALL");
  const [showEditor, setShowEditor] = useState(false);
  const [showImporter, setShowImporter] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  // Add / edit device form state
  const [category, setCategory] = useState("TELKOMSEL");
  const [deviceName, setDeviceName] = useState("");
  const [shapeType, setShapeType] = useState("BOX");
  const [dimM, setDimM] = useState("2.60");
  const [massKg, setMassKg] = useState("25.0");
  const [afM2, setAfM2] = useState("0.910");
  const [asfM2, setAsfM2] = useState("0.390");
  const [remark, setRemark] = useState("");

  const devices = useQuery({ queryKey: ["library", q], queryFn: () => api.listDevices(q) });

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["library"] });
    qc.invalidateQueries({ queryKey: ["library-names"] });
    qc.invalidateQueries({ queryKey: ["inventory"] });
  };

  const importLib = useMutation({
    mutationFn: api.importLibrary,
    onSuccess: (r) => {
      const msg = `${r.imported} devices imported.`;
      setNotice(msg);
      toast(msg);
      invalidateAll();
    },
  });

  const syncMtel = useMutation({
    mutationFn: api.syncMtelLibrary,
    onSuccess: (r) => {
      const msg = `Synced ${r.imported} devices from ${r.source}.`;
      setNotice(msg);
      toast(msg);
      invalidateAll();
    },
  });

  const saveDevice = useMutation({
    mutationFn: () =>
      api.upsertLibraryDevice({
        category: category.trim() || "GENERAL",
        device_name: deviceName.trim(),
        shape_type: shapeType,
        dim_m: Number(dimM),
        mass_kg: Number(massKg),
        af_m2: Number(afM2),
        asf_m2: Number(asfM2),
        remark: remark.trim(),
      }),
    onSuccess: (saved) => {
      const msg = `Saved ${saved.device_name} (EPA ${saved.epa_m2.toFixed(3)} m²) & written to MTEL.lib`;
      setNotice(msg);
      toast(msg);
      setDeviceName("");
      setRemark("");
      invalidateAll();
    },
  });

  const removeDevice = useMutation({
    mutationFn: api.deleteLibraryDevice,
    onSuccess: (_d, name) => {
      toast(`Deleted ${name} from library`);
      invalidateAll();
    },
  });

  const loadIntoForm = (d: LibraryDevice) => {
    setCategory(d.category || "GENERAL");
    setDeviceName(d.device_name);
    setShapeType(d.shape_type || "BOX");
    setDimM(String(d.dim_m));
    setMassKg(String(d.mass_kg));
    setAfM2(String(d.af_m2));
    setAsfM2(String(d.asf_m2));
    setRemark(d.remark || "");
    setShowEditor(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!deviceName.trim()) return;
    saveDevice.mutate();
  };

  const error = (saveDevice.error ?? importLib.error ?? syncMtel.error ?? devices.error) as Error | null;
  const allRows = devices.data ?? [];
  const filteredRows =
    catFilter === "ALL"
      ? allRows
      : allRows.filter((d) => (d.category || "GENERAL").toUpperCase().includes(catFilter));

  return (
    <div className="analysis-workspace">
      <section className="sheet-pane" aria-busy={devices.isLoading}>
        <div className="pane-head">
          <div className="row gap-sm wrap-gap">
            <h2>Katalog Perangkat MTEL.lib</h2>
            <div className="seg-group" role="tablist" aria-label="Filter kategori perangkat">
              {["ALL", "TELKOMSEL", "XL", "IOH", "SMARTFREN", "SURGE", "MW", "MOUNTING"].map((cat) => (
                <button
                  key={cat}
                  type="button"
                  className={`seg-btn ${catFilter === cat ? "active" : ""}`}
                  onClick={() => setCatFilter(cat)}
                >
                  {cat === "ALL" ? `Semua (${allRows.length})` : cat}
                </button>
              ))}
            </div>
          </div>

          <div className="row gap-xs wrap-gap">
            <input
              type="search"
              id="library-search"
              aria-label="Search devices"
              placeholder="Cari nama perangkat / remark…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              style={{ height: 30, minWidth: 210, fontSize: 12 }}
            />
            <button
              type="button"
              className={`btn sm ${showEditor ? "active-pill" : "primary"}`}
              onClick={() => {
                setShowEditor((v) => !v);
                setShowImporter(false);
              }}
            >
              {showEditor ? "Tutup Form" : "+ Tambah / Update .lib"}
            </button>
            <button
              type="button"
              className={`btn quiet sm ${showImporter ? "active-pill" : ""}`}
              onClick={() => {
                setShowImporter((v) => !v);
                setShowEditor(false);
              }}
            >
              Import .lib
            </button>
            <button
              type="button"
              className="btn quiet sm"
              disabled={syncMtel.isPending}
              onClick={() => syncMtel.mutate()}
            >
              {syncMtel.isPending ? "Syncing…" : "Reload MTEL.lib"}
            </button>
            <a href={api.exportLibraryUrl} download="MTEL.lib" className="btn quiet sm">
              Export MTEL.lib
            </a>
          </div>
        </div>

        {showEditor && (
          <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)", background: "var(--surface-subtle)" }}>
            <div className="row between" style={{ marginBottom: 8 }}>
              <strong>Tambah atau Perbarui Perangkat (Otomatis Ditulis ke MTEL.lib)</strong>
              <span className="muted mono">EPA = Af × Ca (TIA-222-G Tabel 2-8)</span>
            </div>
            <form className="analysis-inline-form" onSubmit={onSubmit}>
              <label>
                <span>Kategori / Operator</span>
                <input
                  list="lib-categories"
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  required
                />
                <datalist id="lib-categories">
                  {CATEGORIES.map((c) => (
                    <option key={c} value={c} />
                  ))}
                </datalist>
              </label>
              <label>
                <span>Kode perangkat (.lib)</span>
                <input
                  value={deviceName}
                  onChange={(e) => setDeviceName(e.target.value)}
                  placeholder="cth. RF-1.549"
                  required
                />
              </label>
              <label>
                <span>Tipe bentuk</span>
                <select value={shapeType} onChange={(e) => setShapeType(e.target.value)}>
                  {SHAPES.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>Dimensi / Panjang (m)</span>
                <input
                  type="number"
                  step="0.001"
                  min="0.01"
                  value={dimM}
                  onChange={(e) => setDimM(e.target.value)}
                  required
                />
              </label>
              <label>
                <span>Massa (kg)</span>
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  value={massKg}
                  onChange={(e) => setMassKg(e.target.value)}
                  required
                />
              </label>
              <label>
                <span>Luas depan Af (m²)</span>
                <input
                  type="number"
                  step="0.0001"
                  min="0"
                  value={afM2}
                  onChange={(e) => setAfM2(e.target.value)}
                  required
                />
              </label>
              <label>
                <span>Luas samping Asf (m²)</span>
                <input
                  type="number"
                  step="0.0001"
                  min="0"
                  value={asfM2}
                  onChange={(e) => setAsfM2(e.target.value)}
                  required
                />
              </label>
              <label>
                <span>Keterangan ($ comment)</span>
                <input
                  value={remark}
                  onChange={(e) => setRemark(e.target.value)}
                  placeholder="cth. HUAWEI AAU"
                />
              </label>
              <button type="submit" className="btn primary" disabled={saveDevice.isPending}>
                {saveDevice.isPending ? "Menyimpan…" : "Simpan ke MTEL.lib"}
              </button>
            </form>
          </div>
        )}

        {showImporter && (
          <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)", background: "var(--surface-subtle)" }}>
            <FileDrop
              accept=".lib,.txt"
              label="Tarik berkas ANCILLARY.lib / MTEL.lib ke sini atau klik untuk mengimpor"
              hint="Menggabungkan daftar perangkat ke katalog aktif dan menghitung ulang EPA = Af × Ca."
              busy={importLib.isPending}
              busyLabel="Mengimpor .lib…"
              onFile={(f) => {
                setNotice(null);
                importLib.mutate(f);
              }}
            />
          </div>
        )}

        {notice && <div className="banner info" role="status" style={{ margin: 12 }}>{notice}</div>}
        {error && <div className="banner error" role="alert" style={{ margin: 12 }}>{error.message}</div>}

        <div className="sr-legend-bar mono">
          <span>Menampilkan <strong>{filteredRows.length}</strong> dari {allRows.length} perangkat di <code>MTEL.lib</code></span>
          <span>Klik <strong>Edit</strong> pada baris untuk memuat spesifikasi ke form pembaruan</span>
        </div>

        {devices.isLoading ? (
          <div className="skeleton" style={{ margin: 16 }} />
        ) : !filteredRows.length ? (
          <p className="empty">
            {q || catFilter !== "ALL"
              ? "Tidak ada perangkat yang cocok dengan filter."
              : "Katalog kosong. Klik Reload MTEL.lib atau impor berkas .lib."}
          </p>
        ) : (
          <div className="table-wrap" style={{ maxHeight: 620, overflowY: "auto" }}>
            <table>
              <thead>
                <tr>
                  <th>Kategori</th>
                  <th>Kode Perangkat</th>
                  <th>Bentuk</th>
                  <th className="num">Dimensi (m)</th>
                  <th className="num">Massa (kg)</th>
                  <th className="num">Af (m²)</th>
                  <th className="num">Asf (m²)</th>
                  <th className="num">Ca</th>
                  <th className="num">EPA (m²)</th>
                  <th>Keterangan</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((d) => (
                  <tr key={d.device_id}>
                    <td><span className="badge face-pill">{d.category}</span></td>
                    <td className="mono"><strong>{d.device_name}</strong></td>
                    <td className="mono">{d.shape_type}</td>
                    <td className="num mono">{d.dim_m.toFixed(2)}</td>
                    <td className="num mono">{d.mass_kg.toFixed(1)}</td>
                    <td className="num mono">{d.af_m2.toFixed(3)}</td>
                    <td className="num mono">{d.asf_m2.toFixed(3)}</td>
                    <td className="num mono">{d.ca_factor.toFixed(2)}</td>
                    <td className="num mono"><strong>{d.epa_m2.toFixed(3)}</strong></td>
                    <td className="muted">{d.remark || "—"}</td>
                    <td className="num">
                      <button
                        type="button"
                        className="btn quiet"
                        onClick={() => loadIntoForm(d)}
                        style={{ marginRight: 6 }}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="btn quiet danger"
                        onClick={() => removeDevice.mutate(d.device_name)}
                      >
                        Hapus
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
