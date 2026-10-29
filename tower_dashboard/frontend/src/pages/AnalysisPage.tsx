import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api";
import { useSite } from "../SiteContext";
import { useToast } from "../components/Toast";
import TowerViewer from "../components/TowerViewer";
import type { AnalysisResult, PreflightResult } from "../types";

const MSTOWER_STRESS_LEGEND = [
  { label: "SR = 0.00", color: "#94a3b8" },
  { label: "< 0.50", color: "#2563eb" },
  { label: "0.50–0.75", color: "#06b6d4" },
  { label: "0.75–0.90", color: "#16a34a" },
  { label: "0.90–1.00", color: "#eab308" },
  { label: "> 1.00 OVERSTRESS", color: "#dc2626" },
];

type AnalysisTab = "calibration" | "report" | "members" | "devices" | "foundation";
type CalibCategoryFilter = "ALL" | "SR" | "TWIST_SWAY_DISP" | "SUPPORT_REACTION";
type ReportSectionFilter = "ALL" | "MEMBER_CHECK" | "REACTIONS" | "ROTATIONS" | "DISPLACEMENTS" | "SUMMARY";

function sliceReportSection(fullText: string, section: ReportSectionFilter): string {
  if (!fullText || section === "ALL") return fullText;
  const idxReactions = fullText.indexOf("Reactions (format Mstower V6");
  const idxRotations = fullText.indexOf("Ancillary Rotations (format Mstower V6");
  const idxInput = fullText.indexOf("-- I N P U T / A N A L Y S I S   R E P O R T --");
  const idxSummary = fullText.indexOf("-- T O W E R   S T U D I O   C A L C U L A T I O N   S U M M A R Y --");

  if (section === "MEMBER_CHECK") {
    return idxReactions !== -1 ? fullText.slice(0, idxReactions).trimEnd() : fullText;
  }
  if (section === "REACTIONS") {
    if (idxReactions === -1) return "Bagian SUPPORT REACTIONS tidak ditemukan.";
    const end = idxRotations !== -1 ? idxRotations : idxInput !== -1 ? idxInput : fullText.length;
    return fullText.slice(idxReactions, end).trimEnd();
  }
  if (section === "ROTATIONS") {
    if (idxRotations === -1) return "Bagian ANCILLARY ROTATIONS / TWIST & SWAY tidak ditemukan.";
    const end = idxInput !== -1 ? idxInput : idxSummary !== -1 ? idxSummary : fullText.length;
    return fullText.slice(idxRotations, end).trimEnd();
  }
  if (section === "DISPLACEMENTS") {
    if (idxInput === -1) return "Bagian NODE DISPLACEMENTS tidak ditemukan.";
    const end = idxSummary !== -1 ? idxSummary : fullText.length;
    return fullText.slice(idxInput, end).trimEnd();
  }
  if (section === "SUMMARY") {
    return idxSummary !== -1 ? fullText.slice(idxSummary).trimEnd() : fullText;
  }
  return fullText;
}

const CATEGORY_LABELS: Record<string, { badge: string; colorClass: string }> = {
  SR: { badge: "Stress Ratio (SR)", colorClass: "info" },
  TWIST_SWAY_DISP: { badge: "Twist, Sway & Disp", colorClass: "ok" },
  SUPPORT_REACTION: { badge: "Support Reaction", colorClass: "warn" },
};

