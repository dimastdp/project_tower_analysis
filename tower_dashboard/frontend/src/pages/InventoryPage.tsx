import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useSite } from "../SiteContext";
import ElevationStrip from "../components/ElevationStrip";
import { useToast } from "../components/Toast";
import type { DeviceStatus, SiteDevice, TowerFace } from "../types";

const TENANTS = ["TELKOMSEL", "IOH", "XL", "XLSMART", "SMARTFREN", "SURGE"];

export default function InventoryPage() {
  const qc = useQueryClient();
  const { site } = useSite();
  const toast = useToast();

  const [status, setStatus] = useState<DeviceStatus>("EXISTING");
  const [tenant, setTenant] = useState(TENANTS[0]);
  const [deviceName, setDeviceName] = useState("");
  const [mounting, setMounting] = useState("LEG A");
  const [elev, setElev] = useState("20");
  const [qty, setQty] = useState("1");
  const [faceFilter, setFaceFilter] = useState<TowerFace | "ALL">("ALL");
  const [statusFilter, setStatusFilter] = useState<"ALL" | "EXISTING" | "PROPOSED" | "MISSING">("ALL");
  const [searchQ, setSearchQ] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);

  // Quick-register missing device into MTEL.lib
  const [regDev, setRegDev] = useState<SiteDevice | null>(null);
  const [regShape, setRegShape] = useState("BOX");
  const [regDim, setRegDim] = useState("1.50");
  const [regMass, setRegMass] = useState("25.0");
  const [regAf, setRegAf] = useState("0.45");
  const [regAsf, setRegAsf] = useState("0.20");

  const towers = useQuery({ queryKey: ["towers"], queryFn: api.listTowers });
  const activeTower = towers.data?.find((t) => t.site_name === site);

  const inventory = useQuery({
    queryKey: ["inventory", site],
    queryFn: () => api.listSiteDevices(site!),
    enabled: !!site,
  });
  const names = useQuery({ queryKey: ["library-names"], queryFn: () => api.listDevices("") });

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ["inventory", site] });
    qc.invalidateQueries({ queryKey: ["site-devices", site] });
    qc.invalidateQueries({ queryKey: ["library"] });
    qc.invalidateQueries({ queryKey: ["library-names"] });
  };

  const add = useMutation({
    mutationFn: () =>
      api.addSiteDevice(site!, {
        status,
        tenant,
        device_name: deviceName.trim(),
        mounting_name: mounting.trim() || null,
        elev_z_m: Number(elev),
        qty: Number(qty),
      }),
    onSuccess: () => {
      toast(`Added ${deviceName.trim()} (${status}) to ${site}`);
      setDeviceName("");
      invalidateAll();
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.deleteSiteDevice(site!, id),
    onSuccess: () => {
      toast("Removed device from inventory");
      invalidateAll();
    },
  });

  const registerInLib = useMutation({
    mutationFn: () =>
      api.upsertLibraryDevice({
        category: regDev?.tenant || "CUSTOM",
        device_name: regDev!.device_name,
        shape_type: regShape,
        dim_m: Number(regDim),
        mass_kg: Number(regMass),
        af_m2: Number(regAf),
        asf_m2: Number(regAsf),
        remark: `Added from ${site} inventory`,
      }),
    onSuccess: (saved) => {
      toast(`Registered ${saved.device_name} in MTEL.lib (EPA ${saved.epa_m2.toFixed(3)} m²)`);
      setRegDev(null);
      invalidateAll();
    },
  });

  const applySuggestion = useMutation({
    mutationFn: (args: { id: number; target: string; mode: "replace" | "clone_to_lib" }) =>
      api.applyDeviceSuggestion(site!, args.id, args.target, args.mode),
    onSuccess: (res) => {
      if (res.mode === "clone_to_lib") {
        toast(`Terdaftar "${res.device_name}" ke MTEL.lib berdasarkan profil ${res.based_on}`);
      } else {
        toast(`Diganti "${res.old_name}" → "${res.new_name}" pada site ${site}`);
      }
      invalidateAll();
    },
  });

  if (!site) {
    return (
      <div className="empty card">
        <p>Select or upload a tower first.</p>
        <Link to="/towers" className="btn primary">Go to Towers</Link>
      </div>
    );
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!deviceName.trim()) return;
    add.mutate();
  };
  const error = (add.error ?? remove.error ?? registerInLib.error ?? applySuggestion.error ?? inventory.error) as Error | null;
  const rows = inventory.data ?? [];
  const filteredRows = rows.filter((r) => {
    if (faceFilter !== "ALL" && (r.face ?? "A") !== faceFilter) return false;
    if (statusFilter === "EXISTING" && r.status !== "EXISTING") return false;
    if (statusFilter === "PROPOSED" && r.status !== "PROPOSED") return false;
    if (statusFilter === "MISSING" && r.in_library) return false;
    if (searchQ.trim()) {
      const q = searchQ.toLowerCase();
      return (
        r.device_name.toLowerCase().includes(q) ||
        r.tenant.toLowerCase().includes(q) ||
        (r.mounting_name ?? "").toLowerCase().includes(q)
      );
    }
    return true;
  });
  const totalEpa = rows.reduce((acc, r) => acc + (r.epa_m2 ?? 0) * r.qty, 0);
  const existingCount = rows.filter((r) => r.status === "EXISTING").length;
  const proposedCount = rows.filter((r) => r.status === "PROPOSED").length;
  const missingCount = rows.filter((r) => !r.in_library).length;

  // Deduplicate missing devices by device_name for the Smart Suggestion banner
  const missingByName = new Map<string, SiteDevice>();
  for (const r of rows) {
    if (!r.in_library && !missingByName.has(r.device_name)) {
      missingByName.set(r.device_name, r);
    }
  }
  const missingDistinct = Array.from(missingByName.values());

  return (
    <div className="analysis-split">
      {/* LEFT PANE: 4-Sided Elevation Blueprint */}
      {activeTower && (
        <aside className="cad-pane">
          <div className="pane-head">
            <div>
              <h2>Potongan Elevasi 4 Sisi ({activeTower.site_name})</h2>
              <span className="muted" style={{ fontSize: 12 }}>
                Klik tab sisi atau potongan gambar untuk memfilter tabel perangkat
              </span>
            </div>
          </div>
          <div style={{ padding: "12px 14px" }}>
            <ElevationStrip
              heightM={activeTower.height_m}
              topWidthM={activeTower.top_width_m}
              baseWidthM={activeTower.bot_width_m}
              devices={rows}
              activeFace={faceFilter}
              onFaceChange={setFaceFilter}
            />
          </div>
        </aside>
      )}

      {/* RIGHT PANE: Clean Filterable Inventory Sheet */}
      <div className="stack" style={{ gap: 14 }}>
        {missingDistinct.length > 0 && (
          <section className="card suggest-banner" role="region" aria-label="Saran perangkat mirip di MTEL.lib">
            <div className="row between wrap-gap">
              <div>
                <h2 style={{ color: "var(--proposed)", margin: 0 }}>
                  {missingDistinct.length} Tipe Perangkat Belum Terdaftar di MTEL.lib
                </h2>
                <p className="muted" style={{ margin: "2px 0 0", fontSize: 12 }}>
                  Pilih kandidat terdekat di bawah ini untuk langsung mendaftarkan ke <code>MTEL.lib</code>:
                </p>
              </div>
              <span className="badge warn">Perlu Konfirmasi .lib</span>
            </div>

            <div className="suggest-list">
              {missingDistinct.map((m) => (
                <div key={m.device_name} className="suggest-item">
                  <div className="row between wrap-gap">
                    <div>
                      <span className="badge proposed">{m.status}</span>{" "}
                      <strong className="mono">{m.device_name}</strong>{" "}
                      <span className="muted">
                        ({m.tenant} · Elevasi {m.elev_z_m.toFixed(1)} m · Dimensi {(m.length_m ?? 0).toFixed(3)} m)
                      </span>
                    </div>
                    <button
                      type="button"
                      className="btn quiet sm"
                      onClick={() => {
                        setRegDev(m);
                        setRegDim(String(m.length_m ?? 1.5));
                      }}
                    >
                      Input Manual ke .lib
                    </button>
                  </div>

                  {m.suggestions && m.suggestions.length > 0 ? (
                    <div className="suggest-cards">
                      {m.suggestions.map((s) => (
                        <div key={s.device_name} className="suggest-chip">
                          <div className="row between">
                            <strong className="mono">{s.device_name}</strong>
                            <span className="badge existing">{s.similarity_pct}% mirip</span>
                          </div>
                          <div className="muted mono" style={{ fontSize: 11 }}>
                            {s.shape_type} · Dim {s.dim_m}m · {s.mass_kg}kg · EPA {s.epa_m2.toFixed(3)}m²
                          </div>
                          <div className="row gap-xs" style={{ marginTop: 4 }}>
                            <button
                              type="button"
                              className="btn primary sm"
                              disabled={applySuggestion.isPending}
                              onClick={() =>
                                applySuggestion.mutate({
                                  id: m.id,
                                  target: s.device_name,
                                  mode: "clone_to_lib",
                                })
                              }
                            >
                              + Simpan {m.device_name} ke .lib
                            </button>
                            <button
                              type="button"
                              className="btn quiet sm"
                              disabled={applySuggestion.isPending}
                              onClick={() =>
                                applySuggestion.mutate({
                                  id: m.id,
                                  target: s.device_name,
                                  mode: "replace",
                                })
                              }
                            >
                              Ganti ke {s.device_name}
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="muted">Tidak ada kandidat dekat. Gunakan tombol Input Manual ke .lib.</p>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {regDev && (
          <section className="card">
            <div className="row between">
              <h2>Daftarkan "{regDev.device_name}" ke MTEL.lib</h2>
              <button type="button" className="btn quiet" onClick={() => setRegDev(null)}>
                Tutup
              </button>
            </div>
            <form
              className="form-grid"
              onSubmit={(e) => {
                e.preventDefault();
                registerInLib.mutate();
              }}
            >
              <label>
                Shape
                <select value={regShape} onChange={(e) => setRegShape(e.target.value)}>
                  <option value="BOX">BOX</option>
                  <option value="CYL">CYL</option>
                  <option value="SH1">SH1</option>
                  <option value="SHIELDED">SHIELDED</option>
                </select>
              </label>
              <label>
                Dim (m)
                <input type="number" step="0.001" value={regDim} onChange={(e) => setRegDim(e.target.value)} required />
              </label>
              <label>
                Mass (kg)
                <input type="number" step="0.1" value={regMass} onChange={(e) => setRegMass(e.target.value)} required />
              </label>
              <label>
                Af (m²)
                <input type="number" step="0.001" value={regAf} onChange={(e) => setRegAf(e.target.value)} required />
              </label>
              <label>
                Asf (m²)
                <input type="number" step="0.001" value={regAsf} onChange={(e) => setRegAsf(e.target.value)} required />
              </label>
              <div className="form-actions">
                <button type="submit" className="btn primary" disabled={registerInLib.isPending}>
                  {registerInLib.isPending ? "Menyimpan…" : "Simpan ke MTEL.lib"}
                </button>
              </div>
            </form>
          </section>
        )}

        <section className="sheet-pane" aria-busy={inventory.isLoading}>
          <div className="pane-head">
            <div className="row gap-sm wrap-gap">
              <h2>Inventori Perangkat ({site})</h2>
              <div className="seg-group" role="tablist" aria-label="Filter status perangkat">
                <button
                  type="button"
                  className={`seg-btn ${statusFilter === "ALL" ? "active" : ""}`}
                  onClick={() => setStatusFilter("ALL")}
                >
                  Semua ({rows.length})
                </button>
                <button
                  type="button"
                  className={`seg-btn ${statusFilter === "EXISTING" ? "active" : ""}`}
                  onClick={() => setStatusFilter("EXISTING")}
                >
                  Existing ({existingCount})
                </button>
                <button
                  type="button"
                  className={`seg-btn ${statusFilter === "PROPOSED" ? "active" : ""}`}
                  onClick={() => setStatusFilter("PROPOSED")}
                >
                  Proposed ({proposedCount})
                </button>
                {missingCount > 0 && (
                  <button
                    type="button"
                    className={`seg-btn ${statusFilter === "MISSING" ? "active" : ""}`}
                    onClick={() => setStatusFilter("MISSING")}
                  >
                    Belum di .lib ({missingCount})
                  </button>
                )}
              </div>
            </div>

            <div className="row gap-xs wrap-gap">
              <input
                type="search"
                placeholder="Cari tenant / kode perangkat…"
                value={searchQ}
                onChange={(e) => setSearchQ(e.target.value)}
                style={{ height: 30, minWidth: 190, fontSize: 12 }}
              />
              <button
                type="button"
                className={`btn sm ${showAddForm ? "active-pill" : "primary"}`}
                onClick={() => setShowAddForm((v) => !v)}
              >
                {showAddForm ? "Tutup Form" : "+ Tambah Perangkat"}
              </button>
              <a href={api.exportLibraryUrl} download="MTEL.lib" className="btn quiet sm">
                Export MTEL.lib
              </a>
            </div>
          </div>

          {showAddForm && (
            <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)", background: "var(--surface-subtle)" }}>
              <form className="analysis-inline-form" onSubmit={onSubmit}>
                <label>
                  <span>Status</span>
                  <select value={status} onChange={(e) => setStatus(e.target.value as DeviceStatus)}>
                    <option value="EXISTING">EXISTING</option>
                    <option value="PROPOSED">PROPOSED</option>
                  </select>
                </label>
                <label>
                  <span>Tenant</span>
                  <select value={tenant} onChange={(e) => setTenant(e.target.value)}>
                    {TENANTS.map((t) => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Kode perangkat (.lib)</span>
                  <input
                    list="device-names"
                    value={deviceName}
                    onChange={(e) => setDeviceName(e.target.value)}
                    placeholder="cth. SEC-2.76"
                    required
                  />
                  <datalist id="device-names">
                    {names.data?.map((d) => (
                      <option key={d.device_id} value={d.device_name}>
                        {d.category} · EPA {d.epa_m2} m² · {d.mass_kg} kg
                      </option>
                    ))}
                  </datalist>
                </label>
                <label>
                  <span>Sisi / Leg</span>
                  <input
                    value={mounting}
                    onChange={(e) => setMounting(e.target.value)}
                    placeholder="LEG A / B / C / D"
                  />
                </label>
                <label>
                  <span>Elevasi Z (m)</span>
                  <input
                    type="number"
                    step="0.1"
                    min={0}
                    max={500}
                    value={elev}
                    onChange={(e) => setElev(e.target.value)}
                    required
                  />
                </label>
                <label>
                  <span>Qty</span>
                  <input
                    type="number"
                    min={1}
                    max={999}
                    value={qty}
                    onChange={(e) => setQty(e.target.value)}
                    required
                    style={{ width: 68, minWidth: 68 }}
                  />
                </label>
                <button type="submit" className="btn primary" disabled={add.isPending}>
                  {add.isPending ? "Menyimpan…" : "Simpan ke Site"}
                </button>
              </form>
            </div>
          )}

          {error && <div className="banner error" role="alert" style={{ margin: 12 }}>{error.message}</div>}

          <div className="sheet-body" style={{ padding: 0 }}>
            <div className="sr-legend-bar mono" style={{ background: "var(--surface)" }}>
              <span>Menampilkan <strong>{filteredRows.length}</strong> dari {rows.length} baris perangkat</span>
              <span>Filter Sisi: <strong>{faceFilter === "ALL" ? "Semua 4 Sisi (A/B/C/D)" : `Sisi ${faceFilter}`}</strong></span>
              <span>Total EPA Terdaftar: <strong>{totalEpa.toFixed(2)} m²</strong></span>
            </div>

            {inventory.isLoading ? (
              <div className="skeleton" style={{ margin: 16 }} />
            ) : !filteredRows.length ? (
              <p className="empty">Tidak ada perangkat yang cocok dengan filter saat ini.</p>
            ) : (
              <div className="table-wrap" style={{ maxHeight: 560, overflowY: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Status</th>
                      <th>Sisi</th>
                      <th>Tenant</th>
                      <th>Perangkat (.lib)</th>
                      <th>Dimensi P×L×T (m)</th>
                      <th className="num">Elevasi Z (m)</th>
                      <th className="num">Qty</th>
                      <th className="num">EPA (m²)</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {filteredRows.map((d) => (
                      <tr key={d.id}>
                        <td>
                          <span className={`badge ${d.status.toLowerCase()}`}>{d.status}</span>
                        </td>
                        <td>
                          <button
                            type="button"
                            className="badge face-pill"
                            onClick={() => setFaceFilter(d.face ?? "A")}
                            title={d.mounting_name ?? ""}
                          >
                            Sisi {d.face ?? "A"}
                          </button>
                        </td>
                        <td>{d.tenant}</td>
                        <td className="mono">
                          <strong>{d.device_name}</strong>{" "}
                          {!d.in_library && (
                            <button
                              type="button"
                              className="badge warn"
                              style={{ border: 0, cursor: "pointer" }}
                              title={
                                d.suggestions?.[0]
                                  ? `Klik untuk simpan ke .lib dari referensi ${d.suggestions[0].device_name} (${d.suggestions[0].similarity_pct}%)`
                                  : "Belum ada di .lib"
                              }
                              onClick={() => {
                                if (d.suggestions?.[0]) {
                                  applySuggestion.mutate({
                                    id: d.id,
                                    target: d.suggestions[0].device_name,
                                    mode: "clone_to_lib",
                                  });
                                } else {
                                  setRegDev(d);
                                }
                              }}
                            >
                              + Simpan .lib ({d.suggestions?.[0]?.similarity_pct ?? "?"}%)
                            </button>
                          )}
                        </td>
                        <td className="mono muted">
                          {(d.length_m ?? 0).toFixed(2)}×{(d.width_m ?? 0).toFixed(2)}×{(d.depth_m ?? 0).toFixed(2)}
                        </td>
                        <td className="num mono">{d.elev_z_m.toFixed(1)}</td>
                        <td className="num mono">{d.qty}</td>
                        <td className="num mono">{d.epa_m2 !== null ? d.epa_m2.toFixed(3) : "—"}</td>
                        <td className="num">
                          <button
                            type="button"
                            className="btn quiet danger"
                            onClick={() => remove.mutate(d.id)}
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
          </div>
        </section>
      </div>
    </div>
  );
}
