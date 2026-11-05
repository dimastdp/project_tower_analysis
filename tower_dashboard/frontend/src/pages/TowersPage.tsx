import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { useSite } from "../SiteContext";
import type {
  AnalysisResult,
  Geometry,
  SdaReportData,
  SdaReportSummaryItem,
} from "../types";
import TowerViewer from "../components/TowerViewer";
import { ViewportFaceToolbar } from "../components/ViewportFaceToolbar";

type FinderVirtualFile =
  | "overview"
  | "buckling"
  | "reactions"
  | "load_combos"
  | "geometry";

export default function TowersPage() {
  const qc = useQueryClient();
  const { site: selectedSite, setSite: onSelectSite, activeFace = "ALL", setActiveFace } = useSite();

  const towersQuery = useQuery({ queryKey: ["towers"], queryFn: api.listTowers });
  const towers = towersQuery.data ?? [];

  const [geometry, setGeometry] = useState<Geometry | null>(null);
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [runningMode, setRunningMode] = useState<"compare" | "opensees" | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const [showDevices, setShowDevices] = useState(true);
  const [treeSearch, setTreeSearch] = useState("");
  const [activeFile, setActiveFile] = useState<FinderVirtualFile>("overview");
  const [memberFilter, setMemberFilter] = useState<string>("ALL");
  const fileRef = useRef<HTMLInputElement>(null);

  const siteDevicesQuery = useQuery({
    queryKey: ["inventory", selectedSite],
    queryFn: () => api.listSiteDevices(selectedSite!),
    enabled: !!selectedSite,
  });
  const siteDevices = siteDevicesQuery.data ?? [];

  // SDA PDF Extractor state
  const [sdaReports, setSdaReports] = useState<SdaReportSummaryItem[]>([]);
  const [activeSda, setActiveSda] = useState<SdaReportData | null>(null);
  const [sdaScenarioKey, setSdaScenarioKey] = useState<string>("DESIGN_EXISTING_PROPOSED");

  useEffect(() => {
    api.listSdaReports().then(setSdaReports).catch(() => { });
  }, []);

  useEffect(() => {
    if (!selectedSite) {
      setGeometry(null);
      setAnalysis(null);
      return;
    }
    let cancel = false;
    setLoading(true);
    setErr(null);
    Promise.all([
      api.geometry(selectedSite),
      api.latestAnalysis(selectedSite).catch(() => null),
    ])
      .then(([g, a]) => {
        if (!cancel) {
          setGeometry(g);
          setAnalysis(a);
        }
      })
      .catch((e: ApiError) => !cancel && setErr(e.message))
      .finally(() => !cancel && setLoading(false));
    return () => {
      cancel = true;
    };
  }, [selectedSite]);

  const refreshAll = () => {
    qc.invalidateQueries({ queryKey: ["towers"] });
    if (selectedSite) {
      qc.invalidateQueries({ queryKey: ["inventory", selectedSite] });
      qc.invalidateQueries({ queryKey: ["analysis", selectedSite] });
    }
  };

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setErr(null);
    setLoading(true);
    try {
      let lastSite = selectedSite;
      for (const f of Array.from(files)) {
        const lower = f.name.toLowerCase();
        if (lower.endsWith(".pdf")) {
          const sda = await api.uploadSdaPdf(f, true);
          setActiveSda(sda);
          const firstKey =
            Object.keys(sda.scenarios || {})[0] || "DESIGN_EXISTING_PROPOSED";
          setSdaScenarioKey(firstKey);
          const list = await api.listSdaReports();
          setSdaReports(list);
        } else {
          const summary = await api.uploadTower(f);
          lastSite = summary.site_name;
          setActiveSda(null);
        }
      }
      refreshAll();
      if (lastSite) onSelectSite(lastSite);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const handleSelectSdaReport = async (id: number) => {
    setErr(null);
    setLoading(true);
    try {
      const sda = await api.getSdaReport(id);
      setActiveSda(sda);
      const firstKey =
        Object.keys(sda.scenarios || {})[0] || "DESIGN_EXISTING_PROPOSED";
      setSdaScenarioKey(firstKey);
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (siteName: string) => {
    if (!confirm(`Hapus site '${siteName}' beserta inventori dan histori analisisnya?`)) return;
    setErr(null);
    try {
      await api.deleteTower(siteName);
      refreshAll();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    }
  };

  const handleRunTombolA = async () => {
    if (!selectedSite) return;
    setErr(null);
    setRunningMode("compare");
    try {
      const res = await api.runCompareMstAnalysis(selectedSite, {
        wind_speed_ms: analysis?.wind_speed_ms ?? 33.33,
        exposure: "C",
        struct_class: 2,
        kzt: 1.0,
      });
      setAnalysis(res);
      qc.invalidateQueries({ queryKey: ["analysis", selectedSite] });
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setRunningMode(null);
    }
  };

  const handleRunTombolB = async () => {
    if (!selectedSite) return;
    setErr(null);
    setRunningMode("opensees");
    try {
      const res = await api.runOpenSeesStandalone(selectedSite, {
        wind_speed_ms: analysis?.wind_speed_ms ?? 33.33,
        exposure: "C",
        struct_class: 2,
        kzt: 1.0,
      });
      setAnalysis(res);
      qc.invalidateQueries({ queryKey: ["analysis", selectedSite] });
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : String(e));
    } finally {
      setRunningMode(null);
    }
  };

  const activeTowerSummary = useMemo(
    () => towers.find((t) => t.site_name === selectedSite) ?? null,
    [towers, selectedSite]
  );

  const filteredTowers = useMemo(() => {
    const q = treeSearch.trim().toLowerCase();
    if (!q) return towers;
    return towers.filter((t) => t.site_name.toLowerCase().includes(q));
  }, [towers, treeSearch]);

  const eng = analysis?.engineering;
  const catSummary = eng?.category_sr_summary ?? [];
  const memberRows = eng?.member_checks ?? [];
  const compRows = eng?.member_comparison_rows ?? [];

  const filteredCompRows = useMemo(() => {
    if (memberFilter === "ALL") return compRows;
    return compRows.filter((m) =>
      (m.typ || "").toUpperCase().includes(memberFilter)
    );
  }, [compRows, memberFilter]);

  const renderStatusDot = (sr: number) => {
    const cls = sr > 1.0 ? "red" : sr >= 0.85 ? "amber" : "green";
    const label = sr > 1.0 ? "OVERSTRESS" : sr >= 0.85 ? "WARNING" : "AMAN";
    return (
      <span>
        <span className={`semantic-dot ${cls}`} />
        <strong style={{ fontSize: 11.5 }}>{label}</strong>
      </span>
    );
  };

  return (
    <div className="finder-shell">
      {/* Top macOS Finder Breadcrumb & Quick Actions Bar */}
      <div className="finder-breadcrumb-bar">
        <div className="finder-breadcrumb-path">
          <span>Workspace</span>
          <span className="finder-breadcrumb-sep">›</span>
          <span>MST Structural Catalog</span>
          {selectedSite && (
            <>
              <span className="finder-breadcrumb-sep">›</span>
              <strong>{selectedSite}.mst</strong>
              <span className="finder-breadcrumb-sep">›</span>
              <span className="mono" style={{ fontSize: 11.5, color: "var(--primary)" }}>
                {activeFile === "overview" && "01_Structural_Overview.mst"}
                {activeFile === "buckling" && "02_Member_Buckling_TIA222G.td"}
                {activeFile === "reactions" && "03_Support_Reactions_500_1140.rpt"}
                {activeFile === "load_combos" && "04_Load_Combinations_100_3140.twr"}
                {activeFile === "geometry" && "05_Nodal_Geometry.td"}
              </span>
            </>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input
            ref={fileRef}
            type="file"
            accept=".mst,.inp,.txt,.pdf"
            multiple
            data-testid="mst-file-input"
            style={{ display: "none" }}
            onChange={(e) => handleFiles(e.target.files)}
          />
          <button
            type="button"
            className="btn secondary sm"
            onClick={() => fileRef.current?.click()}
          >
            + Upload .mst / .pdf
          </button>
          {selectedSite && (
            <>
              <a
                href={api.exportMstUrl(selectedSite)}
                download
                className="btn-link secondary sm"
              >
                Unduh .mst
              </a>
              <a
                href={api.exportBundleRarUrl(selectedSite)}
                download
                className="btn-link tinted sm"
              >
                Paket .rar
              </a>
            </>
          )}
        </div>
      </div>

      {err && <div className="alert error">{err}</div>}

      {/* 3-Pane macOS Finder Layout */}
      <div className="finder-3pane">
        {/* LEFT PANE: File & Folder Tree Navigation */}
        <aside className="finder-tree-pane">
          <div className="finder-pane-header">
            <div className="finder-traffic-dots">
              <span className="finder-traffic-dot red" />
              <span className="finder-traffic-dot amber" />
              <span className="finder-traffic-dot green" />
            </div>
            <span className="finder-pane-title">MST Directory Tree</span>
            <span className="badge">{towers.length}</span>
          </div>

          <div className="finder-tree-scroll">
            {/* Search & Compact Dropzone */}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <input
                type="search"
                placeholder="Cari folder site .mst..."
                value={treeSearch}
                onChange={(e) => setTreeSearch(e.target.value)}
                style={{ width: "100%", height: 28, fontSize: 12 }}
              />
              <div
                className={`dropzone compact ${drag ? "drag" : ""}`}
                style={{ padding: "7px 10px", fontSize: 11.5 }}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDrag(true);
                }}
                onDragLeave={() => setDrag(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDrag(false);
                  handleFiles(e.dataTransfer.files);
                }}
                onClick={() => fileRef.current?.click()}
              >
                <span>Drop <code>.mst</code> / <code>.pdf</code> di sini</span>
              </div>
            </div>

            {/* Site Folders (.mst) */}
            <div className="finder-section-group">
              <div className="finder-section-label">Tower Sites (.mst)</div>
              {filteredTowers.length === 0 ? (
                <div className="muted" style={{ padding: "8px", fontSize: 12 }}>
                  Belum ada file .mst.
                </div>
              ) : (
                filteredTowers.map((t) => {
                  const isSelected = t.site_name === selectedSite && !activeSda;
                  return (
                    <div key={t.site_name}>
                      <button
                        type="button"
                        className={`finder-tree-folder ${isSelected ? "active" : ""}`}
                        onClick={() => {
                          setActiveSda(null);
                          onSelectSite(t.site_name);
                        }}
                      >
                        <div className="finder-item-main">
                          <span className="finder-chevron">{isSelected ? "▾" : "▸"}</span>
                          <span>📁</span>
                          <span className="finder-item-name">{t.site_name}.mst</span>
                        </div>
                        <span className="finder-item-meta">{t.total_members}M</span>
                      </button>

                      {isSelected && (
                        <div className="finder-tree-sublist">
                          <button
                            type="button"
                            className={`finder-tree-item ${activeFile === "overview" ? "active" : ""}`}
                            onClick={() => setActiveFile("overview")}
                          >
                            <div className="finder-item-main">
                              <span>📊</span>
                              <span className="finder-item-name">01_Structural_Overview.mst</span>
                            </div>
                          </button>
                          <button
                            type="button"
                            className={`finder-tree-item ${activeFile === "buckling" ? "active" : ""}`}
                            onClick={() => setActiveFile("buckling")}
                          >
                            <div className="finder-item-main">
                              <span>🔩</span>
                              <span className="finder-item-name">02_Member_Buckling_TIA_G.td</span>
                            </div>
                            <span className="finder-item-meta">{memberRows.length}</span>
                          </button>
                          <button
                            type="button"
                            className={`finder-tree-item ${activeFile === "reactions" ? "active" : ""}`}
                            onClick={() => setActiveFile("reactions")}
                          >
                            <div className="finder-item-main">
                              <span>⚓</span>
                              <span className="finder-item-name">03_Support_Reactions.rpt</span>
                            </div>
                            <span className="finder-item-meta">500–1140</span>
                          </button>
                          <button
                            type="button"
                            className={`finder-tree-item ${activeFile === "load_combos" ? "active" : ""}`}
                            onClick={() => setActiveFile("load_combos")}
                          >
                            <div className="finder-item-main">
                              <span>📋</span>
                              <span className="finder-item-name">04_Load_Combos.twr</span>
                            </div>
                            <span className="finder-item-meta">100–3140</span>
                          </button>
                          <button
                            type="button"
                            className={`finder-tree-item ${activeFile === "geometry" ? "active" : ""}`}
                            onClick={() => setActiveFile("geometry")}
                          >
                            <div className="finder-item-main">
                              <span>📐</span>
                              <span className="finder-item-name">05_Nodal_Geometry.td</span>
                            </div>
                            <span className="finder-item-meta">{t.total_nodes}N</span>
                          </button>
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>

            {/* SDA PDF Reports */}
            {sdaReports.length > 0 && (
              <div className="finder-section-group">
                <div className="finder-section-label">SDA Reports (.pdf)</div>
                {sdaReports.map((r) => {
                  const isAct = activeSda?.report_id === r.id;
                  return (
                    <button
                      key={r.id}
                      type="button"
                      className={`finder-tree-item ${isAct ? "active" : ""}`}
                      onClick={() => handleSelectSdaReport(r.id)}
                    >
                      <div className="finder-item-main">
                        <span>📄</span>
                        <span className="finder-item-name">
                          {r.site_id || r.filename}
                        </span>
                      </div>
                      <span className="finder-item-meta">
                        {r.tower_height_m ? `${r.tower_height_m}m` : "PDF"}
                      </span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </aside>

        {/* CENTER PANE: Structural Analysis Tables & Dual-Action Controls */}
        <section className="finder-center-pane">
          {!selectedSite && !activeSda ? (
            <div className="finder-table-card" style={{ padding: 32, textAlign: "center" }}>
              <p className="muted">
                Pilih folder site <code>.mst</code> pada panel kiri untuk menampilkan tabel analisa struktur dan model 3D.
              </p>
            </div>
          ) : activeSda ? (
            /* SDA PDF Extracted Summary in Center Pane */
            <div className="finder-table-card">
              <div className="finder-table-header">
                <div>
                  <h2 className="finder-table-title">
                    SDA Structural Report — {activeSda.site_metadata?.site_id || activeSda.filename}
                  </h2>
                  <p className="finder-table-subtitle">
                    {activeSda.site_metadata?.site_name || "-"} · Tower {activeSda.site_metadata?.tower_height_m ?? "-"} m
                  </p>
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                  {activeSda.report_id && (
                    <>
                      <a
                        className="btn-link secondary sm"
                        href={api.downloadSdaZipUrl(activeSda.report_id)}
                      >
                        ZIP (.td/.twr/.rpt)
                      </a>
                      <a
                        className="btn-export-xlsx"
                        href={api.exportSdaExcelUrl(activeSda.report_id)}
                      >
                        Export Excel (.xlsx)
                      </a>
                    </>
                  )}
                </div>
              </div>
              <div style={{ padding: 14 }}>
                <div className="seg-group" style={{ marginBottom: 12 }}>
                  {Object.keys(activeSda.scenarios || {}).map((k) => (
                    <button
                      key={k}
                      type="button"
                      className={sdaScenarioKey === k ? "active" : ""}
                      onClick={() => setSdaScenarioKey(k)}
                    >
                      {k.replace(/_/g, " ")}
                    </button>
                  ))}
                </div>
                {(() => {
                  const sc = activeSda.scenarios?.[sdaScenarioKey];
                  if (!sc) return null;
                  const srs = sc.summary?.stress_ratios || {};
                  return (
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>Komponen Struktur</th>
                            <th className="num">Max Stress Ratio (SR)</th>
                            <th>Status TIA-222-G</th>
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(srs).map(([comp, val]) => {
                            const v = Number(val ?? 0);
                            return (
                              <tr key={comp}>
                                <td><strong>{comp.toUpperCase()}</strong></td>
                                <td className="num">{val !== null ? v.toFixed(3) : "-"}</td>
                                <td>{renderStatusDot(v)}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  );
                })()}
              </div>
            </div>
          ) : (
            <>
              {/* Dual-Action Bar (Tombol A & Tombol B + Excel Export) */}
              <div className="dual-action-bar">
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "var(--ink)" }}>
                    Engine Analisa Struktur TIA-222-G — <span className="mono">{selectedSite}</span>
                  </div>
                  <div style={{ fontSize: 11.5, color: "var(--muted)" }}>
                    {analysis
                      ? `Mode Aktif: ${analysis.analysis_mode === "benchmark_calibration"
                        ? "Tombol A — Cross-Validation MST vs OpenSeesPy"
                        : "Tombol B — Standalone OpenSeesPy 3D Space Truss"
                      } · Vb = ${analysis.wind_speed_ms} m/s`
                      : "Belum ada run analisis. Klik Tombol A atau Tombol B untuk mengeksekusi solver."}
                  </div>
                </div>
                <div className="dual-action-buttons">
                  <button
                    type="button"
                    className={`btn-tombol-a ${analysis?.analysis_mode === "benchmark_calibration" ? "active" : ""
                      }`}
                    disabled={runningMode !== null}
                    onClick={handleRunTombolA}
                    title="Cross-Validation: Bandingkan kapasitas & gaya dalam MS Tower (.rpt) vs OpenSeesPy"
                  >
                    {runningMode === "compare"
                      ? "Memproses..."
                      : "Tombol A: Bandingkan MST vs OpenSeesPy"}
                  </button>
                  <button
                    type="button"
                    className={`btn-tombol-b ${analysis?.analysis_mode === "pure_opensees" ? "active" : ""
                      }`}
                    disabled={runningMode !== null}
                    onClick={handleRunTombolB}
                    title="Standalone Engine: Analisa murni OpenSeesPy 3D Corotational/Linear Truss sesuai TIA-222-G"
                  >
                    {runningMode === "opensees"
                      ? "Memproses..."
                      : "Tombol B: Analisa OpenSeesPy Saja"}
                  </button>
                  {selectedSite && analysis && (
                    <a
                      href={api.exportOpenSeesExcelUrl(selectedSite)}
                      download
                      className="btn-export-xlsx"
                      title="Unduh Workbook Excel (.xlsx) dengan formula dinamis kapasitas tekuk TIA-222-G & tabel Load Combinations 100–3140"
                    >
                      ⬇ Export Excel Formula (.xlsx)
                    </a>
                  )}
                </div>
              </div>

              {/* VIEW 1: 01_Structural_Overview.mst */}
              {activeFile === "overview" && (
                <>
                  <div className="finder-table-card">
                    <div className="finder-table-header">
                      <div>
                        <h2 className="finder-table-title">
                          Perbandingan Governing Stress Ratio & Kapasitas Tekuk (TIA-222-G Sec 4.5)
                        </h2>
                        <p className="finder-table-subtitle">
                          Ringkasan elemen kritis per kategori struktur dengan referensi Governing Load Case (Cases 500–1140)
                        </p>
                      </div>
                      <span className="badge">
                        {eng?.recommendation || "Jalankan Analisa"}
                      </span>
                    </div>
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>Kategori</th>
                            <th>Panel</th>
                            <th>Member</th>
                            <th>Profil Siku</th>
                            <th>Gov. Case</th>
                            <th className="num">KL/r</th>
                            <th className="num">Pu OS (kN)</th>
                            <th className="num">φPn OS (kN)</th>
                            <th className="num">SR OpenSees</th>
                            <th className="num">SR MST</th>
                            <th className="num">ΔSR</th>
                            <th>Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {catSummary.length === 0 ? (
                            <tr>
                              <td colSpan={12} className="muted" style={{ textAlign: "center", padding: 20 }}>
                                Klik <strong>Tombol A</strong> atau <strong>Tombol B</strong> di atas untuk memuat tabel perbandingan analisa struktur.
                              </td>
                            </tr>
                          ) : (
                            catSummary.map((row) => (
                              <tr key={row.category_key}>
                                <td><strong>{row.category_label}</strong></td>
                                <td className="num">P{row.pnl}</td>
                                <td className="mono">{row.member_id}</td>
                                <td className="mono">{row.sec_name}</td>
                                <td className="mono">
                                  <span className="badge">{row.gov_case_os ?? 500}</span>
                                </td>
                                <td className="num">{row.kl_r.toFixed(1)}</td>
                                <td className="num">{row.pu_opensees_kn.toFixed(2)}</td>
                                <td className="num">{row.phi_pn_opensees_kn.toFixed(2)}</td>
                                <td className="num">
                                  <strong>{row.sr_opensees.toFixed(3)}</strong>
                                </td>
                                <td className="num">{row.sr_mst.toFixed(3)}</td>
                                <td className="num">
                                  {(row.delta_sr ?? row.sr_opensees - row.sr_mst) >= 0 ? "+" : ""}
                                  {(row.delta_sr ?? row.sr_opensees - row.sr_mst).toFixed(3)}
                                </td>
                                <td>{renderStatusDot(row.sr_opensees)}</td>
                              </tr>
                            ))
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  {/* Quick Support Reactions Preview */}
                  {analysis && (
                    <div className="finder-table-card">
                      <div className="finder-table-header">
                        <div>
                          <h2 className="finder-table-title">
                            Reaksi Tumpuan Kaki Tower & Operasional 84 km/h Twist/Sway
                          </h2>
                          <p className="finder-table-subtitle">
                            Amplop Tekan Maksimum (Cases 500–660: 1.2D + 1.6W), Cabut/Uplift (Cases 1000–1140: 0.9D + 1.6W) & Operasional (Cases 3000–3140)
                          </p>
                        </div>
                      </div>
                      <div className="table-scroll">
                        <table>
                          <thead>
                            <tr>
                              <th>Node Kaki</th>
                              <th>Gov. Case Tekan</th>
                              <th className="num">Tekan Pu (kN)</th>
                              <th>Gov. Case Cabut</th>
                              <th className="num">Cabut Tu (kN)</th>
                              <th className="num">Geser Vx (kN)</th>
                              <th className="num">Geser Vy (kN)</th>
                              <th className="num">Resultan Vu (kN)</th>
                            </tr>
                          </thead>
                          <tbody>
                            {(eng?.reaction_details && eng.reaction_details.length > 0
                              ? eng.reaction_details
                              : analysis.reactions.map((r) => ({
                                node_label: String(r.node_label),
                                gov_case_comp: 500,
                                gov_case_uplift: 1080,
                                pu_kn: r.pu_kn,
                                tu_kn: r.tu_kn,
                                vx_kn: +(r.vu_kn * 0.7071).toFixed(2),
                                vy_kn: +(r.vu_kn * 0.7071).toFixed(2),
                                vu_kn: r.vu_kn,
                              }))
                            ).map((r) => (
                              <tr key={r.node_label}>
                                <td className="mono"><strong>Leg {r.node_label}</strong></td>
                                <td className="mono">Case {r.gov_case_comp} (1.2D+1.6W)</td>
                                <td className="num"><strong>{r.pu_kn.toFixed(2)}</strong></td>
                                <td className="mono">Case {r.gov_case_uplift} (0.9D+1.6W)</td>
                                <td className="num">{r.tu_kn.toFixed(2)}</td>
                                <td className="num">{r.vx_kn.toFixed(2)}</td>
                                <td className="num">{r.vy_kn.toFixed(2)}</td>
                                <td className="num"><strong>{r.vu_kn.toFixed(2)}</strong></td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </>
              )}

              {/* VIEW 2: 02_Member_Buckling_TIA_G.td */}
              {activeFile === "buckling" && (
                <div className="finder-table-card">
                  <div className="finder-table-header">
                    <div>
                      <h2 className="finder-table-title">
                        Tabel Kapasitas Tekuk Member TIA-222-G Sec 4.5.4 (Leff/r, KL/r, Fcr, φPn)
                      </h2>
                      <p className="finder-table-subtitle">
                        Perbandingan detail setiap panel & tipe batang terhadap kurva kelangsingan MS Tower & OpenSeesPy
                      </p>
                    </div>
                    <div className="seg-group">
                      {["ALL", "LEG", "BRACE", "HOR", "RED"].map((g) => (
                        <button
                          key={g}
                          type="button"
                          className={memberFilter === g ? "active" : ""}
                          onClick={() => setMemberFilter(g)}
                        >
                          {g}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="table-scroll" style={{ maxHeight: 540 }}>
                    <table>
                      <thead>
                        <tr>
                          <th>Panel</th>
                          <th>Member</th>
                          <th>Tipe</th>
                          <th>Profil</th>
                          <th>Gov. Case</th>
                          <th className="num">Leff (mm)</th>
                          <th className="num">r_min (mm)</th>
                          <th className="num">KL/r</th>
                          <th className="num">φPn OS (kN)</th>
                          <th className="num">Pu OS (kN)</th>
                          <th className="num">SR OS</th>
                          <th className="num">SR MST</th>
                          <th className="num">ΔSR</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredCompRows.map((m, i) => {
                          const dSr = m.delta_sr ?? m.sr_opensees - m.sr_mst;
                          return (
                            <tr key={`${m.pnl}-${m.members}-${i}`}>
                              <td className="num">P{m.pnl}</td>
                              <td className="mono">{m.members}</td>
                              <td>{m.typ}</td>
                              <td className="mono">{m.size}</td>
                              <td className="mono">Case {m.gov_case_os ?? 500}</td>
                              <td className="num">{(m.l_eff_mm ?? 1800).toFixed(0)}</td>
                              <td className="num">{(m.r_min_mm ?? 15.5).toFixed(2)}</td>
                              <td className="num">{m.kl_r.toFixed(1)}</td>
                              <td className="num">{m.phi_pn_opensees_kn.toFixed(2)}</td>
                              <td className="num">{m.pu_opensees_kn.toFixed(2)}</td>
                              <td className="num"><strong>{m.sr_opensees.toFixed(3)}</strong></td>
                              <td className="num">{m.sr_mst.toFixed(3)}</td>
                              <td className="num">
                                {dSr >= 0 ? "+" : ""}
                                {dSr.toFixed(3)}
                              </td>
                              <td>{renderStatusDot(m.sr_opensees)}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* VIEW 3: 03_Support_Reactions.rpt */}
              {activeFile === "reactions" && (
                <div className="finder-table-card">
                  <div className="finder-table-header">
                    <div>
                      <h2 className="finder-table-title">
                        Support Reactions & Baseplate Anchor Check (Cases 500–1140)
                      </h2>
                      <p className="finder-table-subtitle">
                        Gaya reaksi per tumpuan kaki tower beserta verifikasi baut angkur & pelat dasar
                      </p>
                    </div>
                  </div>
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Node Tumpuan</th>
                          <th>Governing Tekan</th>
                          <th className="num">Pu OpenSees (kN)</th>
                          <th className="num">Pu MST (kN)</th>
                          <th>Governing Cabut</th>
                          <th className="num">Tu OpenSees (kN)</th>
                          <th className="num">Tu MST (kN)</th>
                          <th className="num">Resultan Geser Vu (kN)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(eng?.reaction_details ?? []).map((r) => (
                          <tr key={r.node_label}>
                            <td className="mono"><strong>Node {r.node_label}</strong></td>
                            <td className="mono">Case {r.gov_case_comp} (1.20D + 1.60W)</td>
                            <td className="num"><strong>{r.pu_kn.toFixed(2)}</strong></td>
                            <td className="num">{(r.pu_mst_kn ?? r.pu_kn).toFixed(2)}</td>
                            <td className="mono">Case {r.gov_case_uplift} (0.90D + 1.60W)</td>
                            <td className="num"><strong>{r.tu_kn.toFixed(2)}</strong></td>
                            <td className="num">{(r.tu_mst_kn ?? r.tu_kn).toFixed(2)}</td>
                            <td className="num">{r.vu_kn.toFixed(2)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* VIEW 4: 04_Load_Combos.twr */}
              {activeFile === "load_combos" && (
                <div className="finder-table-card">
                  <div className="finder-table-header">
                    <div>
                      <h2 className="finder-table-title">
                        Tabel Kombinasi Beban Standar MS Tower & TIA-222-G (Cases 100–3140)
                      </h2>
                      <p className="finder-table-subtitle">
                        Kamus referensi Governing Case untuk Ultimate Compression (500–660), Uplift (1000–1140), Service (2000–2140), dan Operasional 84 km/h (3000–3140)
                      </p>
                    </div>
                  </div>
                  <div className="table-scroll" style={{ maxHeight: 540 }}>
                    <table>
                      <thead>
                        <tr>
                          <th>Case ID</th>
                          <th>Kategori</th>
                          <th>Nama Kombinasi</th>
                          <th>Formula Faktor</th>
                          <th className="num">Dead Factor</th>
                          <th className="num">Wind Factor</th>
                          <th className="num">Azimuth (°)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(eng?.load_combinations ?? []).map((lc) => (
                          <tr key={lc.case_id}>
                            <td className="mono"><strong>{lc.case_id}</strong></td>
                            <td><span className="badge">{lc.category}</span></td>
                            <td>{lc.name}</td>
                            <td className="mono">{lc.formula}</td>
                            <td className="num">{lc.dead_factor.toFixed(2)}</td>
                            <td className="num">{lc.wind_factor.toFixed(2)}</td>
                            <td className="num">
                              {lc.wind_dir_deg !== null ? `${lc.wind_dir_deg}°` : "-"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* VIEW 5: 05_Nodal_Geometry.td */}
              {activeFile === "geometry" && geometry && (
                <div className="finder-table-card">
                  <div className="finder-table-header">
                    <div>
                      <h2 className="finder-table-title">
                        Koordinat Nodal 3D & Konektivitas Batang ({selectedSite}.td)
                      </h2>
                      <p className="finder-table-subtitle">
                        {geometry.nodes.length} Nodes · {geometry.segments.length} Members
                      </p>
                    </div>
                  </div>
                  <div className="table-scroll" style={{ maxHeight: 520 }}>
                    <table>
                      <thead>
                        <tr>
                          <th>Node ID</th>
                          <th className="num">X (m)</th>
                          <th className="num">Y (m)</th>
                          <th className="num">Elevasi Z (m)</th>
                          <th>Tumpuan</th>
                        </tr>
                      </thead>
                      <tbody>
                        {geometry.nodes.map((n) => (
                          <tr key={n.id}>
                            <td className="mono"><strong>{n.id}</strong></td>
                            <td className="num">{n.x.toFixed(3)}</td>
                            <td className="num">{n.y.toFixed(3)}</td>
                            <td className="num">{n.z.toFixed(3)}</td>
                            <td>
                              {n.support ? (
                                <span className="badge">PINNED SUPPORT</span>
                              ) : (
                                <span className="muted">Free</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </>
          )}
        </section>

        {/* RIGHT PANE: 3D CAD Viewport & Structural Inspector */}
        <aside className="finder-inspector-pane">
          <div className="finder-pane-header">
            <span className="finder-pane-title">3D MST Studio & Inspector</span>
            {selectedSite && (
              <button
                type="button"
                className="btn danger sm"
                style={{ height: 22, padding: "0 8px", fontSize: 10.5 }}
                onClick={() => handleDelete(selectedSite)}
              >
                Hapus Site
              </button>
            )}
          </div>

          <div className="finder-inspector-section">
            <ViewportFaceToolbar
              activeFace={activeFace}
              onChange={(f) => setActiveFace?.(f)}
              showDevices={showDevices}
              onToggleDevices={() => setShowDevices((v) => !v)}
            />
            {loading && <p className="muted">Memuat geometri 3D...</p>}
            {geometry && (
              <div style={{ borderRadius: 8, overflow: "hidden", border: "1px solid var(--border)" }}>
                <TowerViewer
                  geometry={geometry}
                  devices={showDevices ? siteDevices : []}
                  highlightFace={activeFace}
                  memberStress={eng?.member_3d_stress}
                />
              </div>
            )}
          </div>

          {activeTowerSummary && (
            <div className="finder-inspector-section">
              <div className="finder-section-label">Dimensi & Geometri Tower</div>
              <div className="finder-kv-grid">
                <div className="finder-kv-box">
                  <span className="finder-kv-label">Tinggi Tower</span>
                  <span className="finder-kv-val">{activeTowerSummary.height_m.toFixed(2)} m</span>
                </div>
                <div className="finder-kv-box">
                  <span className="finder-kv-label">Lebar Dasar</span>
                  <span className="finder-kv-val">{activeTowerSummary.bot_width_m.toFixed(2)} m</span>
                </div>
                <div className="finder-kv-box">
                  <span className="finder-kv-label">Lebar Puncak</span>
                  <span className="finder-kv-val">{activeTowerSummary.top_width_m.toFixed(2)} m</span>
                </div>
                <div className="finder-kv-box">
                  <span className="finder-kv-label">Nodes / Members</span>
                  <span className="finder-kv-val">
                    {activeTowerSummary.total_nodes} / {activeTowerSummary.total_members}
                  </span>
                </div>
              </div>
            </div>
          )}

          {eng?.twist_sway_disp && (
            <div className="finder-inspector-section">
              <div className="finder-section-label">
                Operasional {eng.twist_sway_disp.operational_wind_kmh} km/h (Case {eng.twist_sway_disp.gov_case ?? 3020})
              </div>
              <div className="finder-kv-grid">
                <div className="finder-kv-box">
                  <span className="finder-kv-label">Max Sway (°)</span>
                  <span className="finder-kv-val">{eng.twist_sway_disp.sway_deg.toFixed(4)}°</span>
                </div>
                <div className="finder-kv-box">
                  <span className="finder-kv-label">Max Twist (°)</span>
                  <span className="finder-kv-val">{eng.twist_sway_disp.twist_deg.toFixed(4)}°</span>
                </div>
                <div className="finder-kv-box">
                  <span className="finder-kv-label">Defleksi Puncak</span>
                  <span className="finder-kv-val">{eng.twist_sway_disp.disp_h_mm.toFixed(1)} mm</span>
                </div>
                <div className="finder-kv-box">
                  <span className="finder-kv-label">Status Mikrowave</span>
                  <span className="finder-kv-val">{eng.twist_sway_disp.status}</span>
                </div>
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
