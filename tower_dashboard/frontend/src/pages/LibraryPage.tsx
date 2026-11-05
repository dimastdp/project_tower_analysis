import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useSite } from "../SiteContext";
import FileDrop from "../components/FileDrop";
import { useToast } from "../components/Toast";
import type { LibraryDevice, SiteDevice } from "../types";

const SHAPES = ["BOX", "CYL", "SH1", "SHIELDED", "GRID", "UNITY"];
const CATEGORIES = ["TELKOMSEL", "IOH", "XL", "SMARTFREN", "SURGE", "MW DISHES", "MOUNTING", "GENERAL"];

export default function LibraryPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const { site } = useSite();

  // Scope Tab: "PROJECT" (devices in active project) vs "MASTER" (all devices in MTEL.lib)
  const [scopeTab, setScopeTab] = useState<"PROJECT" | "MASTER">("PROJECT");
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
  const siteDevices = useQuery({
    queryKey: ["inventory", site],
    queryFn: () => api.listSiteDevices(site!),
    enabled: !!site,
  });

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["library"] });
    qc.invalidateQueries({ queryKey: ["library-names"] });
    qc.invalidateQueries({ queryKey: ["inventory"] });
  };

  const importLib = useMutation({
    mutationFn: api.importLibrary,
    onSuccess: (r) => {
      const msg = `${r.imported} perangkat diimpor ke Master .lib.`;
      setNotice(msg);
      toast(msg);
      invalidateAll();
    },
  });

  const syncMtel = useMutation({
    mutationFn: api.syncMtelLibrary,
    onSuccess: (r) => {
      const msg = `Sinkronisasi ${r.imported} perangkat dari ${r.source}.`;
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
      const msg = `Tersimpan ${saved.device_name} (EPA ${saved.epa_m2.toFixed(3)} m²) ke Master MTEL.lib`;
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
      toast(`Dihapus ${name} dari Master .lib`);
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

  const loadProjectDeviceIntoForm = (d: SiteDevice) => {
    const h = d.dim_m ?? d.length_m ?? 1.5;
    const w = d.width_m ?? 0.35;
    const dep = d.depth_m ?? 0.18;
    setCategory(d.tenant || "PROJECT");
    setDeviceName(d.device_name);
    setShapeType(d.shape_type || "BOX");
    setDimM(h.toFixed(3));
    setMassKg((d.mass_kg ?? 22.0).toFixed(1));
    setAfM2((d.af_m2 ?? h * w).toFixed(4));
    setAsfM2((d.asf_m2 ?? h * dep).toFixed(4));
    setRemark(`Project ${site} (${d.status})`);
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
  const projectRowsRaw = siteDevices.data ?? [];

  // Aggregate unique project devices with total qty, elevations, and tenants
  const projectDeviceMap = new Map<
    string,
    {
      sample: SiteDevice;
      totalQty: number;
      tenants: Set<string>;
      statuses: Set<string>;
      elevations: number[];
    }
  >();

  for (const pd of projectRowsRaw) {
    const existing = projectDeviceMap.get(pd.device_name);
    if (existing) {
      existing.totalQty += pd.qty;
      existing.tenants.add(pd.tenant);
      existing.statuses.add(pd.status);
      if (!existing.elevations.includes(pd.elev_z_m)) {
        existing.elevations.push(pd.elev_z_m);
      }
    } else {
      projectDeviceMap.set(pd.device_name, {
        sample: pd,
        totalQty: pd.qty,
        tenants: new Set([pd.tenant]),
        statuses: new Set([pd.status]),
        elevations: [pd.elev_z_m],
      });
    }
  }

  const projectUniqueList = Array.from(projectDeviceMap.values()).filter((item) => {
    if (!q.trim()) return true;
    const ql = q.toLowerCase();
    return (
      item.sample.device_name.toLowerCase().includes(ql) ||
      Array.from(item.tenants).some((t) => t.toLowerCase().includes(ql))
    );
  });

  const projectInLibCount = Array.from(projectDeviceMap.values()).filter((i) => i.sample.in_library).length;
  const projectMissingCount = projectDeviceMap.size - projectInLibCount;

  const filteredMasterRows =
    catFilter === "ALL"
      ? allRows
      : allRows.filter((d) => (d.category || "GENERAL").toUpperCase().includes(catFilter));

  return (
    <div className="analysis-workspace">
      <section className="sheet-pane" aria-busy={devices.isLoading || siteDevices.isLoading}>
        {/* Top Header: Separated Scope Tabs (Project Devices vs Master Library .lib) */}
        <div className="pane-head" style={{ flexWrap: "wrap", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <h2 style={{ margin: 0 }}>Manajemen Perangkat &amp; Katalog .lib</h2>

            <div className="segmented" role="tablist" aria-label="Pilih cakupan katalog .lib">
              <button
                type="button"
                role="tab"
                aria-selected={scopeTab === "PROJECT"}
                className={scopeTab === "PROJECT" ? "active" : ""}
                onClick={() => setScopeTab("PROJECT")}
              >
                Perangkat Project ({site ?? "Site"}) · {projectDeviceMap.size} Tipe
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={scopeTab === "MASTER"}
                className={scopeTab === "MASTER" ? "active" : ""}
                onClick={() => setScopeTab("MASTER")}
              >
                Master Katalog MTEL.lib · {allRows.length} Item
              </button>
            </div>
          </div>

          <div className="row gap-xs wrap-gap" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input
              type="search"
              id="library-search"
              aria-label="Cari perangkat"
              placeholder="Cari kode perangkat / tenant…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              style={{ height: 30, minWidth: 210, fontSize: 12 }}
            />
            <button
              type="button"
              className={`btn sm ${showEditor ? "tinted" : "primary"}`}
              onClick={() => {
                setShowEditor((v) => !v);
                setShowImporter(false);
              }}
            >
              {showEditor ? "Tutup Form" : "+ Tambah / Update .lib"}
            </button>
            <button
              type="button"
              className="btn secondary sm"
              onClick={() => {
                setShowImporter((v) => !v);
                setShowEditor(false);
              }}
            >
              Import .lib
            </button>
            {site && (
              <a
                href={api.exportProjectLibUrl(site)}
                download={`${site}_PROJECT.lib`}
                className="btn tinted sm"
                title="Unduh file .lib khusus berisi perangkat pada project ini saja"
              >
                Export Project .lib ({site})
              </a>
            )}
            <a
              href={api.exportLibraryUrl}
              download="MTEL.lib"
              className="btn secondary sm"
              title="Unduh seluruh database Master MTEL.lib"
            >
              Export Master MTEL.lib
            </a>
          </div>
        </div>

        {/* Sub-bar ringkasan pemisahan Project vs Master Library */}
        <div
          style={{
            padding: "10px 16px",
            background: "var(--surface-2)",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            flexWrap: "wrap",
            fontSize: 12,
          }}
        >
          {scopeTab === "PROJECT" ? (
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <span>
                Cakupan: <strong>Perangkat Project Aktif ({site ?? "—"})</strong>
              </span>
              <span className="badge ok">{projectInLibCount} Terdaftar di Master .lib</span>
              {projectMissingCount > 0 ? (
                <span className="badge warn">
                  {projectMissingCount} Belum di Master .lib (Menggunakan Pendekatan Dimensi)
                </span>
              ) : (
                <span className="badge info">100% Comply dengan Master .lib</span>
              )}
            </div>
          ) : (
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span>Filter Kategori Master .lib:</span>
              {["ALL", "TELKOMSEL", "XL", "IOH", "SMARTFREN", "SURGE", "MW", "MOUNTING"].map((cat) => (
                <button
                  key={cat}
                  type="button"
                  className={`filter-pill ${catFilter === cat ? "active" : ""}`}
                  onClick={() => setCatFilter(cat)}
                >
                  {cat === "ALL" ? `Semua (${allRows.length})` : cat}
                </button>
              ))}
            </div>
          )}

          <span className="mono" style={{ color: "var(--muted)", fontSize: 11.5 }}>
            Dimensi 3D: Tinggi = Dim · Lebar = Af/Dim · Tebal = Asf/Dim · EPA = Af × Ca
          </span>
        </div>

        {showEditor && (
          <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)", background: "var(--surface-2)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
              <strong>Tambah / Sinkronkan Spesifikasi Perangkat ke Master MTEL.lib</strong>
              <span className="mono" style={{ color: "var(--muted)" }}>EPA = Af × Ca (TIA-222-G Tabel 2-8)</span>
            </div>
            <form className="form-grid" onSubmit={onSubmit}>
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
                <span>Dimensi / Tinggi (m)</span>
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
              <div style={{ display: "flex", alignItems: "flex-end" }}>
                <button type="submit" className="btn primary" disabled={saveDevice.isPending}>
                  {saveDevice.isPending ? "Menyimpan…" : "Simpan ke Master .lib"}
                </button>
              </div>
            </form>
          </div>
        )}

        {showImporter && (
          <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)", background: "var(--surface-2)" }}>
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

        {/* TAB 1: PROJECT DEVICES TABLE */}
        {scopeTab === "PROJECT" ? (
          !projectUniqueList.length ? (
            <div style={{ padding: 28, textAlign: "center", color: "var(--muted)" }}>
              Belum ada perangkat pada project <strong>{site ?? "ini"}</strong>. Tambahkan perangkat di tab{" "}
              <strong>Inventori</strong> atau beralih ke tab <strong>Master Katalog MTEL.lib</strong>.
            </div>
          ) : (
            <div className="table-scroll" style={{ maxHeight: 620 }}>
              <table>
                <thead>
                  <tr>
                    <th>Status .lib</th>
                    <th>Kode Perangkat (Project)</th>
                    <th>Tenant &amp; Status</th>
                    <th>Bentuk 3D</th>
                    <th className="num">Dimensi Fisik T × L × D (m)</th>
                    <th className="num">Massa (kg)</th>
                    <th className="num">Af (m²)</th>
                    <th className="num">Asf (m²)</th>
                    <th className="num">EPA (m²)</th>
                    <th className="num">Total Qty</th>
                    <th>Elevasi (m)</th>
                    <th className="num">Aksi</th>
                  </tr>
                </thead>
                <tbody>
                  {projectUniqueList.map(({ sample: d, totalQty, tenants, statuses, elevations }) => {
                    const h = d.length_m ?? d.dim_m ?? 0.8;
                    const w = d.width_m ?? 0.35;
                    const dep = d.depth_m ?? 0.18;
                    const af = d.af_m2 ?? h * w;
                    const asf = d.asf_m2 ?? h * dep;
                    return (
                      <tr key={d.device_name}>
                        <td>
                          {d.in_library ? (
                            <span className="badge ok">Di Master .lib</span>
                          ) : (
                            <span className="badge warn">Auto-Approach</span>
                          )}
                        </td>
                        <td className="mono">
                          <strong>{d.device_name}</strong>
                        </td>
                        <td>
                          <span className="badge info" style={{ marginRight: 4 }}>
                            {Array.from(tenants).join(", ")}
                          </span>
                          <span className={`badge ${statuses.has("PROPOSED") ? "proposed" : "existing"}`}>
                            {Array.from(statuses).join("/")}
                          </span>
                        </td>
                        <td className="mono">{d.shape_type ?? "BOX"}</td>
                        <td className="num mono">
                          <strong>
                            {h.toFixed(2)} × {w.toFixed(2)} × {dep.toFixed(2)}
                          </strong>
                        </td>
                        <td className="num mono">{(d.mass_kg ?? 20.0).toFixed(1)}</td>
                        <td className="num mono">{af.toFixed(3)}</td>
                        <td className="num mono">{asf.toFixed(3)}</td>
                        <td className="num mono">
                          <strong>{(d.epa_m2 ?? af * 1.2).toFixed(3)}</strong>
                        </td>
                        <td className="num mono">
                          <strong>{totalQty}</strong>
                        </td>
                        <td className="mono">
                          {elevations
                            .sort((a, b) => b - a)
                            .map((z) => `${z.toFixed(1)}m`)
                            .join(", ")}
                        </td>
                        <td className="num">
                          <button
                            type="button"
                            className={`btn sm ${d.in_library ? "secondary" : "primary"}`}
                            onClick={() => loadProjectDeviceIntoForm(d)}
                          >
                            {d.in_library ? "Edit Spesifikasi" : "+ Simpan ke .lib"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )
        ) : (
          /* TAB 2: MASTER LIBRARY TABLE */
          <div className="table-scroll" style={{ maxHeight: 620 }}>
            <table>
              <thead>
                <tr>
                  <th>Kategori</th>
                  <th>Kode Perangkat</th>
                  <th>Status Project</th>
                  <th>Bentuk</th>
                  <th className="num">Dimensi T × L × D (m)</th>
                  <th className="num">Massa (kg)</th>
                  <th className="num">Af (m²)</th>
                  <th className="num">Asf (m²)</th>
                  <th className="num">Ca</th>
                  <th className="num">EPA (m²)</th>
                  <th>Keterangan</th>
                  <th className="num">Aksi</th>
                </tr>
              </thead>
              <tbody>
                {filteredMasterRows.map((d) => {
                  const usedInProject = projectDeviceMap.has(d.device_name);
                  const w = d.dim_m > 0 ? d.af_m2 / d.dim_m : 0.35;
                  const dep = d.dim_m > 0 ? d.asf_m2 / d.dim_m : 0.18;
                  return (
                    <tr key={d.device_id} className={usedInProject ? "selected" : ""}>
                      <td>
                        <span className="badge info">{d.category}</span>
                      </td>
                      <td className="mono">
                        <strong>{d.device_name}</strong>
                      </td>
                      <td>
                        {usedInProject ? (
                          <span className="badge ok">Dipakai di {site}</span>
                        ) : (
                          <span style={{ color: "var(--muted)", fontSize: 11.5 }}>Cadangan Katalog</span>
                        )}
                      </td>
                      <td className="mono">{d.shape_type}</td>
                      <td className="num mono">
                        {d.dim_m.toFixed(2)} × {w.toFixed(2)} × {dep.toFixed(2)}
                      </td>
                      <td className="num mono">{d.mass_kg.toFixed(1)}</td>
                      <td className="num mono">{d.af_m2.toFixed(3)}</td>
                      <td className="num mono">{d.asf_m2.toFixed(3)}</td>
                      <td className="num mono">{d.ca_factor.toFixed(2)}</td>
                      <td className="num mono">
                        <strong>{d.epa_m2.toFixed(3)}</strong>
                      </td>
                      <td style={{ color: "var(--ink-secondary)" }}>{d.remark || "—"}</td>
                      <td className="num" style={{ whiteSpace: "nowrap" }}>
                        <button
                          type="button"
                          className="btn secondary sm"
                          onClick={() => loadIntoForm(d)}
                          style={{ marginRight: 6 }}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          className="btn danger sm"
                          onClick={() => removeDevice.mutate(d.device_name)}
                        >
                          Hapus
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
