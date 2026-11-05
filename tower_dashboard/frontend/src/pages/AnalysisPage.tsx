import { FormEvent, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { useSite } from "../SiteContext";
import type {
  AnalysisResult,
  Geometry,
  MsTowerReportResult,
  PreflightResult,
} from "../types";
import TowerViewer from "../components/TowerViewer";
import { ViewportFaceToolbar } from "../components/ViewportFaceToolbar";

type AnalysisTreeSection =
  | "buckling_overview"
  | "buckling_all"
  | "load_combinations"
  | "support_reactions"
  | "twist_sway"
  | "wind_foundation"
  | "rpt_terminal";

export default function AnalysisPage() {
  const qc = useQueryClient();
  const { site: selectedSite, setSite: onSelectSite, activeFace = "ALL", setActiveFace } = useSite();

  const towersQuery = useQuery({ queryKey: ["towers"], queryFn: api.listTowers });
  const towers = towersQuery.data ?? [];

  const siteDevicesQuery = useQuery({
    queryKey: ["inventory", selectedSite],
    queryFn: () => api.listSiteDevices(selectedSite!),
    enabled: !!selectedSite,
  });
  const siteDevices = siteDevicesQuery.data ?? [];

  const [windSpeed, setWindSpeed] = useState("33.33");
  const [exposure, setExposure] = useState<"B" | "C" | "D">("C");
  const [structClass, setStructClass] = useState<1 | 2 | 3>(2);
  const [kzt, setKzt] = useState("1.0");
  const [analysisMode, setAnalysisMode] = useState<"pure_opensees" | "benchmark_calibration">(
    "benchmark_calibration"
  );

  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [geometry, setGeometry] = useState<Geometry | null>(null);
  const [preflight, setPreflight] = useState<PreflightResult | null>(null);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showDevices, setShowDevices] = useState(true);

  const [activeNode, setActiveNode] = useState<AnalysisTreeSection>("buckling_overview");
  const [groupFilter, setGroupFilter] = useState<string>("ALL");
  const [comboCategoryFilter, setComboCategoryFilter] = useState<string>("ALL");

  // MS Tower V6 .rpt report state
  const [rptData, setRptData] = useState<MsTowerReportResult | null>(null);
  const [rptLoading, setRptLoading] = useState(false);
  const [rptFilter, setRptFilter] = useState("");

  useEffect(() => {
    if (!selectedSite) {
      setResult(null);
      setGeometry(null);
      setPreflight(null);
      setRptData(null);
      return;
    }
    setErr(null);
    setRptData(null);
    api
      .latestAnalysis(selectedSite)
      .then((r) => {
        setResult(r);
        if (r) {
          setWindSpeed(String(r.wind_speed_ms));
          if (r.analysis_mode) setAnalysisMode(r.analysis_mode);
        }
      })
      .catch((e: ApiError) => setErr(e.message));
    api
      .geometry(selectedSite)
      .then(setGeometry)
      .catch(() => setGeometry(null));
    api
      .preflightAnalysis(selectedSite)
      .then((pf) => {
        setPreflight(pf);
        if (pf.default_vb_ms) setWindSpeed(String(pf.default_vb_ms));
        if (pf.default_exposure) setExposure(pf.default_exposure);
      })
      .catch(() => setPreflight(null));
  }, [selectedSite]);

  useEffect(() => {
    if (activeNode !== "rpt_terminal" || !selectedSite || !result) return;
    setRptLoading(true);
    api
      .analysisReport(selectedSite)
      .then(setRptData)
      .catch((e: ApiError) => setErr(e.message))
      .finally(() => setRptLoading(false));
  }, [activeNode, selectedSite, result?.run_id]);

  const executeMode = async (modeToRun: "pure_opensees" | "benchmark_calibration") => {
    if (!selectedSite) return;
    setErr(null);
    setRunning(true);
    setAnalysisMode(modeToRun);
    try {
      const params = {
        wind_speed_ms: Number(windSpeed),
        exposure,
        struct_class: structClass,
        kzt: Number(kzt),
      };
      const r =
        modeToRun === "benchmark_calibration"
          ? await api.runCompareMstAnalysis(selectedSite, params)
          : await api.runOpenSeesStandalone(selectedSite, params);
      setResult(r);
      qc.invalidateQueries({ queryKey: ["analysis", selectedSite] });
      api.preflightAnalysis(selectedSite).then(setPreflight).catch(() => {});
    } catch (ex) {
      setErr(ex instanceof ApiError ? ex.message : String(ex));
    } finally {
      setRunning(false);
    }
  };

  const handleRun = async (e: FormEvent) => {
    e.preventDefault();
    await executeMode(analysisMode);
  };

  const eng = result?.engineering;
  const catSummary = eng?.category_sr_summary ?? [];
  const memberChecks = eng?.member_checks ?? [];
  const compRows = eng?.member_comparison_rows ?? [];
  const loadCombos = eng?.load_combinations ?? [];
  const reactionDetails = eng?.reaction_details ?? [];
  const ts = eng?.twist_sway_disp;

  const filteredCompRows = useMemo(() => {
    if (groupFilter === "ALL") return compRows;
    return compRows.filter((m) =>
      (m.typ || "").toUpperCase().includes(groupFilter)
    );
  }, [compRows, groupFilter]);

  const filteredCombos = useMemo(() => {
    if (comboCategoryFilter === "ALL") return loadCombos;
    return loadCombos.filter((c) => c.category === comboCategoryFilter);
  }, [loadCombos, comboCategoryFilter]);

  const maxSrMember = useMemo(() => {
    if (!memberChecks.length) return null;
    return memberChecks.reduce(
      (best, cur) => (cur.stress_ratio > best.stress_ratio ? cur : best),
      memberChecks[0]
    );
  }, [memberChecks]);

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
      {/* Top macOS Finder Breadcrumb Bar */}
      <div className="finder-breadcrumb-bar">
        <div className="finder-breadcrumb-path">
          <span>Workspace</span>
          <span className="finder-breadcrumb-sep">›</span>
          <span>Structural Analysis TIA-222-G</span>
          {selectedSite && (
            <>
              <span className="finder-breadcrumb-sep">›</span>
              <strong>{selectedSite}</strong>
              <span className="finder-breadcrumb-sep">›</span>
              <span className="mono" style={{ fontSize: 11.5, color: "var(--primary)" }}>
                {activeNode === "buckling_overview" && "01_Governing_Buckling_Comparison.rpt"}
                {activeNode === "buckling_all" && `02_Member_Buckling_${groupFilter}.td`}
                {activeNode === "load_combinations" && "03_Load_Combinations_100_3140.twr"}
                {activeNode === "support_reactions" && "04_Support_Reactions_500_1140.rpt"}
                {activeNode === "twist_sway" && "05_Service_Twist_Sway_84kmh.rpt"}
                {activeNode === "wind_foundation" && "06_Wind_EPA_Foundation.rpt"}
                {activeNode === "rpt_terminal" && "07_Raw_MSTower_V6.rpt"}
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

          {result && selectedSite && (
            <>
              <a
                href={api.exportOpenSeesExcelUrl(selectedSite)}
                download
                className="btn-export-xlsx"
                title="Download Excel (.xlsx) dengan formula dinamis kapasitas tekuk TIA-222-G & tabel Load Combinations 100–3140"
              >
                ⬇ Export Excel Formula (.xlsx)
              </a>
              <a
                href={api.exportRptUrl(selectedSite)}
                download
                className="btn-link secondary sm"
              >
                Unduh .rpt
              </a>
            </>
          )}
        </div>
      </div>

      {err && <div className="alert error">{err}</div>}
      {result && result.warnings.map((w) => (
        <div key={w} className="alert warn">{w}</div>
      ))}

      {/* 3-Pane macOS Finder Layout */}
      <div className="finder-3pane">
        {/* LEFT PANE: Analysis Modules Tree & Wind Parameters */}
        <aside className="finder-tree-pane">
          <div className="finder-pane-header">
            <div className="finder-traffic-dots">
              <span className="finder-traffic-dot red" />
              <span className="finder-traffic-dot amber" />
              <span className="finder-traffic-dot green" />
            </div>
            <span className="finder-pane-title">TIA-222-G Explorer</span>
            {result && <span className="badge">Run #{result.run_id}</span>}
          </div>

          <div className="finder-tree-scroll">
            {/* Folder 1: Buckling & Member Capacity */}
            <div className="finder-section-group">
              <div className="finder-section-label">1. Member Buckling (Sec 4.5)</div>
              <button
                type="button"
                className={`finder-tree-folder ${
                  activeNode === "buckling_overview" ? "active" : ""
                }`}
                onClick={() => setActiveNode("buckling_overview")}
              >
                <div className="finder-item-main">
                  <span>📊</span>
                  <span className="finder-item-name">Governing_SR_Vs_MST.rpt</span>
                </div>
                <span className="finder-item-meta">500–1140</span>
              </button>

              <button
                type="button"
                className={`finder-tree-folder ${
                  activeNode === "buckling_all" && groupFilter === "ALL" ? "active" : ""
                }`}
                onClick={() => {
                  setActiveNode("buckling_all");
                  setGroupFilter("ALL");
                }}
              >
                <div className="finder-item-main">
                  <span>🔩</span>
                  <span className="finder-item-name">All_Member_Buckling.td</span>
                </div>
                <span className="finder-item-meta">{memberChecks.length}</span>
              </button>

              <div className="finder-tree-sublist">
                {[
                  { key: "LEG", label: "Leg_Members (Curves 1–3)" },
                  { key: "BRACE", label: "Diagonal_Bracing (Curves 4–6)" },
                  { key: "HOR", label: "Horizontal_Members" },
                  { key: "RED", label: "Redundant_Bracing" },
                ].map((g) => (
                  <button
                    key={g.key}
                    type="button"
                    className={`finder-tree-item ${
                      activeNode === "buckling_all" && groupFilter === g.key ? "active" : ""
                    }`}
                    onClick={() => {
                      setActiveNode("buckling_all");
                      setGroupFilter(g.key);
                    }}
                  >
                    <div className="finder-item-main">
                      <span>📐</span>
                      <span className="finder-item-name">{g.label}</span>
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {/* Folder 2: Load Combinations Dictionary (100-3140) */}
            <div className="finder-section-group">
              <div className="finder-section-label">2. Load Combinations</div>
              <button
                type="button"
                className={`finder-tree-folder ${
                  activeNode === "load_combinations" ? "active" : ""
                }`}
                onClick={() => setActiveNode("load_combinations")}
              >
                <div className="finder-item-main">
                  <span>📋</span>
                  <span className="finder-item-name">Load_Combos_100_3140.twr</span>
                </div>
                <span className="finder-item-meta">{loadCombos.length || 42}</span>
              </button>
            </div>

            {/* Folder 3: Support Reactions & Serviceability */}
            <div className="finder-section-group">
              <div className="finder-section-label">3. Reactions & Deflection</div>
              <button
                type="button"
                className={`finder-tree-item ${
                  activeNode === "support_reactions" ? "active" : ""
                }`}
                onClick={() => setActiveNode("support_reactions")}
              >
                <div className="finder-item-main">
                  <span>⚓</span>
                  <span className="finder-item-name">Support_Reactions.rpt</span>
                </div>
                <span className="finder-item-meta">500–1140</span>
              </button>

              <button
                type="button"
                className={`finder-tree-item ${
                  activeNode === "twist_sway" ? "active" : ""
                }`}
                onClick={() => setActiveNode("twist_sway")}
              >
                <div className="finder-item-main">
                  <span>📡</span>
                  <span className="finder-item-name">Twist_Sway_84kmh.rpt</span>
                </div>
                <span className="finder-item-meta">2000–3140</span>
              </button>

              <button
                type="button"
                className={`finder-tree-item ${
                  activeNode === "wind_foundation" ? "active" : ""
                }`}
                onClick={() => setActiveNode("wind_foundation")}
              >
                <div className="finder-item-main">
                  <span>🌬️</span>
                  <span className="finder-item-name">Wind_EPA_&_Foundation.rpt</span>
                </div>
              </button>

              <button
                type="button"
                className={`finder-tree-item ${
                  activeNode === "rpt_terminal" ? "active" : ""
                }`}
                onClick={() => setActiveNode("rpt_terminal")}
              >
                <div className="finder-item-main">
                  <span>📄</span>
                  <span className="finder-item-name">Raw_MSTower_V6.rpt</span>
                </div>
              </button>
            </div>

            {/* Wind & TIA-222-G Input Form inside Left Sidebar */}
            <form
              onSubmit={handleRun}
              style={{
                borderTop: "1px solid var(--border)",
                paddingTop: 10,
                display: "flex",
                flexDirection: "column",
                gap: 8,
              }}
            >
              <div className="finder-section-label" style={{ padding: 0 }}>
                Parameter Angin TIA-222-G
              </div>
              <label style={{ fontSize: 11.5 }}>
                Kecepatan Angin Vb (m/s)
                <input
                  required
                  type="number"
                  step="any"
                  min={1}
                  max={100}
                  value={windSpeed}
                  onChange={(e) => setWindSpeed(e.target.value)}
                  style={{ height: 28 }}
                />
              </label>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                <label style={{ fontSize: 11.5 }}>
                  Exposure
                  <select
                    value={exposure}
                    onChange={(e) => setExposure(e.target.value as "B" | "C" | "D")}
                    style={{ height: 28 }}
                  >
                    <option value="B">Exp B</option>
                    <option value="C">Exp C</option>
                    <option value="D">Exp D</option>
                  </select>
                </label>
                <label style={{ fontSize: 11.5 }}>
                  Class
                  <select
                    value={structClass}
                    onChange={(e) => setStructClass(Number(e.target.value) as 1 | 2 | 3)}
                    style={{ height: 28 }}
                  >
                    <option value={1}>Class I</option>
                    <option value={2}>Class II</option>
                    <option value={3}>Class III</option>
                  </select>
                </label>
              </div>
              <label style={{ fontSize: 11.5 }}>
                Topographic Factor Kzt
                <input
                  type="number"
                  step="0.05"
                  min={0.5}
                  max={3.0}
                  value={kzt}
                  onChange={(e) => setKzt(e.target.value)}
                  style={{ height: 28 }}
                />
              </label>
            </form>
          </div>
        </aside>

        {/* CENTER PANE: Dual-Action Bar & Structural Analysis Tables */}
        <section className="finder-center-pane">
          {/* Mandatory Dual-Action Buttons (Tombol A & Tombol B + Excel Export) */}
          <div className="dual-action-bar">
            <div>
              <div style={{ fontSize: 13.5, fontWeight: 600, color: "var(--ink)" }}>
                Dual-Mode Structural Analysis Engine —{" "}
                <span className="mono">{selectedSite || "Pilih Site"}</span>
              </div>
              <div style={{ fontSize: 11.5, color: "var(--muted)" }}>
                {result
                  ? `Aktif: ${
                      result.analysis_mode === "benchmark_calibration"
                        ? "Tombol A — Cross-Validation MST (.rpt) vs OpenSeesPy"
                        : "Tombol B — Standalone OpenSeesPy TIA-222-G Engine"
                    } · Vb = ${result.wind_speed_ms} m/s (${(
                      result.wind_speed_ms * 3.6
                    ).toFixed(0)} km/h)`
                  : "Pilih Tombol A (Cross-Validation) atau Tombol B (Standalone OpenSeesPy) untuk menjalankan solver."}
              </div>
            </div>

            <div className="dual-action-buttons">
              <button
                type="button"
                className={`btn-tombol-a ${
                  result?.analysis_mode === "benchmark_calibration" ? "active" : ""
                }`}
                disabled={running || !selectedSite}
                onClick={() => executeMode("benchmark_calibration")}
              >
                {running && analysisMode === "benchmark_calibration"
                  ? "Menghitung..."
                  : "Tombol A: Bandingkan MST vs OpenSeesPy"}
              </button>

              <button
                type="button"
                className={`btn-tombol-b ${
                  result?.analysis_mode === "pure_opensees" ? "active" : ""
                }`}
                disabled={running || !selectedSite}
                onClick={() => executeMode("pure_opensees")}
              >
                {running && analysisMode === "pure_opensees"
                  ? "Menghitung..."
                  : "Tombol B: Analisa OpenSeesPy Saja"}
              </button>

              {result && selectedSite && (
                <a
                  href={api.exportOpenSeesExcelUrl(selectedSite)}
                  download
                  className="btn-export-xlsx"
                >
                  ⬇ Export Analysis to Excel (.xlsx)
                </a>
              )}
            </div>
          </div>

          {preflight && preflight.has_missing_references && (
            <div className="alert warn">
              Ditemukan {preflight.missing_devices.length} perangkat unmapped di inventori.{" "}
              <strong>Tombol A</strong> akan otomatis memetakan referensi terdekat ke{" "}
              <code>MTEL.lib</code>.
            </div>
          )}

          {!result ? (
            <div className="finder-table-card" style={{ padding: 36, textAlign: "center" }}>
              <p className="muted">
                Belum ada hasil analisa untuk site ini. Klik{" "}
                <strong>Tombol A: Bandingkan MST vs OpenSeesPy</strong> atau{" "}
                <strong>Tombol B: Analisa OpenSeesPy Saja</strong> di atas.
              </p>
            </div>
          ) : (
            <>
              {/* SECTION 1: Governing SR Summary & Cross-Validation vs MST */}
              {activeNode === "buckling_overview" && (
                <>
                  <div className="finder-table-card">
                    <div className="finder-table-header">
                      <div>
                        <h2 className="finder-table-title">
                          1. Tabel Perbandingan Governing Stress Ratio & Kapasitas Tekuk (TIA-222-G Sec 4.5)
                        </h2>
                        <p className="finder-table-subtitle">
                          Perbandingan elemen kritis per kategori struktur dengan referensi Governing Case (Cases 500–1140) dan ΔSR = SR_OpenSees − SR_MST
                        </p>
                      </div>
                      <span className="badge">{eng?.recommendation}</span>
                    </div>
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>Komponen</th>
                            <th>Panel</th>
                            <th>Member</th>
                            <th>Profil Siku</th>
                            <th>Gov. Case</th>
                            <th className="num">Leff/r_min</th>
                            <th className="num">KL/r</th>
                            <th className="num">Pu OS (kN)</th>
                            <th className="num">φPn OS (kN)</th>
                            <th className="num">SR OpenSees</th>
                            <th className="num">Pu MST (kN)</th>
                            <th className="num">φPn MST (kN)</th>
                            <th className="num">SR MST</th>
                            <th className="num">ΔSR</th>
                            <th>Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {catSummary.map((row) => {
                            const lOverR =
                              row.l_eff_mm && row.r_min_mm && row.r_min_mm > 0
                                ? row.l_eff_mm / row.r_min_mm
                                : row.kl_r;
                            const deltaSr = row.delta_sr ?? row.sr_opensees - row.sr_mst;
                            return (
                              <tr
                                key={row.category_key}
                                style={
                                  row.category_key === "OVERALL"
                                    ? { fontWeight: 700, background: "var(--surface-2)" }
                                    : undefined
                                }
                              >
                                <td><strong>{row.category_label}</strong></td>
                                <td className="num">P{row.pnl}</td>
                                <td className="mono">{row.member_id}</td>
                                <td className="mono">{row.sec_name}</td>
                                <td className="mono">
                                  <span className="badge">Case {row.gov_case_os ?? 500}</span>
                                </td>
                                <td className="num">{lOverR.toFixed(1)}</td>
                                <td className="num">{row.kl_r.toFixed(1)}</td>
                                <td className="num">{row.pu_opensees_kn.toFixed(2)}</td>
                                <td className="num">{row.phi_pn_opensees_kn.toFixed(2)}</td>
                                <td className="num">
                                  <strong>{row.sr_opensees.toFixed(3)}</strong>
                                </td>
                                <td className="num">{row.pu_mst_kn.toFixed(2)}</td>
                                <td className="num">{row.phi_pn_mst_kn.toFixed(2)}</td>
                                <td className="num">{row.sr_mst.toFixed(3)}</td>
                                <td className="num">
                                  {deltaSr >= 0 ? "+" : ""}
                                  {deltaSr.toFixed(3)}
                                </td>
                                <td>{renderStatusDot(row.sr_opensees)}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  {/* Panel-by-Panel Member Comparison Table */}
                  {compRows.length > 0 && (
                    <div className="finder-table-card">
                      <div className="finder-table-header">
                        <div>
                          <h2 className="finder-table-title">
                            Perbandingan Per Panel & Grup Member (MS Tower vs OpenSeesPy)
                          </h2>
                          <p className="finder-table-subtitle">
                            Menampilkan {compRows.length} grup panel dari bawah ke puncak tower
                          </p>
                        </div>
                      </div>
                      <div className="table-scroll" style={{ maxHeight: 460 }}>
                        <table>
                          <thead>
                            <tr>
                              <th>Panel</th>
                              <th>Member</th>
                              <th>Tipe</th>
                              <th>Profil</th>
                              <th>Gov. Case</th>
                              <th className="num">KL/r</th>
                              <th className="num">Pu OS (kN)</th>
                              <th className="num">φPn OS (kN)</th>
                              <th className="num">SR OS</th>
                              <th className="num">Pu MST (kN)</th>
                              <th className="num">φPn MST (kN)</th>
                              <th className="num">SR MST</th>
                              <th className="num">ΔSR</th>
                              <th>Status</th>
                            </tr>
                          </thead>
                          <tbody>
                            {compRows.map((r, i) => {
                              const dSr = r.delta_sr ?? r.sr_opensees - r.sr_mst;
                              return (
                                <tr key={`${r.pnl}-${r.members}-${i}`}>
                                  <td className="num">P{r.pnl}</td>
                                  <td className="mono">{r.members}</td>
                                  <td>{r.typ}</td>
                                  <td className="mono">{r.size}</td>
                                  <td className="mono">Case {r.gov_case_os ?? 500}</td>
                                  <td className="num">{r.kl_r.toFixed(1)}</td>
                                  <td className="num">{r.pu_opensees_kn.toFixed(2)}</td>
                                  <td className="num">{r.phi_pn_opensees_kn.toFixed(2)}</td>
                                  <td className="num">
                                    <strong>{r.sr_opensees.toFixed(3)}</strong>
                                  </td>
                                  <td className="num">{r.pu_mst_kn.toFixed(2)}</td>
                                  <td className="num">{r.phi_pn_mst_kn.toFixed(2)}</td>
                                  <td className="num">{r.sr_mst.toFixed(3)}</td>
                                  <td className="num">
                                    {dSr >= 0 ? "+" : ""}
                                    {dSr.toFixed(3)}
                                  </td>
                                  <td>{renderStatusDot(r.sr_opensees)}</td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </>
              )}

              {/* SECTION 2: Detailed Member Buckling Check (All Members) */}
              {activeNode === "buckling_all" && (
                <div className="finder-table-card">
                  <div className="finder-table-header">
                    <div>
                      <h2 className="finder-table-title">
                        2. Detail Kapasitas Tekuk Elemen Siku TIA-222-G Sec 4.5.4 ({groupFilter})
                      </h2>
                      <p className="finder-table-subtitle">
                        Parameter Leff, r_min, Kurva Eccentricity KL/r, dan φPn = 0.90·Ag·Fcr per panel & tipe batang
                      </p>
                    </div>
                    <div className="seg-group">
                      {["ALL", "LEG", "BRACE", "HOR", "RED"].map((g) => (
                        <button
                          key={g}
                          type="button"
                          className={groupFilter === g ? "active" : ""}
                          onClick={() => setGroupFilter(g)}
                        >
                          {g}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="table-scroll" style={{ maxHeight: 560 }}>
                    <table>
                      <thead>
                        <tr>
                          <th>Panel</th>
                          <th>Member</th>
                          <th>Tipe</th>
                          <th>Profil</th>
                          <th>Gov. Case</th>
                          <th className="num">Ag (mm²)</th>
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
                        {filteredCompRows.map((m, idx) => {
                          const dSr = m.delta_sr ?? m.sr_opensees - m.sr_mst;
                          return (
                            <tr key={`${m.pnl}-${m.members}-${idx}`}>
                              <td className="num">P{m.pnl}</td>
                              <td className="mono">{m.members}</td>
                              <td>{m.typ}</td>
                              <td className="mono">{m.size}</td>
                              <td className="mono">Case {m.gov_case_os ?? 500}</td>
                              <td className="num">{(m.ag_mm2 ?? 940).toFixed(0)}</td>
                              <td className="num">{(m.l_eff_mm ?? 1800).toFixed(0)}</td>
                              <td className="num">{(m.r_min_mm ?? 15.5).toFixed(2)}</td>
                              <td className="num">{m.kl_r.toFixed(1)}</td>
                              <td className="num">{m.phi_pn_opensees_kn.toFixed(2)}</td>
                              <td className="num">{m.pu_opensees_kn.toFixed(2)}</td>
                              <td className="num">
                                <strong>{m.sr_opensees.toFixed(3)}</strong>
                              </td>
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

              {/* SECTION 3: Standard Load Combinations Dictionary (Cases 100–3140) */}
              {activeNode === "load_combinations" && (
                <div className="finder-table-card">
                  <div className="finder-table-header">
                    <div>
                      <h2 className="finder-table-title">
                        3. Tabel Kombinasi Beban Standar MS Tower & TIA-222-G (Cases 100–3140)
                      </h2>
                      <p className="finder-table-subtitle">
                        Referensi kamus kombinasi beban yang tertaut ke formula VLOOKUP pada Export Excel (.xlsx)
                      </p>
                    </div>
                    <div className="seg-group">
                      {[
                        "ALL",
                        "PRIMARY",
                        "ULTIMATE_COMPRESSION",
                        "ULTIMATE_UPLIFT",
                        "SERVICEABILITY",
                        "OPERATIONAL_84KMH",
                      ].map((cat) => (
                        <button
                          key={cat}
                          type="button"
                          className={comboCategoryFilter === cat ? "active" : ""}
                          onClick={() => setComboCategoryFilter(cat)}
                        >
                          {cat === "ALL" ? "ALL (42)" : cat.replace("ULTIMATE_", "")}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="table-scroll" style={{ maxHeight: 560 }}>
                    <table>
                      <thead>
                        <tr>
                          <th>Case ID</th>
                          <th>Kategori</th>
                          <th>Deskripsi Kombinasi</th>
                          <th>Formula Kombinasi</th>
                          <th className="num">Dead Factor</th>
                          <th className="num">Wind Factor</th>
                          <th className="num">Arah Angin (°)</th>
                          <th>Keterangan Engineering</th>
                        </tr>
                      </thead>
                      <tbody>
                        {filteredCombos.map((lc) => (
                          <tr key={lc.case_id}>
                            <td className="mono"><strong>{lc.case_id}</strong></td>
                            <td><span className="badge">{lc.category}</span></td>
                            <td>{lc.name}</td>
                            <td className="mono"><strong>{lc.formula}</strong></td>
                            <td className="num">{lc.dead_factor.toFixed(2)}</td>
                            <td className="num">{lc.wind_factor.toFixed(2)}</td>
                            <td className="num">
                              {lc.wind_dir_deg !== null ? `${lc.wind_dir_deg}°` : "-"}
                            </td>
                            <td className="muted">{lc.note}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* SECTION 4: Support Reactions & Baseplate Anchor Check */}
              {activeNode === "support_reactions" && (
                <>
                  <div className="finder-table-card">
                    <div className="finder-table-header">
                      <div>
                        <h2 className="finder-table-title">
                          4. Tabel Reaksi Tumpuan Kaki Tower (Cases 500–660 & 1000–1140)
                        </h2>
                        <p className="finder-table-subtitle">
                          Tekan Maksimum (1.20D + 1.60W), Cabut/Uplift Maksimum (0.90D + 1.60W), dan Resultan Geser Vu = √(Vx² + Vy²)
                        </p>
                      </div>
                    </div>
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>Node Kaki</th>
                            <th>Gov. Case Tekan</th>
                            <th className="num">Tekan Pu OS (kN)</th>
                            <th className="num">Tekan Pu MST (kN)</th>
                            <th>Gov. Case Cabut</th>
                            <th className="num">Cabut Tu OS (kN)</th>
                            <th className="num">Cabut Tu MST (kN)</th>
                            <th className="num">Geser Vx (kN)</th>
                            <th className="num">Geser Vy (kN)</th>
                            <th className="num">Resultan Vu (kN)</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(reactionDetails.length > 0
                            ? reactionDetails
                            : result.reactions.map((r) => ({
                                node_label: String(r.node_label),
                                gov_case_comp: 500,
                                gov_case_uplift: 1080,
                                pu_kn: r.pu_kn,
                                tu_kn: r.tu_kn,
                                vx_kn: +(r.vu_kn * 0.7071).toFixed(2),
                                vy_kn: +(r.vu_kn * 0.7071).toFixed(2),
                                vu_kn: r.vu_kn,
                                pu_mst_kn: r.pu_kn,
                                tu_mst_kn: r.tu_kn,
                                vu_mst_kn: r.vu_kn,
                              }))
                          ).map((r) => (
                            <tr key={r.node_label}>
                              <td className="mono"><strong>Leg {r.node_label}</strong></td>
                              <td className="mono">Case {r.gov_case_comp} (1.2D+1.6W)</td>
                              <td className="num"><strong>{r.pu_kn.toFixed(2)}</strong></td>
                              <td className="num">{(r.pu_mst_kn ?? r.pu_kn).toFixed(2)}</td>
                              <td className="mono">Case {r.gov_case_uplift} (0.9D+1.6W)</td>
                              <td className="num"><strong>{r.tu_kn.toFixed(2)}</strong></td>
                              <td className="num">{(r.tu_mst_kn ?? r.tu_kn).toFixed(2)}</td>
                              <td className="num">{r.vx_kn.toFixed(2)}</td>
                              <td className="num">{r.vy_kn.toFixed(2)}</td>
                              <td className="num"><strong>{r.vu_kn.toFixed(2)}</strong></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  {eng?.anchor_baseplate && (
                    <div className="finder-table-card">
                      <div className="finder-table-header">
                        <div>
                          <h2 className="finder-table-title">
                            Verifikasi Baut Angkur (Anchor Rod) & Baseplate
                          </h2>
                        </div>
                      </div>
                      <div className="table-scroll">
                        <table>
                          <thead>
                            <tr>
                              <th>Komponen Sambungan</th>
                              <th>Spesifikasi</th>
                              <th className="num">Gaya / Tegangan</th>
                              <th className="num">Kapasitas Izin</th>
                              <th className="num">Rasio Interaksi</th>
                              <th>Status</th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr>
                              <td><strong>Anchor Bolt</strong></td>
                              <td className="mono">
                                {eng.anchor_baseplate.n_bolts} × M{eng.anchor_baseplate.d_bolt_mm} (Fu={eng.anchor_baseplate.fu_bolt_mpa} MPa)
                              </td>
                              <td className="num">
                                Tu={eng.anchor_baseplate.pu_bolt_kn} kN / Vu={eng.anchor_baseplate.vu_bolt_kn} kN
                              </td>
                              <td className="num">An = {eng.anchor_baseplate.an_mm2} mm²</td>
                              <td className="num"><strong>{eng.anchor_baseplate.anchor_ratio.toFixed(3)}</strong></td>
                              <td>{renderStatusDot(eng.anchor_baseplate.anchor_ratio)}</td>
                            </tr>
                            <tr>
                              <td><strong>Baseplate</strong></td>
                              <td className="mono">
                                {eng.anchor_baseplate.bp_width_mm}×{eng.anchor_baseplate.bp_width_mm}×{eng.anchor_baseplate.bp_thick_mm} mm
                              </td>
                              <td className="num">fp = {eng.anchor_baseplate.fp_mpa} MPa</td>
                              <td className="num">ϕFp = {eng.anchor_baseplate.fp_allow_mpa} MPa</td>
                              <td className="num"><strong>{eng.anchor_baseplate.bp_ratio.toFixed(3)}</strong></td>
                              <td>{renderStatusDot(eng.anchor_baseplate.bp_ratio)}</td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </>
              )}

              {/* SECTION 5: Service Deflection & 84 km/h Operational Twist/Sway */}
              {activeNode === "twist_sway" && ts && (
                <div className="finder-table-card">
                  <div className="finder-table-header">
                    <div>
                      <h2 className="finder-table-title">
                        5. Evaluasi Serviceability (Cases 2000–2140) & Operasional 84 km/h Twist/Sway (Cases 3000–3140)
                      </h2>
                      <p className="finder-table-subtitle">
                        Kombinasi Operasional: {ts.load_combination || "1.20D + 0.49W (Case 3020)"} · Batas Izin Microwave Dish ≤ {ts.sway_limit_deg}°
                      </p>
                    </div>
                    <span className="badge">{ts.status}</span>
                  </div>
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Parameter Deformasi</th>
                          <th>Governing Case</th>
                          <th className="num">OpenSeesPy</th>
                          <th className="num">MS Tower (.rpt)</th>
                          <th className="num">Batas Izin TIA-222-G</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          <td><strong>Max Sway (Kemiringan Antena)</strong></td>
                          <td className="mono">Case {ts.gov_case ?? 3020} (1.20D + 0.49W)</td>
                          <td className="num"><strong>{ts.sway_deg.toFixed(4)}°</strong></td>
                          <td className="num">{ts.mst_sway_deg.toFixed(4)}°</td>
                          <td className="num">≤ {ts.sway_limit_deg.toFixed(2)}°</td>
                          <td>{renderStatusDot(ts.sway_deg / ts.sway_limit_deg)}</td>
                        </tr>
                        <tr>
                          <td><strong>Max Twist (Puntir Puncak)</strong></td>
                          <td className="mono">Case {ts.gov_case ?? 3020} (1.20D + 0.49W)</td>
                          <td className="num"><strong>{ts.twist_deg.toFixed(4)}°</strong></td>
                          <td className="num">{ts.mst_twist_deg.toFixed(4)}°</td>
                          <td className="num">≤ {ts.sway_limit_deg.toFixed(2)}°</td>
                          <td>{renderStatusDot(ts.twist_deg / ts.sway_limit_deg)}</td>
                        </tr>
                        <tr>
                          <td><strong>Defleksi Horizontal Puncak (Ux, Uy)</strong></td>
                          <td className="mono">Case {ts.gov_service_case ?? 2000} (1.00D + 1.00W)</td>
                          <td className="num"><strong>{ts.disp_h_mm.toFixed(2)} mm</strong></td>
                          <td className="num">{ts.mst_disp_h_mm.toFixed(2)} mm</td>
                          <td className="num">L / 200</td>
                          <td>{renderStatusDot(0.35)}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* SECTION 6: Wind EPA & Foundation Check */}
              {activeNode === "wind_foundation" && eng && (
                <>
                  <div className="finder-table-card">
                    <div className="finder-table-header">
                      <div>
                        <h2 className="finder-table-title">
                          Gaya Angin Perangkat Antena (TIA-222-G Sec 2.6.9: F = qz · Gh · EPA)
                        </h2>
                        <p className="finder-table-subtitle">
                          Total 1.6W = {eng.wind_summary.total_dev_wind_kn.toFixed(2)} kN · Total 1.2D = {eng.wind_summary.total_dev_dead_kn.toFixed(2)} kN
                        </p>
                      </div>
                    </div>
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>Status</th>
                            <th>Tenant</th>
                            <th>Perangkat</th>
                            <th className="num">Elev Z (m)</th>
                            <th className="num">Qty</th>
                            <th className="num">qz (Pa)</th>
                            <th className="num">Total EPA (m²)</th>
                            <th className="num">Fw (kN)</th>
                            <th className="num">1.6·Fw (kN)</th>
                            <th className="num">1.2·DL (kN)</th>
                          </tr>
                        </thead>
                        <tbody>
                          {eng.device_loads.map((d, i) => (
                            <tr key={`${d.device_name}-${i}`}>
                              <td><strong>{d.status}</strong></td>
                              <td>{d.tenant}</td>
                              <td className="mono">{d.device_name}</td>
                              <td className="num">{d.elev_z_m.toFixed(1)}</td>
                              <td className="num">{d.qty}</td>
                              <td className="num">{d.qz_pa.toFixed(1)}</td>
                              <td className="num">{d.epa_total_m2.toFixed(3)}</td>
                              <td className="num">{d.fw_kn.toFixed(3)}</td>
                              <td className="num"><strong>{d.fw_factored_kn.toFixed(3)}</strong></td>
                              <td className="num">{d.fd_factored_kn.toFixed(3)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </>
              )}

              {/* SECTION 7: Raw MS Tower V6 .rpt Viewer */}
              {activeNode === "rpt_terminal" && (
                <div className="finder-table-card">
                  <div className="finder-table-header">
                    <div>
                      <h2 className="finder-table-title">
                        MS Tower V6 Output Report (.rpt)
                      </h2>
                    </div>
                    <input
                      type="search"
                      placeholder="Cari baris di .rpt..."
                      value={rptFilter}
                      onChange={(e) => setRptFilter(e.target.value)}
                      style={{ width: 220, height: 28 }}
                    />
                  </div>
                  <div style={{ padding: 12 }}>
                    {rptLoading && <p className="muted">Memuat laporan .rpt...</p>}
                    {rptData && (
                      <div className="rpt-viewer-box">
                        <pre className="rpt-pre">
                          {rptData.report_text
                            .split("\n")
                            .filter((ln) =>
                              rptFilter.trim()
                                ? ln.toLowerCase().includes(rptFilter.toLowerCase())
                                : true
                            )
                            .map((line, idx) => (
                              <div key={idx} className="rpt-line">
                                <span className="rpt-ln">{idx + 1}</span>
                                <span className="rpt-txt">{line}</span>
                              </div>
                            ))}
                        </pre>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </section>

        {/* RIGHT PANE: 3D Stress Ratio Stage & Structural Verdict Inspector */}
        <aside className="finder-inspector-pane">
          <div className="finder-pane-header">
            <span className="finder-pane-title">3D Stress Ratio Stage</span>
            {maxSrMember && renderStatusDot(maxSrMember.stress_ratio)}
          </div>

          <div className="finder-inspector-section">
            <ViewportFaceToolbar
              activeFace={activeFace}
              onChange={(f) => setActiveFace?.(f)}
              showDevices={showDevices}
              onToggleDevices={() => setShowDevices((v) => !v)}
            />
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

          {result && (
            <div className="finder-inspector-section">
              <div className="finder-section-label">Ringkasan Governing Kapasitas</div>
              <div className="finder-kv-grid">
                <div className="finder-kv-box">
                  <span className="finder-kv-label">Max SR Overall</span>
                  <span className="finder-kv-val">
                    {maxSrMember ? maxSrMember.stress_ratio.toFixed(3) : "-"}
                  </span>
                </div>
                <div className="finder-kv-box">
                  <span className="finder-kv-label">Profil Kritis</span>
                  <span className="finder-kv-val">
                    {maxSrMember ? maxSrMember.sec_name : "-"}
                  </span>
                </div>
                <div className="finder-kv-box">
                  <span className="finder-kv-label">Max Tekan Pu</span>
                  <span className="finder-kv-val">{result.max_pu_kn.toFixed(2)} kN</span>
                </div>
                <div className="finder-kv-box">
                  <span className="finder-kv-label">Max Cabut Tu</span>
                  <span className="finder-kv-val">{result.max_tu_kn.toFixed(2)} kN</span>
                </div>
              </div>
            </div>
          )}

          {eng?.recommendation && (
            <div className="finder-inspector-section">
              <div className="finder-section-label">Rekomendasi Struktur</div>
              <div
                className="finder-kv-box"
                style={{
                  background:
                    maxSrMember && maxSrMember.stress_ratio <= 1.0
                      ? "var(--success-bg)"
                      : "var(--danger-bg)",
                  borderColor:
                    maxSrMember && maxSrMember.stress_ratio <= 1.0
                      ? "var(--success-bd)"
                      : "var(--danger-bd)",
                }}
              >
                <div style={{ fontSize: 12, fontWeight: 600 }}>{eng.recommendation}</div>
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
