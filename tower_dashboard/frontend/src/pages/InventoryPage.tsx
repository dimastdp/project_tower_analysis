import { FormEvent, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { useSite } from "../SiteContext";
import type {
  DeviceStatus,
  SiteDevice,
  TowerFace,
} from "../types";
import ElevationStrip from "../components/ElevationStrip";

function inferDeviceFace(d: SiteDevice, idx: number): TowerFace {
  if (d.face && ["A", "B", "C", "D"].includes(d.face)) return d.face;
  const txt = `${d.tenant} ${d.device_name} ${d.mounting_name ?? ""}`.toUpperCase();
  if (/\bFACE[\s_-]*A\b|\bSEC[\s_-]*1\b|\bS1\b|\bLEG[\s_-]*A\b/.test(txt)) return "A";
  if (/\bFACE[\s_-]*B\b|\bSEC[\s_-]*2\b|\bS2\b|\bLEG[\s_-]*B\b/.test(txt)) return "B";
  if (/\bFACE[\s_-]*C\b|\bSEC[\s_-]*3\b|\bS3\b|\bLEG[\s_-]*C\b/.test(txt)) return "C";
  if (/\bFACE[\s_-]*D\b|\bSEC[\s_-]*4\b|\bS4\b|\bLEG[\s_-]*D\b/.test(txt)) return "D";
  const faces: TowerFace[] = ["A", "B", "C", "D"];
  return faces[idx % 4];
}

const FACE_META: Record<TowerFace, { title: string; az: string }> = {
  A: { title: "Face A", az: "0° (Utara)" },
  B: { title: "Face B", az: "90° (Timur)" },
  C: { title: "Face C", az: "180° (Selatan)" },
  D: { title: "Face D", az: "270° (Barat)" },
};

export default function InventoryPage() {
  const qc = useQueryClient();
  const { site: selectedSite, setSite: onSelectSite } = useSite();

  const towersQuery = useQuery({ queryKey: ["towers"], queryFn: api.listTowers });
  const towers = towersQuery.data ?? [];

  const catalogQuery = useQuery({
    queryKey: ["library", ""],
    queryFn: () => api.listDevices(""),
  });
  const catalog = catalogQuery.data ?? [];

  const [items, setItems] = useState<SiteDevice[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busyMsg, setBusyMsg] = useState<string | null>(null);

  // Finder folder navigation state
  const [statusFilter, setStatusFilter] = useState<"ALL" | DeviceStatus | "MISSING">("ALL");
  const [faceFilter, setFaceFilter] = useState<"ALL" | TowerFace>("ALL");
  const [tenantFilter, setTenantFilter] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);

  // Add device form state
  const [status, setStatus] = useState<DeviceStatus>("EXISTING");
  const [tenant, setTenant] = useState("TSEL");
  const [deviceName, setDeviceName] = useState("");
  const [mountingName, setMountingName] = useState("SM-1");
  const [elevZ, setElevZ] = useState("65");
  const [qty, setQty] = useState("1");

  const reload = () => {
    if (!selectedSite) {
      setItems([]);
      return;
    }
    setErr(null);
    api
      .listSiteDevices(selectedSite)
      .then((list) => {
        setItems(list);
        qc.invalidateQueries({ queryKey: ["inventory", selectedSite] });
      })
      .catch((e: ApiError) => setErr(e.message));
  };

  useEffect(reload, [selectedSite]);

  const activeTower = useMemo(
    () => towers.find((t) => t.site_name === selectedSite) ?? null,
    [towers, selectedSite]
  );

  const towerHeight = useMemo(() => {
    if (activeTower && activeTower.height_m > 1) return Math.ceil(activeTower.height_m);
    const maxDev = items.reduce((m, d) => Math.max(m, d.elev_z_m), 0);
    return Math.max(40, Math.ceil((maxDev + 5) / 5) * 5);
  }, [activeTower, items]);

  const itemsWithFace = useMemo(
    () => items.map((d, i) => ({ ...d, face: inferDeviceFace(d, i) })),
    [items]
  );

  const missingDevices = useMemo(
    () => itemsWithFace.filter((d) => !d.in_library),
    [itemsWithFace]
  );

  const tenantsList = useMemo(() => {
    const map = new Map<string, number>();
    for (const d of itemsWithFace) {
      const t = (d.tenant || "UNKNOWN").toUpperCase();
      map.set(t, (map.get(t) ?? 0) + d.qty);
    }
    return Array.from(map.entries()).sort((a, b) => b[1] - a[1]);
  }, [itemsWithFace]);

  const filteredItems = useMemo(() => {
    return itemsWithFace.filter((d) => {
      if (statusFilter === "EXISTING" && d.status !== "EXISTING") return false;
      if (statusFilter === "PROPOSED" && d.status !== "PROPOSED") return false;
      if (statusFilter === "MISSING" && d.in_library) return false;
      if (faceFilter !== "ALL" && d.face !== faceFilter) return false;
      if (tenantFilter !== "ALL" && (d.tenant || "").toUpperCase() !== tenantFilter) return false;
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const hay = `${d.tenant} ${d.device_name} ${d.mounting_name ?? ""} ${d.face}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [itemsWithFace, statusFilter, faceFilter, tenantFilter, searchQuery]);

  const summaryMetrics = useMemo(() => {
    let totalUnits = 0;
    let totalEpa = 0;
    let totalMass = 0;
    let existingCount = 0;
    let proposedCount = 0;
    for (const d of itemsWithFace) {
      totalUnits += d.qty;
      if (d.status === "EXISTING") existingCount += d.qty;
      else proposedCount += d.qty;
      if (d.epa_m2 != null) totalEpa += d.epa_m2 * d.qty;
      if (d.mass_kg != null) totalMass += d.mass_kg * d.qty;
    }
    return { totalUnits, totalEpa, totalMass, existingCount, proposedCount };
  }, [itemsWithFace]);

  const mountingDevices = useMemo(
    () => catalog.filter((c) => c.category === "MOUNTING"),
    [catalog]
  );

  const handleAdd = async (e: FormEvent) => {
    e.preventDefault();
    if (!selectedSite) return;
    setErr(null);
    try {
      await api.addSiteDevice(selectedSite, {
        status,
        tenant: tenant.trim(),
        device_name: deviceName.trim(),
        mounting_name: mountingName.trim() || null,
        elev_z_m: Number(elevZ),
        qty: Number(qty),
      });
      setDeviceName("");
      reload();
    } catch (ex) {
      setErr(ex instanceof ApiError ? ex.message : String(ex));
    }
  };

  const handleDelete = async (id: number) => {
    if (!selectedSite) return;
    setErr(null);
    try {
      await api.deleteSiteDevice(selectedSite, id);
      reload();
    } catch (ex) {
      setErr(ex instanceof ApiError ? ex.message : String(ex));
    }
  };

  const handleApplySuggestion = async (
    devId: number,
    targetDeviceName: string,
    mode: "replace" | "clone_to_lib"
  ) => {
    if (!selectedSite) return;
    setErr(null);
    setBusyMsg("Menyelaraskan referensi perangkat ke MTEL.lib...");
    try {
      await api.applyDeviceSuggestion(selectedSite, devId, targetDeviceName, mode);
      reload();
      qc.invalidateQueries({ queryKey: ["library"] });
    } catch (ex) {
      setErr(ex instanceof ApiError ? ex.message : String(ex));
    } finally {
      setBusyMsg(null);
    }
  };

  const activeFolderLabel = useMemo(() => {
    const parts: string[] = [];
    if (statusFilter === "ALL") parts.push("All_Inventory.twr");
    else if (statusFilter === "EXISTING") parts.push("Status/EXISTING.twr");
    else if (statusFilter === "PROPOSED") parts.push("Status/PROPOSED.twr");
    else if (statusFilter === "MISSING") parts.push("Status/Unmapped_Lib.err");
    if (faceFilter !== "ALL") parts.push(`Face_${faceFilter}`);
    if (tenantFilter !== "ALL") parts.push(`Tenant_${tenantFilter}`);
    return parts.join(" › ");
  }, [statusFilter, faceFilter, tenantFilter]);

  return (
    <div className="finder-shell">
      {/* Top macOS Finder Breadcrumb & Toolbar */}
      <div className="finder-breadcrumb-bar">
        <div className="finder-breadcrumb-path">
          <span>Workspace</span>
          <span className="finder-breadcrumb-sep">›</span>
          <span>Ancillary Inventory</span>
          {selectedSite && (
            <>
              <span className="finder-breadcrumb-sep">›</span>
              <strong>{selectedSite}</strong>
              <span className="finder-breadcrumb-sep">›</span>
              <span className="mono" style={{ fontSize: 11.5, color: "var(--primary)" }}>
                {activeFolderLabel}
              </span>
            </>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <select
            aria-label="Pilih site"
            value={selectedSite ?? ""}
            onChange={(e) => onSelectSite(e.target.value)}
            style={{ height: 30, fontSize: 12 }}
          >
            {towers.length === 0 && <option value="">-- belum ada site --</option>}
            {towers.map((t) => (
              <option key={t.site_name} value={t.site_name}>
                {t.site_name}
              </option>
            ))}
          </select>

          <button
            type="button"
            className="btn sm"
            onClick={() => setShowAddForm((v) => !v)}
          >
            {showAddForm ? "Tutup Form" : "+ Tambah Perangkat"}
          </button>

          {selectedSite && (
            <a
              href={api.exportProjectLibUrl(selectedSite)}
              download
              className="btn-link tinted sm"
            >
              Export Project .lib
            </a>
          )}
        </div>
      </div>

      {err && <div className="alert error">{err}</div>}
      {busyMsg && <div className="alert">{busyMsg}</div>}

      {/* 3-Pane macOS Finder Layout */}
      <div className="finder-3pane">
        {/* LEFT PANE: Hierarchical Inventory Folder Tree */}
        <aside className="finder-tree-pane">
          <div className="finder-pane-header">
            <div className="finder-traffic-dots">
              <span className="finder-traffic-dot red" />
              <span className="finder-traffic-dot amber" />
              <span className="finder-traffic-dot green" />
            </div>
            <span className="finder-pane-title">Inventory Folders</span>
            <span className="badge">{items.length}</span>
          </div>

          <div className="finder-tree-scroll">
            {/* Search input */}
            <input
              type="search"
              placeholder="Filter kode antena / tenant..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{ width: "100%", height: 28, fontSize: 12 }}
            />

            {/* Folder Group 1: Status Hierarchy */}
            <div className="finder-section-group">
              <div className="finder-section-label">Status Folders (.twr)</div>
              <button
                type="button"
                className={`finder-tree-folder ${
                  statusFilter === "ALL" && faceFilter === "ALL" && tenantFilter === "ALL"
                    ? "active"
                    : ""
                }`}
                onClick={() => {
                  setStatusFilter("ALL");
                  setFaceFilter("ALL");
                  setTenantFilter("ALL");
                }}
              >
                <div className="finder-item-main">
                  <span>📂</span>
                  <span className="finder-item-name">All_Devices.twr</span>
                </div>
                <span className="finder-item-meta">{summaryMetrics.totalUnits}u</span>
              </button>

              <button
                type="button"
                className={`finder-tree-item ${statusFilter === "EXISTING" ? "active" : ""}`}
                onClick={() => setStatusFilter("EXISTING")}
              >
                <div className="finder-item-main">
                  <span className="semantic-dot green" />
                  <span className="finder-item-name">EXISTING_Equipment</span>
                </div>
                <span className="finder-item-meta">{summaryMetrics.existingCount}u</span>
              </button>

              <button
                type="button"
                className={`finder-tree-item ${statusFilter === "PROPOSED" ? "active" : ""}`}
                onClick={() => setStatusFilter("PROPOSED")}
              >
                <div className="finder-item-main">
                  <span className="semantic-dot amber" />
                  <span className="finder-item-name">PROPOSED_Equipment</span>
                </div>
                <span className="finder-item-meta">{summaryMetrics.proposedCount}u</span>
              </button>

              {missingDevices.length > 0 && (
                <button
                  type="button"
                  className={`finder-tree-item ${statusFilter === "MISSING" ? "active" : ""}`}
                  onClick={() => setStatusFilter("MISSING")}
                >
                  <div className="finder-item-main">
                    <span className="semantic-dot red" />
                    <span className="finder-item-name">Missing_In_Lib.err</span>
                  </div>
                  <span className="finder-item-meta">{missingDevices.length}</span>
                </button>
              )}
            </div>

            {/* Folder Group 2: Tower Faces (A / B / C / D) */}
            <div className="finder-section-group">
              <div className="finder-section-label">Tower Sectors / Faces</div>
              {(["ALL", "A", "B", "C", "D"] as const).map((f) => {
                const count =
                  f === "ALL"
                    ? itemsWithFace.length
                    : itemsWithFace.filter((d) => d.face === f).length;
                return (
                  <button
                    key={f}
                    type="button"
                    className={`finder-tree-item ${faceFilter === f ? "active" : ""}`}
                    onClick={() => setFaceFilter(f)}
                  >
                    <div className="finder-item-main">
                      <span>{f === "ALL" ? "🧭" : "📡"}</span>
                      <span className="finder-item-name">
                        {f === "ALL" ? "Semua Face (A–D)" : `${FACE_META[f].title} · ${FACE_META[f].az}`}
                      </span>
                    </div>
                    <span className="finder-item-meta">{count}</span>
                  </button>
                );
              })}
            </div>

            {/* Folder Group 3: Operator / Tenant Directories */}
            <div className="finder-section-group">
              <div className="finder-section-label">Tenants / Operators</div>
              <button
                type="button"
                className={`finder-tree-item ${tenantFilter === "ALL" ? "active" : ""}`}
                onClick={() => setTenantFilter("ALL")}
              >
                <div className="finder-item-main">
                  <span>🏢</span>
                  <span className="finder-item-name">Semua Operator</span>
                </div>
                <span className="finder-item-meta">{tenantsList.length}</span>
              </button>
              {tenantsList.map(([tName, uCount]) => (
                <button
                  key={tName}
                  type="button"
                  className={`finder-tree-item ${tenantFilter === tName ? "active" : ""}`}
                  onClick={() => setTenantFilter(tName)}
                >
                  <div className="finder-item-main">
                    <span>📁</span>
                    <span className="finder-item-name">{tName}</span>
                  </div>
                  <span className="finder-item-meta">{uCount}u</span>
                </button>
              ))}
            </div>
          </div>
        </aside>

        {/* CENTER PANE: High-Density Inventory & Structural Wind Load Table */}
        <section className="finder-center-pane">
          {/* Collapsible Add Device Card */}
          {showAddForm && selectedSite && (
            <div className="finder-table-card" style={{ padding: 14 }}>
              <div style={{ marginBottom: 10, fontWeight: 600, fontSize: 13 }}>
                Tambah Perangkat Baru ke Site <span className="mono">{selectedSite}</span>
              </div>
              <form onSubmit={handleAdd} className="grid-form">
                <label>
                  Status
                  <select
                    value={status}
                    onChange={(e) => setStatus(e.target.value as DeviceStatus)}
                  >
                    <option value="EXISTING">EXISTING</option>
                    <option value="PROPOSED">PROPOSED</option>
                  </select>
                </label>
                <label>
                  Tenant
                  <input
                    required
                    value={tenant}
                    onChange={(e) => setTenant(e.target.value)}
                  />
                </label>
                <label className="span-2">
                  Device Name (Kode .lib)
                  <input
                    required
                    list="catalog-devices"
                    value={deviceName}
                    onChange={(e) => setDeviceName(e.target.value)}
                    placeholder="cth. SEC2.6, MW1.2, RRU-40"
                  />
                  <datalist id="catalog-devices">
                    {catalog.map((c) => (
                      <option key={c.device_name} value={c.device_name}>
                        {c.category} — EPA {c.epa_m2.toFixed(3)} m²
                      </option>
                    ))}
                  </datalist>
                </label>
                <label>
                  Mounting (.lib)
                  <input
                    list="mounting-devices"
                    value={mountingName}
                    onChange={(e) => setMountingName(e.target.value)}
                  />
                  <datalist id="mounting-devices">
                    {mountingDevices.map((m) => (
                      <option key={m.device_name} value={m.device_name} />
                    ))}
                  </datalist>
                </label>
                <label>
                  Elevasi Z (m)
                  <input
                    required
                    type="number"
                    step="any"
                    value={elevZ}
                    onChange={(e) => setElevZ(e.target.value)}
                  />
                </label>
                <label>
                  Qty
                  <input
                    required
                    type="number"
                    min={1}
                    value={qty}
                    onChange={(e) => setQty(e.target.value)}
                  />
                </label>
                <div className="form-actions">
                  <button type="submit" className="btn">
                    + Simpan ke Inventori
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* Missing in .lib Smart Resolution Banner */}
          {missingDevices.length > 0 && (
            <div className="finder-table-card" style={{ borderColor: "var(--warn-bd)" }}>
              <div className="finder-table-header" style={{ background: "var(--warn-bg)" }}>
                <div>
                  <h3 className="finder-table-title" style={{ fontSize: 13.5 }}>
                    <span className="semantic-dot amber" />
                    {missingDevices.length} Referensi Perangkat Belum Terdaftar di MTEL.lib
                  </h3>
                  <p className="finder-table-subtitle">
                    Pilih saran kemiripan dimensi untuk menyelaraskan EPA & massa sebelum analisa struktur OpenSeesPy.
                  </p>
                </div>
              </div>
              <div style={{ padding: 12, display: "flex", flexDirection: "column", gap: 8 }}>
                {missingDevices.map((d) => {
                  const topSugg = d.suggestions?.[0];
                  return (
                    <div
                      key={d.id}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        flexWrap: "wrap",
                        gap: 8,
                        padding: "6px 10px",
                        borderRadius: 6,
                        background: "var(--surface-2)",
                      }}
                    >
                      <div>
                        <strong className="mono">{d.device_name}</strong>{" "}
                        <span className="muted">
                          ({d.tenant} · Z = {d.elev_z_m} m · Qty {d.qty})
                        </span>
                      </div>
                      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                        {topSugg && (
                          <>
                            <button
                              type="button"
                              className="btn secondary sm"
                              onClick={() =>
                                handleApplySuggestion(d.id, topSugg.device_name, "replace")
                              }
                            >
                              Gunakan {topSugg.device_name} (EPA {topSugg.epa_m2.toFixed(2)} m²)
                            </button>
                            <button
                              type="button"
                              className="btn sm"
                              onClick={() =>
                                handleApplySuggestion(d.id, topSugg.device_name, "clone_to_lib")
                              }
                            >
                              Daftarkan '{d.device_name}' ke .lib
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Main Inventory & Structural Wind Load Table */}
          <div className="finder-table-card">
            <div className="finder-table-header">
              <div>
                <h2 className="finder-table-title">
                  Tabel Inventori Perangkat & Kontribusi Beban Struktur (.twr)
                </h2>
                <p className="finder-table-subtitle">
                  Menampilkan {filteredItems.length} baris perangkat · Total EPA ={" "}
                  <strong>{summaryMetrics.totalEpa.toFixed(3)} m²</strong> · Total Massa ={" "}
                  <strong>{summaryMetrics.totalMass.toFixed(1)} kg</strong>
                </p>
              </div>
              <div className="seg-group">
                {(["ALL", "EXISTING", "PROPOSED"] as const).map((st) => (
                  <button
                    key={st}
                    type="button"
                    className={statusFilter === st ? "active" : ""}
                    onClick={() => setStatusFilter(st)}
                  >
                    {st}
                  </button>
                ))}
              </div>
            </div>

            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Status</th>
                    <th>Face</th>
                    <th>Tenant</th>
                    <th>Kode .lib</th>
                    <th>Mounting</th>
                    <th className="num">Elev Z (m)</th>
                    <th className="num">Qty</th>
                    <th className="num">EPA/u (m²)</th>
                    <th className="num">Massa/u (kg)</th>
                    <th className="num">Total EPA (m²)</th>
                    <th className="num">1.2D Gravity (kN)</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {filteredItems.length === 0 ? (
                    <tr>
                      <td colSpan={12} className="muted" style={{ textAlign: "center", padding: 24 }}>
                        Tidak ada perangkat pada folder filter ini.
                      </td>
                    </tr>
                  ) : (
                    filteredItems.map((d) => {
                      const totEpa = d.epa_m2 != null ? d.epa_m2 * d.qty : null;
                      const totMassKg = d.mass_kg != null ? d.mass_kg * d.qty : null;
                      const factDeadKn =
                        totMassKg != null ? (totMassKg * 9.81 * 1.2) / 1000.0 : null;
                      const dotClass = !d.in_library
                        ? "red"
                        : d.status === "EXISTING"
                        ? "green"
                        : "amber";

                      return (
                        <tr key={d.id} className={!d.in_library ? "row-warn" : ""}>
                          <td>
                            <span className={`semantic-dot ${dotClass}`} />
                            <strong>{d.status}</strong>
                          </td>
                          <td>
                            <span className="badge">Face {d.face}</span>
                          </td>
                          <td><strong>{d.tenant}</strong></td>
                          <td className="mono">
                            {d.device_name}
                            {!d.in_library && (
                              <span
                                style={{
                                  marginLeft: 6,
                                  fontSize: 10.5,
                                  color: "var(--danger)",
                                  fontWeight: 600,
                                }}
                              >
                                [Unmapped]
                              </span>
                            )}
                          </td>
                          <td className="mono">{d.mounting_name || "-"}</td>
                          <td className="num">{d.elev_z_m.toFixed(2)}</td>
                          <td className="num">{d.qty}</td>
                          <td className="num">
                            {d.epa_m2 != null ? d.epa_m2.toFixed(3) : "-"}
                          </td>
                          <td className="num">
                            {d.mass_kg != null ? d.mass_kg.toFixed(1) : "-"}
                          </td>
                          <td className="num">
                            <strong>{totEpa != null ? totEpa.toFixed(3) : "-"}</strong>
                          </td>
                          <td className="num">
                            {factDeadKn != null ? factDeadKn.toFixed(3) : "-"}
                          </td>
                          <td className="num">
                            <button
                              type="button"
                              className="btn danger sm"
                              onClick={() => handleDelete(d.id)}
                            >
                              Hapus
                            </button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* RIGHT PANE: 4-Sided Elevation Blueprint & Inventory Inspector */}
        <aside className="finder-inspector-pane">
          <div className="finder-pane-header">
            <span className="finder-pane-title">4-Face Elevation Blueprint</span>
            <span className="badge">H = {towerHeight} m</span>
          </div>

          <div className="finder-inspector-section">
            <div className="finder-kv-grid">
              <div className="finder-kv-box">
                <span className="finder-kv-label">Total Unit</span>
                <span className="finder-kv-val">{summaryMetrics.totalUnits} unit</span>
              </div>
              <div className="finder-kv-box">
                <span className="finder-kv-label">Total EPA</span>
                <span className="finder-kv-val">{summaryMetrics.totalEpa.toFixed(2)} m²</span>
              </div>
              <div className="finder-kv-box">
                <span className="finder-kv-label">Total Massa</span>
                <span className="finder-kv-val">{summaryMetrics.totalMass.toFixed(1)} kg</span>
              </div>
              <div className="finder-kv-box">
                <span className="finder-kv-label">Status .lib</span>
                <span className="finder-kv-val">
                  {missingDevices.length === 0 ? "100% Valid" : `${missingDevices.length} Missing`}
                </span>
              </div>
            </div>
          </div>

          <div className="finder-inspector-section">
            <ElevationStrip
              heightM={towerHeight}
              topWidthM={activeTower?.top_width_m ?? 1.5}
              baseWidthM={activeTower?.bot_width_m ?? 6.5}
              devices={itemsWithFace}
              activeFace={faceFilter}
              onFaceChange={setFaceFilter}
            />
          </div>
        </aside>
      </div>
    </div>
  );
}