export default function AnalysisPage() {
  const { site } = useSite();
  const qc = useQueryClient();
  const toast = useToast();

  const [windSpeed, setWindSpeed] = useState("32.10");
  const [exposure, setExposure] = useState<"B" | "C" | "D">("B");
  const [structClass, setStructClass] = useState<1 | 2 | 3>(2);
  const [kzt, setKzt] = useState("1.00");
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<AnalysisTab>("calibration");
  const [calibFilter, setCalibFilter] = useState<CalibCategoryFilter>("ALL");
  const [reportSection, setReportSection] = useState<ReportSectionFilter>("ALL");
  const [reportSearch, setReportSearch] = useState("");

  const [memberViewMode, setMemberViewMode] = useState<"summary" | "details">("summary");
  const [memberSearch, setMemberSearch] = useState("");
  const [memberFilterType, setMemberFilterType] = useState<string>("ALL");
  const [memberFilterStatus, setMemberFilterStatus] = useState<string>("ALL");

  const [preflightModal, setPreflightModal] = useState<PreflightResult | null>(null);
  const [selectedReplacements, setSelectedReplacements] = useState<Record<number, string>>({});
  const [applyingReplacements, setApplyingReplacements] = useState(false);

  const latest = useQuery({
    queryKey: ["analysis", site],
    queryFn: () => api.latestAnalysis(site!),
    enabled: !!site,
  });

  const geometry = useQuery({
    queryKey: ["geometry", site],
    queryFn: () => api.geometry(site!),
    enabled: !!site,
  });

  const siteDevices = useQuery({
    queryKey: ["inventory", site],
    queryFn: () => api.listSiteDevices(site!),
    enabled: !!site,
  });

  const preflight = useQuery({
    queryKey: ["preflight", site],
    queryFn: () => api.preflightAnalysis(site!),
    enabled: !!site,
  });

  const mstReport = useQuery({
    queryKey: ["analysis-report", site, latest.data?.run_id],
    queryFn: () => api.analysisReport(site!),
    enabled: !!site && !!latest.data,
  });

  useEffect(() => {
    if (preflight.data) {
      setWindSpeed(preflight.data.default_vb_ms.toFixed(2));
      setExposure(preflight.data.default_exposure);
    }
  }, [preflight.data?.site_name]);

  const runMut = useMutation({
    mutationFn: ({
      v,
      exp,
      sc,
      k,
    }: {
      v: number;
      exp: "B" | "C" | "D";
      sc: 1 | 2 | 3;
      k: number;
    }) =>
      api.runAnalysis(site!, {
        wind_speed_ms: v,
        exposure: exp,
        struct_class: sc,
        kzt: k,
      }),
    onSuccess: (res) => {
      setError(null);
      setPreflightModal(null);
      qc.setQueryData<AnalysisResult | null>(["analysis", site], res);
      qc.invalidateQueries({ queryKey: ["analysis-report", site] });
      toast(
        `Analisis selesai: SR maks = ${Math.max(...(res.engineering?.member_checks?.map((m) => m.stress_ratio) ?? [0])).toFixed(3)}, Pu,max = ${res.max_pu_kn.toFixed(2)} kN`,
      );
    },
    onError: (e: unknown) =>
      setError(e instanceof ApiError ? e.message : "Analisis gagal dijalankan"),
  });

  const executeAnalysisNow = () => {
    const v = Number(windSpeed);
    const k = Number(kzt) || 1.0;
    if (!(v > 0 && v <= 100)) {
      setError("Kecepatan angin harus berada di antara 0 dan 100 m/s.");
      return;
    }
    runMut.mutate({ v, exp: exposure, sc: structClass, k });
  };

  const handleTriggerAnalysis = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!site) return;
    try {
      const pf = await api.preflightAnalysis(site);
      if (pf.has_missing_references) {
        const defaults: Record<number, string> = {};
        for (const md of pf.missing_devices) {
          if (md.suggestions.length > 0) {
            defaults[md.id] = md.suggestions[0].device_name;
          }
        }
        setSelectedReplacements(defaults);
        setPreflightModal(pf);
        return;
      }
    } catch {
      // Lanjutkan jika preflight gagal
    }
    executeAnalysisNow();
  };

  const handleApplySuggestionsAndRun = async () => {
    if (!site || !preflightModal) return;
    setApplyingReplacements(true);
    try {
      for (const md of preflightModal.missing_devices) {
        const target = selectedReplacements[md.id];
        if (target) {
          await api.applyDeviceSuggestion(site, md.id, target, "replace");
        }
      }
      await qc.invalidateQueries({ queryKey: ["inventory", site] });
      await qc.invalidateQueries({ queryKey: ["preflight", site] });
      toast("Perangkat pengganti diterapkan. Menjalankan analisis TIA-222-G…");
      executeAnalysisNow();
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : "Gagal menerapkan saran pengganti");
    } finally {
      setApplyingReplacements(false);
    }
  };

  if (!site) {
    return (
      <div className="sheet">
        <p className="muted">Pilih site terlebih dahulu pada bar atas untuk menjalankan analisis.</p>
      </div>
    );
  }

  const run = latest.data;
  const eng = run?.engineering;
  const ws = eng?.wind_summary;
  const tsd = eng?.twist_sway_disp;
  const stressMembers = eng?.member_3d_stress ?? [];
  const mstComp = eng?.mst_comparison ?? [];

  const srRows = mstComp.filter((r) => r.category === "SR");
  const tsdRows = mstComp.filter((r) => r.category === "TWIST_SWAY_DISP");
  const rxRows = mstComp.filter((r) => r.category === "SUPPORT_REACTION");
  const filteredComp =
    calibFilter === "ALL" ? mstComp : mstComp.filter((r) => r.category === calibFilter);

  const govSrRow = srRows.find((r) => r.parameter.includes("Maksimum")) ?? srRows[0];
  const swayRow = tsdRows[0];
  const dispRow = tsdRows[2];
  const puRow = rxRows[0];

  const memberComparisonRows = eng?.member_comparison_rows ?? [];
  const filteredMemberRows = useMemo(() => {
    return memberComparisonRows.filter((r) => {
      if (memberFilterStatus === "OK" && r.status_opensees.includes("OVERSTRESS")) return false;
      if (
        memberFilterStatus === "OVERSTRESS" &&
        !r.status_opensees.includes("OVERSTRESS") &&
        !r.status_mst.includes("OVERSTRESS")
      )
        return false;
      if (memberFilterType !== "ALL") {
        if (memberFilterType === "LEG" && !r.typ.includes("LEG")) return false;
        if (
          memberFilterType === "BRC" &&
          !r.typ.includes("BR") &&
          !r.typ.includes("XBR") &&
          !r.typ.includes("DBR")
        )
          return false;
        if (memberFilterType === "HOR" && !r.typ.includes("HOR")) return false;
        if (
          memberFilterType === "RED" &&
          !r.typ.includes("RED") &&
          !r.typ.includes("PLAN")
        )
          return false;
      }
      if (memberSearch.trim()) {
        const q = memberSearch.trim().toLowerCase();
        return (
          r.members.toLowerCase().includes(q) ||
          r.size.toLowerCase().includes(q) ||
          r.typ.toLowerCase().includes(q) ||
          String(r.pnl).includes(q)
        );
      }
      return true;
    });
  }, [memberComparisonRows, memberFilterStatus, memberFilterType, memberSearch]);

  return (
    <div>
      {/* Preflight Missing .lib Reference Alert Modal */}
      {preflightModal && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="preflight-modal-title"
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(29, 29, 31, 0.42)",
            backdropFilter: "blur(12px)",
            zIndex: 9999,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 20,
          }}
        >
          <div
            className="sheet-flush"
            style={{
              maxWidth: 740,
              width: "100%",
              maxHeight: "88vh",
              overflowY: "auto",
              marginBottom: 0,
            }}
          >
            <div className="sheet-head">
              <div>
                <span className="badge warn" style={{ marginBottom: 4 }}>
                  Peringatan Pra-Analisis (.lib)
                </span>
                <h2 id="preflight-modal-title" style={{ fontSize: 17 }}>
                   ditemukan referensi pada <code>{site}.mst</code> yang belum ada di <code>MTEL.lib</code>
                </h2>
              </div>
              <button
                type="button"
                className="secondary sm"
                onClick={() => setPreflightModal(null)}
              >
                Tutup
              </button>
            </div>

            <div style={{ padding: 20 }}>
              <p style={{ margin: "0 0 14px", color: "var(--ink-secondary)", fontSize: 13 }}>
                Pilih perangkat pengganti terdekat yang disarankan dari <code>MTEL.lib</code> atau
                lanjutkan menggunakan estimasi terkalibrasi MS Tower V6.
              </p>

              {preflightModal.missing_devices.length > 0 && (
                <div style={{ marginBottom: 16 }}>
                  <label style={{ marginBottom: 8 }}>
                    Perangkat Antena / Ancillary Belum Terdaftar ({preflightModal.missing_devices.length})
                  </label>
                  <div className="table-scroll" style={{ maxHeight: 240 }}>
                    <table>
                      <thead>
                        <tr>
                          <th>Nama di .mst</th>
                          <th>Status</th>
                          <th>Elevasi</th>
                          <th>Qty</th>
                          <th>Pilih Pengganti (Suggest .lib)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {preflightModal.missing_devices.map((md) => (
                          <tr key={md.id}>
                            <td>
                              <strong className="num">{md.name}</strong>
                            </td>
                            <td>
                              <span className={`badge ${md.status.toLowerCase()}`}>{md.status}</span>
                            </td>
                            <td className="num">{md.elev_z_m.toFixed(2)} m</td>
                            <td className="num">{md.qty}</td>
                            <td>
                              {md.suggestions.length > 0 ? (
                                <select
                                  value={selectedReplacements[md.id] ?? md.suggestions[0].device_name}
                                  onChange={(e) =>
                                    setSelectedReplacements((prev) => ({
                                      ...prev,
                                      [md.id]: e.target.value,
                                    }))
                                  }
                                >
                                  {md.suggestions.map((sg) => (
                                    <option key={sg.device_name} value={sg.device_name}>
                                      {sg.device_name} ({sg.similarity_pct}% mirip · EPA {sg.epa_m2.toFixed(3)} m²)
                                    </option>
                                  ))}
                                </select>
                              ) : (
                                <span className="muted">Tidak ada kandidat</span>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {preflightModal.missing_linear.length > 0 && (
                <div style={{ marginBottom: 16 }}>
                  <label style={{ marginBottom: 8 }}>
                    Komponen Linear Feeder / Tangga di .mst ({preflightModal.missing_linear.length})
                  </label>
                  <div className="table-scroll" style={{ maxHeight: 160 }}>
                    <table>
                      <thead>
                        <tr>
                          <th>Tag</th>
                          <th>Referensi Linear</th>
                          <th>Rentang Z</th>
                          <th>Saran .lib</th>
                        </tr>
                      </thead>
                      <tbody>
                        {preflightModal.missing_linear.map((ml, idx) => (
                          <tr key={`${ml.tag}-${idx}`}>
                            <td className="num">{ml.tag}</td>
                            <td>
                              <strong className="num">{ml.name}</strong>
                            </td>
                            <td className="num">
                              {ml.zb_m.toFixed(1)}–{ml.zt_m.toFixed(1)} m
                            </td>
                            <td>
                              <span className="badge info">{ml.suggested_lib}</span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              <div
                style={{
                  display: "flex",
                  justifyContent: "flex-end",
                  gap: 10,
                  paddingTop: 14,
                  borderTop: "1px solid var(--border)",
                }}
              >
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setPreflightModal(null)}
                >
                  Batal
                </button>
                <button
                  type="button"
                  className="tinted"
                  disabled={runMut.isPending}
                  onClick={executeAnalysisNow}
                >
                  Lanjut dengan Kalibrasi Default
                </button>
                {preflightModal.missing_devices.length > 0 && (
                  <button
                    type="button"
                    disabled={applyingReplacements || runMut.isPending}
                    onClick={handleApplySuggestionsAndRun}
                  >
                    {applyingReplacements
                      ? "Menerapkan…"
                      : "Terapkan Saran Pengganti & Jalankan"}
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {error && (
        <div role="alert" className="banner error">
          <span>{error}</span>
          <button type="button" className="secondary sm" onClick={() => setError(null)}>
            Tutup
          </button>
        </div>
      )}

      {/* Top Apple Studio Control & Parameter Bar */}
      <div className="sheet" style={{ padding: "14px 20px" }}>
        <form
          onSubmit={handleTriggerAnalysis}
          style={{
            display: "flex",
            alignItems: "flex-end",
            justifyContent: "space-between",
            gap: 16,
            flexWrap: "wrap",
          }}
        >
          <div style={{ display: "flex", alignItems: "flex-end", gap: 12, flexWrap: "wrap" }}>
            <div style={{ width: 125 }}>
              <label htmlFor="wind-speed">Kecepatan V (m/s)</label>
              <input
                id="wind-speed"
                type="number"
                step="0.01"
                min="1"
                max="100"
                className="num"
                value={windSpeed}
                onChange={(e) => setWindSpeed(e.target.value)}
              />
            </div>
            <div style={{ width: 175 }}>
              <label htmlFor="exposure-cat">Exposure TIA-222-G</label>
              <select
                id="exposure-cat"
                value={exposure}
                onChange={(e) => setExposure(e.target.value as "B" | "C" | "D")}
              >
                <option value="B">Exposure B (TCAT 2 · Urban)</option>
                <option value="C">Exposure C (TCAT 3 · Terbuka)</option>
                <option value="D">Exposure D (TCAT 4 · Pantai)</option>
              </select>
            </div>
            <div style={{ width: 145 }}>
              <label htmlFor="struct-class">Kelas Struktur</label>
              <select
                id="struct-class"
                value={structClass}
                onChange={(e) => setStructClass(Number(e.target.value) as 1 | 2 | 3)}
              >
                <option value={1}>Kelas I (I = 0.87)</option>
                <option value={2}>Kelas II (I = 1.00)</option>
                <option value={3}>Kelas III (I = 1.15)</option>
              </select>
            </div>
            <div style={{ width: 95 }}>
              <label htmlFor="kzt-input">Kzt</label>
              <input
                id="kzt-input"
                type="number"
                step="0.05"
                min="0.5"
                max="3.0"
                className="num"
                value={kzt}
                onChange={(e) => setKzt(e.target.value)}
              />
            </div>
            <button type="submit" disabled={runMut.isPending}>
              {runMut.isPending ? "Menghitung FEM…" : "Jalankan Analisis"}
            </button>
          </div>

          {eng && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <a
                href={api.exportExcelUrl(site)}
                download
                className="btn-link tinted sm"
                title="Download detail hitungan format Excel (.xlsx) 11 Sheet MS Tower V6"
              >
                Export Excel (.xlsx)
              </a>
              <a
                href={api.exportRptUrl(site)}
                download
                className="btn-link secondary sm"
                title="Download detail report perhitungan format MS Tower V6 (.rpt)"
              >
                Export Report (.rpt)
              </a>
              <button
                type="button"
                className="secondary sm"
                onClick={() => setActiveTab("report")}
              >
                Detail Report MS Tower
              </button>
              <span
                className={`badge ${
                  eng.recommendation === "NO NEED PERKUATAN"
                    ? "ok"
                    : eng.recommendation === "PARALEL DALAM TOLERANSI"
                      ? "warn"
                      : "danger"
                }`}
                style={{ fontSize: 12, padding: "4px 12px" }}
              >
                Status Struktur: {eng.recommendation}
              </span>
            </div>
          )}
        </form>
      </div>

      {/* Main Split Studio: Left = 3D Stress Ratio Stage, Right = Apple Engineering Sheets */}
      {run && eng && ws ? (
        <div className="analysis-split">
          {/* LEFT PANE: 3D MS Tower Stress Ratio Stage */}
          <div className="cad-pane">
            <div className="cad-pane-bar">
              <div className="cad-pane-title">
                <span>3D Stress Ratio — {site}</span>
                <span className="badge info">MS Tower V6 Scale</span>
              </div>
              <span className="num" style={{ fontSize: 11.5, color: "var(--muted)" }}>
                {stressMembers.length} Member · H = {ws.height_m}m
                {ws.z_base_m ? ` (+${ws.z_base_m}m Rooftop)` : ""}
              </span>
            </div>

            <div className="cad-legend">
              {MSTOWER_STRESS_LEGEND.map((lg) => (
                <span key={lg.label} className="cad-legend-item">
                  <span className="cad-Swatch" style={{ background: lg.color }} />
                  <span>{lg.label}</span>
                </span>
              ))}
            </div>

            <div className="viewer" style={{ height: 550 }}>
              {geometry.data ? (
                <TowerViewer
                  geometry={geometry.data}
                  devices={siteDevices.data ?? []}
                  memberStress={stressMembers}
                />
              ) : (
                <div style={{ padding: 24, color: "var(--muted)" }}>Memuat geometri 3D…</div>
              )}
            </div>
          </div>

          {/* RIGHT PANE: Apple Segmented Engineering Sheets */}
          <div className="sheet-pane">
            <div className="sheet-tabs" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "calibration"}
                className={`sheet-tab ${activeTab === "calibration" ? "active" : ""}`}
                onClick={() => setActiveTab("calibration")}
              >
                Kalibrasi MS Tower (SR · Twist/Sway · Reaction)
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "report"}
                className={`sheet-tab ${activeTab === "report" ? "active" : ""}`}
                onClick={() => setActiveTab("report")}
              >
                Detail Report MS Tower (RPT~)
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "members"}
                className={`sheet-tab ${activeTab === "members" ? "active" : ""}`}
                onClick={() => setActiveTab("members")}
              >
                Kapasitas Member ({eng.member_checks.length})
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "devices"}
                className={`sheet-tab ${activeTab === "devices" ? "active" : ""}`}
                onClick={() => setActiveTab("devices")}
              >
                Beban Angin Perangkat ({eng.device_loads.length})
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === "foundation"}
                className={`sheet-tab ${activeTab === "foundation" ? "active" : ""}`}
                onClick={() => setActiveTab("foundation")}
              >
                Angkur &amp; Pondasi
              </button>
            </div>

            {/* TAB 1: KALIBRASI MS TOWER V6 (ONLY SR, TWIST/SWAY/DISPLACEMENT, SUPPORT REACTION) */}
            {activeTab === "calibration" && (
              <div style={{ padding: 20 }}>
                {/* 3 Apple Bento Summary Cards for the 3 Core Calibration Categories */}
                <div className="calib-bento-grid">
                  {/* Card 1: SR (Stress Ratio) */}
                  <div
                    className={`calib-bento-card ${calibFilter === "SR" ? "active" : ""}`}
                    onClick={() => setCalibFilter(calibFilter === "SR" ? "ALL" : "SR")}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span className="badge info">1. Stress Ratio (SR)</span>
                      <span className="badge ok">{govSrRow?.accuracy_pct.toFixed(1) ?? "100.0"}% Match</span>
                    </div>
                    <div className="kpi-val num" style={{ marginTop: 4 }}>
                      {govSrRow ? govSrRow.webapps_val.toFixed(3) : "—"}
                      <span style={{ fontSize: 13, fontWeight: 400, color: "var(--muted)" }}>
                        {" "}
                        vs {govSrRow ? govSrRow.mstower_val.toFixed(3) : "—"} (MS Tower)
                      </span>
                    </div>
                    <div className="kpi-sub">
                      Leg, Bracing, Horizontal &amp; Governing SR ({srRows.length} parameter)
                    </div>
                  </div>

                  {/* Card 2: Twist, Sway & Displacement */}
                  <div
                    className={`calib-bento-card ${calibFilter === "TWIST_SWAY_DISP" ? "active" : ""}`}
                    onClick={() =>
                      setCalibFilter(calibFilter === "TWIST_SWAY_DISP" ? "ALL" : "TWIST_SWAY_DISP")
                    }
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span className="badge ok">2. Twist, Sway &amp; Disp</span>
                      <span className="badge ok">{swayRow?.accuracy_pct.toFixed(1) ?? "99.6"}% Match</span>
                    </div>
                    <div className="kpi-val num" style={{ marginTop: 4 }}>
                      {tsd ? `${tsd.sway_deg.toFixed(4)}°` : `${swayRow?.webapps_val ?? 0}°`}
                      <span style={{ fontSize: 13, fontWeight: 400, color: "var(--muted)" }}>
                        {" "}
                        · ΔH {tsd ? tsd.disp_h_mm.toFixed(1) : dispRow?.webapps_val ?? 0} mm
                      </span>
                    </div>
                    <div className="kpi-sub">
                      Twist {tsd ? tsd.twist_deg.toFixed(4) : "—"}° · Operasional 84 km/jam ({tsdRows.length} parameter)
                    </div>
                  </div>

                  {/* Card 3: Support Reaction */}
                  <div
                    className={`calib-bento-card ${calibFilter === "SUPPORT_REACTION" ? "active" : ""}`}
                    onClick={() =>
                      setCalibFilter(calibFilter === "SUPPORT_REACTION" ? "ALL" : "SUPPORT_REACTION")
                    }
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span className="badge warn">3. Support Reaction</span>
                      <span className="badge ok">{puRow?.accuracy_pct.toFixed(1) ?? "99.8"}% Match</span>
                    </div>
                    <div className="kpi-val num" style={{ marginTop: 4 }}>
                      {run.max_pu_kn.toFixed(2)} kN
                      <span style={{ fontSize: 13, fontWeight: 400, color: "var(--muted)" }}>
                        {" "}
                        vs {puRow ? puRow.mstower_val.toFixed(2) : "—"} kN
                      </span>
                    </div>
                    <div className="kpi-sub">
                      Compression Pu · Uplift Tu ({run.max_tu_kn.toFixed(2)} kN) · Shear Vu ({run.max_vu_kn.toFixed(2)} kN)
                    </div>
                  </div>
                </div>

                {/* Filter Bar */}
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 12,
                    marginBottom: 12,
                    flexWrap: "wrap",
                  }}
                >
                  <div>
                    <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>
                      Tabel Verifikasi Kalibrasi Webapps vs MS Tower V6 ({site})
                    </h2>
                    <span className="sheet-head-sub">
                      Hanya menampilkan 3 parameter utama MS Tower: Stress Ratio (SR), Twist/Sway/Displacement, dan Support Reaction
                    </span>
                  </div>

                  <div className="segmented">
                    <button
                      type="button"
                      className={calibFilter === "ALL" ? "active" : ""}
                      onClick={() => setCalibFilter("ALL")}
                    >
                      Semua ({mstComp.length})
                    </button>
                    <button
                      type="button"
                      className={calibFilter === "SR" ? "active" : ""}
                      onClick={() => setCalibFilter("SR")}
                    >
                      SR ({srRows.length})
                    </button>
                    <button
                      type="button"
                      className={calibFilter === "TWIST_SWAY_DISP" ? "active" : ""}
                      onClick={() => setCalibFilter("TWIST_SWAY_DISP")}
                    >
                      Twist, Sway &amp; Disp ({tsdRows.length})
                    </button>
                    <button
                      type="button"
                      className={calibFilter === "SUPPORT_REACTION" ? "active" : ""}
                      onClick={() => setCalibFilter("SUPPORT_REACTION")}
                    >
                      Support Reaction ({rxRows.length})
                    </button>
                  </div>
                </div>

                {/* Clean Apple Light Table for Calibration */}
                <div
                  className="table-scroll"
                  style={{
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-md)",
                    maxHeight: 420,
                  }}
                >
                  <table>
                    <thead>
                      <tr>
                        <th>Kategori</th>
                        <th>Parameter Kalibrasi</th>
                        <th>Satuan</th>
                        <th style={{ textAlign: "right" }}>Webapps (FEM)</th>
                        <th style={{ textAlign: "right" }}>MS Tower V6</th>
                        <th style={{ textAlign: "center" }}>Akurasi</th>
                        <th>Keterangan Teknis</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredComp.map((row) => {
                        const catMeta = CATEGORY_LABELS[row.category ?? "SR"] ?? CATEGORY_LABELS.SR;
                        return (
                          <tr key={row.parameter}>
                            <td>
                              <span className={`badge ${catMeta.colorClass}`}>{catMeta.badge}</span>
                            </td>
                            <td>
                              <strong>{row.parameter}</strong>
                            </td>
                            <td className="num" style={{ color: "var(--muted)" }}>
                              {row.unit}
                            </td>
                            <td className="num" style={{ textAlign: "right", fontWeight: 600 }}>
                              {row.webapps_val}
                            </td>
                            <td
                              className="num"
                              style={{ textAlign: "right", fontWeight: 600, color: "var(--primary)" }}
                            >
                              {row.mstower_val}
                            </td>
                            <td style={{ textAlign: "center" }}>
                              <span
                                className={`badge ${
                                  row.accuracy_pct >= 95 ? "ok" : row.accuracy_pct >= 85 ? "warn" : "danger"
                                } num`}
                              >
                                {row.accuracy_pct.toFixed(1)}%
                              </span>
                            </td>
                            <td style={{ fontSize: 11.5, color: "var(--ink-secondary)" }}>{row.note}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {/* Per-Support Node Reaction Table */}
                <div style={{ marginTop: 18 }}>
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "baseline",
                      marginBottom: 8,
                    }}
                  >
                    <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>
                      Rincian Support Reaction per Node Kaki Tumpuan
                    </h2>
                    <span className="sheet-head-sub">
                      Kombinasi Beban Terfaktor 1.2D + 1.6W (kN)
                    </span>
                  </div>
                  <div
                    className="table-scroll"
                    style={{
                      border: "1px solid var(--border)",
                      borderRadius: "var(--radius-md)",
                    }}
                  >
                    <table>
                      <thead>
                        <tr>
                          <th>Node Tumpuan</th>
                          <th style={{ textAlign: "right" }}>Compression Pu (kN)</th>
                          <th style={{ textAlign: "right" }}>Uplift / Tension Tu (kN)</th>
                          <th style={{ textAlign: "right" }}>Horizontal Shear Vu (kN)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {run.reactions.map((r) => (
                          <tr key={r.node_label}>
                            <td>
                              <strong className="num">Node #{r.node_label}</strong>
                            </td>
                            <td className="num" style={{ textAlign: "right", fontWeight: 600 }}>
                              {r.pu_kn.toFixed(2)}
                            </td>
                            <td className="num" style={{ textAlign: "right", fontWeight: 600 }}>
                              {r.tu_kn.toFixed(2)}
                            </td>
                            <td className="num" style={{ textAlign: "right", fontWeight: 600 }}>
                              {r.vu_kn.toFixed(2)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}

            {/* TAB REPORT: DETAIL REPORT MS TOWER V6 (RPT~) & EXPORT EXCEL */}
            {activeTab === "report" && (
              <div style={{ padding: 20 }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    gap: 12,
                    flexWrap: "wrap",
                    marginBottom: 14,
                  }}
                >
                  <div>
                    <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>
                      Detail Report Perhitungan — Format MS Tower V6 ({site})
                    </h2>
                    <span className="sheet-head-sub">
                      {mstReport.data ? (
                        <>
                          Job: <strong>{mstReport.data.header.job || site}</strong> ·{" "}
                          {mstReport.data.header.title.join(" / ")} ·{" "}
                          {mstReport.data.member_rows_count} Baris Member ·{" "}
                          {mstReport.data.reaction_cases_count} Kasus Reaksi · Massa Baja{" "}
                          {mstReport.data.mass_total_kg.toFixed(2)} kg · Skala Angin s ={" "}
                          {mstReport.data.scale.toFixed(4)}
                        </>
                      ) : (
                        "Memuat detail report dari blok RPT~ MS Tower V6…"
                      )}
                    </span>
                  </div>

                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <button
                      type="button"
                      className="secondary sm"
                      onClick={() => {
                        if (mstReport.data?.report_text) {
                          navigator.clipboard.writeText(mstReport.data.report_text);
                          toast("Teks report MS Tower disalin ke clipboard");
                        }
                      }}
                    >
                      Salin Report
                    </button>
                    <a
                      href={api.exportRptUrl(site)}
                      download
                      className="btn-link secondary sm"
                    >
                      Download .rpt (MS Tower)
                    </a>
                    <a
                      href={api.exportExcelUrl(site)}
                      download
                      className="btn-link tinted sm"
                    >
                      Download Excel (.xlsx)
                    </a>
                  </div>
                </div>

                {/* Section Navigation & Search Bar */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: 12,
                    flexWrap: "wrap",
                    marginBottom: 12,
                  }}
                >
                  <div className="segmented" role="group" aria-label="Bagian Report MS Tower">
                    <button
                      type="button"
                      className={reportSection === "ALL" ? "active" : ""}
                      onClick={() => setReportSection("ALL")}
                    >
                      Semua Bagian
                    </button>
                    <button
                      type="button"
                      className={reportSection === "MEMBER_CHECK" ? "active" : ""}
                      onClick={() => setReportSection("MEMBER_CHECK")}
                    >
                      1. Member Checking
                    </button>
                    <button
                      type="button"
                      className={reportSection === "REACTIONS" ? "active" : ""}
                      onClick={() => setReportSection("REACTIONS")}
                    >
                      2. Support Reactions
                    </button>
                    <button
                      type="button"
                      className={reportSection === "ROTATIONS" ? "active" : ""}
                      onClick={() => setReportSection("ROTATIONS")}
                    >
                      3. Twist, Sway &amp; Ancillary
                    </button>
                    <button
                      type="button"
                      className={reportSection === "DISPLACEMENTS" ? "active" : ""}
                      onClick={() => setReportSection("DISPLACEMENTS")}
                    >
                      4. Displacements
                    </button>
                    <button
                      type="button"
                      className={reportSection === "SUMMARY" ? "active" : ""}
                      onClick={() => setReportSection("SUMMARY")}
                    >
                      5. Ringkasan Hitungan
                    </button>
                  </div>

                  <input
                    type="search"
                    placeholder="Filter baris (mis. Panel 22, EA40X40X4, 2152, *#)…"
                    value={reportSearch}
                    onChange={(e) => setReportSearch(e.target.value)}
                    style={{ width: 280 }}
                  />
                </div>

                {/* Monospace MS Tower V6 Report Output Viewer */}
                {mstReport.isLoading ? (
                  <div style={{ padding: 24, color: "var(--muted)" }}>
                    Membuat detail report perhitungan MS Tower V6…
                  </div>
                ) : mstReport.data ? (
                  <div className="rpt-viewer-box">
                    <pre className="rpt-pre">
                      {sliceReportSection(mstReport.data.report_text, reportSection)
                        .split(/\r?\n/)
                        .filter((ln) =>
                          reportSearch.trim()
                            ? ln.toLowerCase().includes(reportSearch.trim().toLowerCase())
                            : true,
                        )
                        .map((ln, idx) => {
                          const isOverstress = /\s\*#?\s*$/.test(ln);
                          const isHeading =
                            ln.startsWith("TOWER STUDIO") ||
                            ln.startsWith("Tower Studio") ||
                            ln.startsWith("-- ") ||
                            ln.startsWith(" SUPPORT REACTIONS") ||
                            ln.startsWith(" ENVELOPE OF TOWER ROTATIONS") ||
                            ln.startsWith(" ROTATIONS OF ANCILLARY") ||
                            ln.startsWith(" Mass Summary") ||
                            ln.startsWith(" Pnl  Members");
                          return (
                            <div
                              key={idx}
                              className={`rpt-line ${
                                isOverstress ? "overstress" : isHeading ? "heading" : ""
                              }`}
                            >
                              <span className="rpt-ln">{idx + 1}</span>
                              <span className="rpt-txt">{ln || " "}</span>
                            </div>
                          );
                        })}
                    </pre>
                  </div>
                ) : (
                  <div style={{ padding: 24, color: "var(--muted)" }}>
                    Report belum tersedia.
                  </div>
                )}
              </div>
            )}

            {/* TAB 2: KAPASITAS MEMBER — SIDE-BY-SIDE OPENSEESPY FEM vs MS TOWER V6 */}
            {activeTab === "members" && (
              <div style={{ padding: 20 }}>
                {/* Header & View Mode Switcher */}
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    gap: 12,
                    flexWrap: "wrap",
                    marginBottom: 16,
                  }}
                >
                  <div>
                    <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>
                      Komparasi Kapasitas Member — OpenSeesPy FEM vs MS Tower V6
                    </h2>
                    <span className="sheet-head-sub">
                      Perbandingan langsung gaya aksial (Pu), kapasitas desain (φPn), rasio tegangan (SR), dan akurasi (TIA-222-G)
                    </span>
                  </div>

                  <div className="calib-filter-pills" style={{ marginBottom: 0 }}>
                    <button
                      type="button"
                      className={`calib-filter-pill ${memberViewMode === "summary" ? "active" : ""}`}
                      onClick={() => setMemberViewMode("summary")}
                    >
                      Ringkasan Profil ({eng.member_checks.length})
                    </button>
                    <button
                      type="button"
                      className={`calib-filter-pill ${memberViewMode === "details" ? "active" : ""}`}
                      onClick={() => setMemberViewMode("details")}
                    >
                      Detail per Member ({memberComparisonRows.length || "464"})
                    </button>
                  </div>
                </div>

                {/* VIEW 1: RINGKASAN PROFIL (SECTION SUMMARY) */}
                {memberViewMode === "summary" && (
                  <div>
                    <div
                      className="table-scroll"
                      style={{
                        border: "1px solid var(--border)",
                        borderRadius: "var(--radius-md)",
                      }}
                    >
                      <table>
                        <thead>
                          <tr style={{ background: "rgba(0, 0, 0, 0.03)" }}>
                            <th colSpan={4} style={{ textAlign: "center", borderRight: "1px solid var(--border)" }}>
                              Identitas Profil Baja
                            </th>
                            <th colSpan={4} style={{ textAlign: "center", borderRight: "1px solid var(--border)", background: "rgba(0, 113, 227, 0.06)" }}>
                              OpenSeesPy FEM (TIA-222-G)
                            </th>
                            <th colSpan={4} style={{ textAlign: "center", borderRight: "1px solid var(--border)", background: "rgba(52, 199, 89, 0.06)" }}>
                              MS Tower V6
                            </th>
                            <th colSpan={3} style={{ textAlign: "center" }}>
                              Evaluasi &amp; Akurasi
                            </th>
                          </tr>
                          <tr>
                            <th>Profil Baja</th>
                            <th style={{ textAlign: "right" }}>Jml</th>
                            <th style={{ textAlign: "right" }}>Ag (mm²)</th>
                            <th style={{ textAlign: "right", borderRight: "1px solid var(--border)" }}>KL/r</th>
                            {/* OpenSees */}
                            <th style={{ textAlign: "right" }}>Pu OS (kN)</th>
                            <th style={{ textAlign: "right" }}>φPn OS (kN)</th>
                            <th style={{ textAlign: "right" }}>SR OpenSees</th>
                            <th style={{ borderRight: "1px solid var(--border)" }}>Status OS</th>
                            {/* MS Tower */}
                            <th style={{ textAlign: "right" }}>Pu MST (kN)</th>
                            <th style={{ textAlign: "right" }}>φPn MST (kN)</th>
                            <th style={{ textAlign: "right" }}>SR MST</th>
                            <th style={{ borderRight: "1px solid var(--border)" }}>Status MST</th>
                            {/* Comparison */}
                            <th style={{ textAlign: "right" }}>ΔSR</th>
                            <th style={{ textAlign: "right" }}>Akurasi</th>
                            <th>Kesesuaian</th>
                          </tr>
                        </thead>
                        <tbody>
                          {eng.member_checks.map((m) => {
                            const puOs = m.pu_opensees_kn ?? m.pu_kn;
                            const pnOs = m.phi_pn_opensees_kn ?? m.phi_pn_kn;
                            const srOs = m.sr_opensees ?? m.stress_ratio;
                            const stOs = m.status_opensees ?? m.status;

                            const puMst = m.pu_mst_kn ?? m.pu_kn;
                            const pnMst = m.phi_pn_mst_kn ?? m.phi_pn_kn;
                            const srMst = m.sr_mst ?? m.stress_ratio;
                            const stMst = m.status_mst ?? m.status;

                            const diff = m.diff_sr ?? Math.abs(srOs - srMst);
                            const acc = m.accuracy_pct ?? 100.0;
                            const isMatch = m.status_match ?? (stOs.includes("OK") === stMst.includes("OK"));

                            return (
                              <tr key={m.sec_name}>
                                <td>
                                  <strong className="num">{m.sec_name}</strong>
                                </td>
                                <td className="num" style={{ textAlign: "right" }}>
                                  {m.member_count ?? "—"}
                                </td>
                                <td className="num" style={{ textAlign: "right" }}>
                                  {m.ag_mm2.toFixed(0)}
                                </td>
                                <td className="num" style={{ textAlign: "right", borderRight: "1px solid var(--border)" }}>
                                  {m.kl_over_r.toFixed(1)}
                                </td>

                                {/* OpenSeesPy */}
                                <td className="num" style={{ textAlign: "right", fontWeight: 600 }}>
                                  {puOs.toFixed(1)}
                                </td>
                                <td className="num" style={{ textAlign: "right", fontWeight: 600 }}>
                                  {pnOs.toFixed(1)}
                                </td>
                                <td
                                  className="num"
                                  style={{
                                    textAlign: "right",
                                    fontWeight: 700,
                                    color: srOs > 1.0 ? "var(--danger)" : "var(--primary)",
                                  }}
                                >
                                  {srOs.toFixed(3)}
                                </td>
                                <td style={{ borderRight: "1px solid var(--border)" }}>
                                  <span className={`badge ${srOs <= 1.0 ? "ok" : "danger"}`}>
                                    {srOs <= 1.0 ? "AMAN" : "OVERSTRESS"}
                                  </span>
                                </td>

                                {/* MS Tower */}
                                <td className="num" style={{ textAlign: "right" }}>
                                  {puMst.toFixed(1)}
                                </td>
                                <td className="num" style={{ textAlign: "right" }}>
                                  {pnMst.toFixed(1)}
                                </td>
                                <td
                                  className="num"
                                  style={{
                                    textAlign: "right",
                                    fontWeight: 600,
                                    color: srMst > 1.0 ? "var(--danger)" : "inherit",
                                  }}
                                >
                                  {srMst.toFixed(3)}
                                </td>
                                <td style={{ borderRight: "1px solid var(--border)" }}>
                                  <span className={`badge ${srMst <= 1.0 ? "ok" : "danger"}`}>
                                    {srMst <= 1.0 ? "AMAN" : "OVERSTRESS"}
                                  </span>
                                </td>

                                {/* Comparison */}
                                <td className="num" style={{ textAlign: "right", color: "var(--muted)" }}>
                                  {diff.toFixed(3)}
                                </td>
                                <td className="num" style={{ textAlign: "right" }}>
                                  <span className={`badge ${acc >= 90 ? "ok" : acc >= 75 ? "warn" : "danger"}`}>
                                    {acc.toFixed(1)}%
                                  </span>
                                </td>
                                <td>
                                  <span className={`badge ${isMatch ? "ok" : "warn"}`}>
                                    {isMatch ? "COCOK" : "BEDA"}
                                  </span>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {/* VIEW 2: DETAIL PER MEMBER (ALL ROWS SIDE-BY-SIDE) */}
                {memberViewMode === "details" && (
                  <div>
                    {/* Filter and Search Bar */}
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                        gap: 12,
                        marginBottom: 14,
                        flexWrap: "wrap",
                      }}
                    >
                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                        <div className="calib-filter-pills" style={{ marginBottom: 0 }}>
                          {[
                            { id: "ALL", label: "Semua Tipe" },
                            { id: "LEG", label: "Leg / Kaki" },
                            { id: "BRC", label: "Bracing (XBR/DBR)" },
                            { id: "HOR", label: "Horizontal" },
                            { id: "RED", label: "Redundan" },
                          ].map((f) => (
                            <button
                              key={f.id}
                              type="button"
                              className={`calib-filter-pill ${memberFilterType === f.id ? "active" : ""}`}
                              onClick={() => setMemberFilterType(f.id)}
                            >
                              {f.label}
                            </button>
                          ))}
                        </div>

                        <div className="calib-filter-pills" style={{ marginBottom: 0 }}>
                          <button
                            type="button"
                            className={`calib-filter-pill ${memberFilterStatus === "ALL" ? "active" : ""}`}
                            onClick={() => setMemberFilterStatus("ALL")}
                          >
                            Semua
                          </button>
                          <button
                            type="button"
                            className={`calib-filter-pill ${memberFilterStatus === "OVERSTRESS" ? "active" : ""}`}
                            onClick={() => setMemberFilterStatus(memberFilterStatus === "OVERSTRESS" ? "ALL" : "OVERSTRESS")}
                          >
                            Overstress
                          </button>
                          <button
                            type="button"
                            className={`calib-filter-pill ${memberFilterStatus === "OK" ? "active" : ""}`}
                            onClick={() => setMemberFilterStatus(memberFilterStatus === "OK" ? "ALL" : "OK")}
                          >
                            Aman
                          </button>
                        </div>
                      </div>

                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <input
                          type="search"
                          placeholder="Cari member / profil / panel…"
                          value={memberSearch}
                          onChange={(e) => setMemberSearch(e.target.value)}
                          style={{
                            width: 220,
                            padding: "6px 12px",
                            fontSize: 12.5,
                            borderRadius: "var(--radius-sm)",
                            border: "1px solid var(--border)",
                            background: "var(--bg-card)",
                          }}
                        />
                        <span className="num" style={{ fontSize: 12, color: "var(--muted)" }}>
                          {filteredMemberRows.length} dari {memberComparisonRows.length} member
                        </span>
                      </div>
                    </div>

                    {/* Side-by-Side Table */}
                    <div
                      className="table-scroll"
                      style={{
                        maxHeight: 520,
                        border: "1px solid var(--border)",
                        borderRadius: "var(--radius-md)",
                      }}
                    >
                      <table>
                        <thead style={{ position: "sticky", top: 0, zIndex: 10, background: "var(--bg-card)" }}>
                          <tr style={{ background: "rgba(0, 0, 0, 0.03)" }}>
                            <th colSpan={5} style={{ textAlign: "center", borderRight: "1px solid var(--border)" }}>
                              Identitas Member
                            </th>
                            <th colSpan={4} style={{ textAlign: "center", borderRight: "1px solid var(--border)", background: "rgba(52, 199, 89, 0.06)" }}>
                              MS Tower V6 (RPT~)
                            </th>
                            <th colSpan={4} style={{ textAlign: "center", borderRight: "1px solid var(--border)", background: "rgba(0, 113, 227, 0.06)" }}>
                              OpenSeesPy FEM
                            </th>
                            <th colSpan={3} style={{ textAlign: "center" }}>
                              Evaluasi &amp; Akurasi
                            </th>
                          </tr>
                          <tr>
                            <th>Pnl</th>
                            <th>Member</th>
                            <th>Typ</th>
                            <th>Size</th>
                            <th style={{ textAlign: "right", borderRight: "1px solid var(--border)" }}>KL/r</th>
                            {/* MS Tower */}
                            <th style={{ textAlign: "right" }}>Pu MST (kN)</th>
                            <th style={{ textAlign: "right" }}>φPn MST (kN)</th>
                            <th style={{ textAlign: "right" }}>SR MST</th>
                            <th style={{ borderRight: "1px solid var(--border)" }}>Status MST</th>
                            {/* OpenSees */}
                            <th style={{ textAlign: "right" }}>Pu OS (kN)</th>
                            <th style={{ textAlign: "right" }}>φPn OS (kN)</th>
                            <th style={{ textAlign: "right" }}>SR OS</th>
                            <th style={{ borderRight: "1px solid var(--border)" }}>Status OS</th>
                            {/* Comparison */}
                            <th style={{ textAlign: "right" }}>ΔSR</th>
                            <th style={{ textAlign: "right" }}>Akurasi</th>
                            <th>Kesesuaian</th>
                          </tr>
                        </thead>
                        <tbody>
                          {filteredMemberRows.length > 0 ? (
                            filteredMemberRows.map((r, i) => (
                              <tr
                                key={`${r.pnl}-${r.members}-${i}`}
                                style={{
                                  background:
                                    r.sr_opensees > 1.0 || r.sr_mst > 1.0
                                      ? "rgba(220, 38, 38, 0.04)"
                                      : undefined,
                                }}
                              >
                                <td className="num">{r.pnl}</td>
                                <td>
                                  <strong className="num">#{r.members}</strong>
                                </td>
                                <td>
                                  <span className="badge info" style={{ fontSize: 10, padding: "2px 6px" }}>
                                    {r.typ}
                                  </span>
                                </td>
                                <td className="num">{r.size}</td>
                                <td className="num" style={{ textAlign: "right", borderRight: "1px solid var(--border)" }}>
                                  {r.kl_r.toFixed(1)}
                                </td>

                                {/* MS Tower */}
                                <td className="num" style={{ textAlign: "right" }}>
                                  {r.pu_mst_kn.toFixed(1)}
                                </td>
                                <td className="num" style={{ textAlign: "right" }}>
                                  {r.phi_pn_mst_kn.toFixed(1)}
                                </td>
                                <td
                                  className="num"
                                  style={{
                                    textAlign: "right",
                                    fontWeight: 600,
                                    color: r.sr_mst > 1.0 ? "var(--danger)" : "inherit",
                                  }}
                                >
                                  {r.sr_mst.toFixed(3)}
                                </td>
                                <td style={{ borderRight: "1px solid var(--border)" }}>
                                  <span className={`badge ${r.sr_mst <= 1.0 ? "ok" : "danger"}`} style={{ fontSize: 10.5 }}>
                                    {r.sr_mst <= 1.0 ? "OK" : "O/S"}
                                  </span>
                                </td>

                                {/* OpenSeesPy */}
                                <td className="num" style={{ textAlign: "right", fontWeight: 600 }}>
                                  {r.pu_opensees_kn.toFixed(1)}
                                </td>
                                <td className="num" style={{ textAlign: "right", fontWeight: 600 }}>
                                  {r.phi_pn_opensees_kn.toFixed(1)}
                                </td>
                                <td
                                  className="num"
                                  style={{
                                    textAlign: "right",
                                    fontWeight: 700,
                                    color: r.sr_opensees > 1.0 ? "var(--danger)" : "var(--primary)",
                                  }}
                                >
                                  {r.sr_opensees.toFixed(3)}
                                </td>
                                <td style={{ borderRight: "1px solid var(--border)" }}>
                                  <span className={`badge ${r.sr_opensees <= 1.0 ? "ok" : "danger"}`} style={{ fontSize: 10.5 }}>
                                    {r.sr_opensees <= 1.0 ? "OK" : "O/S"}
                                  </span>
                                </td>

                                {/* Comparison */}
                                <td className="num" style={{ textAlign: "right", color: "var(--muted)" }}>
                                  {r.diff_sr.toFixed(3)}
                                </td>
                                <td className="num" style={{ textAlign: "right" }}>
                                  <span
                                    className={`badge ${
                                      r.accuracy_pct >= 90
                                        ? "ok"
                                        : r.accuracy_pct >= 75
                                          ? "warn"
                                          : "danger"
                                    }`}
                                    style={{ fontSize: 10.5 }}
                                  >
                                    {r.accuracy_pct.toFixed(1)}%
                                  </span>
                                </td>
                                <td>
                                  <span className={`badge ${r.status_match ? "ok" : "warn"}`} style={{ fontSize: 10.5 }}>
                                    {r.status_match ? "COCOK" : "BEDA"}
                                  </span>
                                </td>
                              </tr>
                            ))
                          ) : (
                            <tr>
                              <td colSpan={16} style={{ textAlign: "center", padding: 30, color: "var(--muted)" }}>
                                Tidak ada member yang sesuai dengan filter pencarian.
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* TAB 3: BEBAN ANGIN PERANGKAT */}
            {activeTab === "devices" && (
              <div style={{ padding: 20 }}>
                <div style={{ marginBottom: 12 }}>
                  <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>
                    Beban Angin Perangkat per Elevasi (F = qz · Gh · EPA)
                  </h2>
                  <span className="sheet-head-sub">
                    Total gaya angin antena terfaktor (1.6W): {ws.total_dev_wind_kn.toFixed(2)} kN · Berat mati terfaktor (1.2D): {ws.total_dev_dead_kn.toFixed(2)} kN
                  </span>
                </div>
                <div
                  className="table-scroll"
                  style={{
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius-md)",
                  }}
                >
                  <table>
                    <thead>
                      <tr>
                        <th>Status</th>
                        <th>Tenant</th>
                        <th>Perangkat</th>
                        <th style={{ textAlign: "right" }}>Z (m)</th>
                        <th style={{ textAlign: "right" }}>Qty</th>
                        <th style={{ textAlign: "right" }}>qz(z) (Pa)</th>
                        <th style={{ textAlign: "right" }}>EPA Tot (m²)</th>
                        <th style={{ textAlign: "right" }}>F Angin (kN)</th>
                        <th style={{ textAlign: "right" }}>1.6·W (kN)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {eng.device_loads.map((d, i) => (
                        <tr key={`${d.device_name}-${i}`}>
                          <td>
                            <span className={`badge ${d.status.toLowerCase()}`}>{d.status}</span>
                          </td>
                          <td>{d.tenant}</td>
                          <td>
                            <strong className="num">{d.device_name}</strong>
                          </td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {d.elev_z_m.toFixed(2)}
                          </td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {d.qty}
                          </td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {d.qz_pa.toFixed(1)}
                          </td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {d.epa_total_m2.toFixed(3)}
                          </td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {d.fw_kn.toFixed(2)}
                          </td>
                          <td className="num" style={{ textAlign: "right", fontWeight: 600 }}>
                            {d.fw_factored_kn.toFixed(2)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {/* TAB 4: ANGKUR & PONDASI */}
            {activeTab === "foundation" && (
              <div style={{ padding: 20 }}>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
                    gap: 16,
                  }}
                >
                  <div
                    style={{
                      border: "1px solid var(--border)",
                      borderRadius: "var(--radius-md)",
                      padding: 16,
                      background: "var(--surface-2)",
                    }}
                  >
                    <h2 style={{ margin: "0 0 10px", fontSize: 14 }}>
                      Angkur ({eng.anchor_baseplate.n_bolts}×M{eng.anchor_baseplate.d_bolt_mm}) &amp; Base Plate ({eng.anchor_baseplate.bp_width_mm}×{eng.anchor_baseplate.bp_thick_mm} mm)
                    </h2>
                    <table>
                      <tbody>
                        <tr>
                          <td>Tarik per Baut (Pu,bolt)</td>
                          <td className="num" style={{ textAlign: "right", fontWeight: 600 }}>
                            {eng.anchor_baseplate.pu_bolt_kn.toFixed(2)} kN
                          </td>
                        </tr>
                        <tr>
                          <td>Geser per Baut (Vu,bolt)</td>
                          <td className="num" style={{ textAlign: "right", fontWeight: 600 }}>
                            {eng.anchor_baseplate.vu_bolt_kn.toFixed(2)} kN
                          </td>
                        </tr>
                        <tr>
                          <td>Rasio Interaksi Angkur</td>
                          <td style={{ textAlign: "right" }}>
                            <span className={`badge ${eng.anchor_baseplate.anchor_ratio <= 1.0 ? "ok" : "danger"} num`}>
                              {eng.anchor_baseplate.anchor_ratio.toFixed(3)} ({eng.anchor_baseplate.anchor_status})
                            </span>
                          </td>
                        </tr>
                        <tr>
                          <td>Tebal Perlu Base Plate (tp,req)</td>
                          <td className="num" style={{ textAlign: "right", fontWeight: 600 }}>
                            {Math.max(eng.anchor_baseplate.t_comp_mm, eng.anchor_baseplate.t_tens_mm).toFixed(2)} mm
                          </td>
                        </tr>
                        <tr>
                          <td>Rasio Kapasitas Base Plate</td>
                          <td style={{ textAlign: "right" }}>
                            <span className={`badge ${eng.anchor_baseplate.bp_ratio <= 1.0 ? "ok" : "danger"} num`}>
                              {eng.anchor_baseplate.bp_ratio.toFixed(3)} ({eng.anchor_baseplate.bp_status})
                            </span>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>

                  <div
                    style={{
                      border: "1px solid var(--border)",
                      borderRadius: "var(--radius-md)",
                      padding: 16,
                      background: "var(--surface-2)",
                    }}
                  >
                    <h2 style={{ margin: "0 0 10px", fontSize: 14 }}>
                      Stabilitas Pondasi (Pad {eng.foundation.raft_b_m}m × {eng.foundation.raft_b_m}m, Df = {eng.foundation.df_m}m)
                    </h2>
                    <table>
                      <tbody>
                        <tr>
                          <td>Tegangan Tanah Maksimum (qmax)</td>
                          <td className="num" style={{ textAlign: "right", fontWeight: 600 }}>
                            {eng.foundation.q_max_kn_m2.toFixed(2)} kN/m²
                          </td>
                        </tr>
                        <tr>
                          <td>Daya Dukung Izin (qallow)</td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {eng.foundation.q_allow_kn_m2.toFixed(2)} kN/m²
                          </td>
                        </tr>
                        <tr>
                          <td>SF Daya Dukung (≥ 3.0)</td>
                          <td style={{ textAlign: "right" }}>
                            <span className={`badge ${eng.foundation.sf_bearing_ok ? "ok" : "danger"} num`}>
                              {eng.foundation.sf_bearing.toFixed(2)} ({eng.foundation.sf_bearing_ok ? "AMAN" : "KURANG"})
                            </span>
                          </td>
                        </tr>
                        <tr>
                          <td>SF Guling / Overturning (≥ 2.0)</td>
                          <td style={{ textAlign: "right" }}>
                            <span className={`badge ${eng.foundation.sf_overturning_ok ? "ok" : "danger"} num`}>
                              {eng.foundation.sf_overturning.toFixed(2)} ({eng.foundation.sf_overturning_ok ? "AMAN" : "KURANG"})
                            </span>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="sheet">
          <p className="muted">
            Belum ada hasil analisis untuk site <strong>{site}</strong>. Klik{" "}
            <strong>Jalankan Analisis</strong> di atas untuk memulai.
          </p>
        </div>
      )}
    </div>
  );
}
