import { useState, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useToast } from "../components/Toast";
import type { SdaReportData, SdaScenarioData, SdaDeviceItem } from "../types";

export default function SdaExtractorPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [activeReportId, setActiveReportId] = useState<number | null>(null);
  const [activeScenario, setActiveScenario] = useState<string>("PROPOSED");
  const [activeFileTab, setActiveFileTab] = useState<"td" | "twr" | "rpt" | "p1">("td");
  const [runOpensees, setRunOpensees] = useState<boolean>(false);
  const [deviceFilter, setDeviceFilter] = useState<string>("");
  const [deviceStatusFilter, setDeviceStatusFilter] = useState<"ALL" | "EXISTING" | "PROPOSED">("ALL");

  // Query historical reports
  const reportsQuery = useQuery({
    queryKey: ["sda-reports"],
    queryFn: api.listSdaReports,
  });

  // Query active report details
  const reportQuery = useQuery({
    queryKey: ["sda-report", activeReportId],
    queryFn: () => (activeReportId ? api.getSdaReport(activeReportId) : null),
    enabled: !!activeReportId,
  });

  // Upload mutation
  const uploadMutation = useMutation({
    mutationFn: (file: File) => api.uploadSdaPdf(file, runOpensees),
    onSuccess: (data: SdaReportData) => {
      toast("Laporan PDF SDA berhasil diekstrak dan diproses!");
      qc.invalidateQueries({ queryKey: ["sda-reports"] });
      if (data.report_id) {
        setActiveReportId(data.report_id);
      }
      // Set active scenario to PROPOSED if available, else first scenario
      const scKeys = Object.keys(data.scenarios || {});
      if (scKeys.includes("PROPOSED")) {
        setActiveScenario("PROPOSED");
      } else if (scKeys.length > 0) {
        setActiveScenario(scKeys[0]);
      }
    },
    onError: (err: Error) => {
      toast(`Gagal mengekstrak PDF SDA: ${err.message}`);
    },
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      uploadMutation.mutate(file);
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (file && file.name.toLowerCase().endsWith(".pdf")) {
      uploadMutation.mutate(file);
    } else {
      toast("Silakan unggah file dokumen PDF (.pdf)");
    }
  };

  const reportData = reportQuery.data;
  const scenarios = reportData?.scenarios || {};
  const scenarioKeys = Object.keys(scenarios);
  const currentScenario: SdaScenarioData | undefined = scenarios[activeScenario] || (scenarioKeys.length > 0 ? scenarios[scenarioKeys[0]] : undefined);

  // Copy raw file text helper
  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    toast("Isi file berhasil disalin ke clipboard!");
  };

  // Filtered devices list
  const allDevices: SdaDeviceItem[] = [
    ...(currentScenario?.devices?.antennas || []),
    ...(currentScenario?.devices?.linear || []),
  ];
  const filteredDevices = allDevices.filter((d) => {
    const matchesFilter =
      !deviceFilter ||
      d.id.toLowerCase().includes(deviceFilter.toLowerCase()) ||
      (d.tenant && d.tenant.toLowerCase().includes(deviceFilter.toLowerCase())) ||
      (d.lib && d.lib.toLowerCase().includes(deviceFilter.toLowerCase()));
    const matchesStatus =
      deviceStatusFilter === "ALL" || d.status === deviceStatusFilter;
    return matchesFilter && matchesStatus;
  });

  return (
    <div className="sda-extractor-page">
      {/* Page Header */}
      <div className="section-head">
        <div>
          <h2>Import & Ekstraksi PDF Laporan SDA</h2>
          <p className="subtext">
            Ekstrak otomatis file native MS-Tower (.td, .twr, .rpt, .p1), inventori perangkat antena & feeder, serta resume hasil analisa struktur dari dokumen PDF SDA Konsultan.
          </p>
        </div>

        {reportData && activeReportId && (
          <div className="action-toolbar" style={{ display: "flex", gap: "0.5rem" }}>
            <a
              href={api.downloadSdaZipUrl(activeReportId)}
              className="button secondary"
              download
              title="Unduh seluruh file .td, .twr, .rpt, .p1 dalam format zip"
            >
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 6 }}>
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3" />
              </svg>
              Download MST Files (.zip)
            </a>
            <a
              href={api.exportSdaExcelUrl(activeReportId)}
              className="button primary"
              download
              title="Unduh ringkasan analisa dan komparasi skenario dalam format Excel .xlsx"
            >
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginRight: 6 }}>
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="8" y1="13" x2="16" y2="13" />
                <line x1="8" y1="17" x2="16" y2="17" />
              </svg>
              Export Excel (.xlsx)
            </a>
          </div>
        )}
      </div>

      {/* Upload Zone & History Selector Bar */}
      <div className="grid-2-1" style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: "1rem", marginBottom: "1.5rem" }}>
        {/* Dropzone Card */}
        <div
          className="card upload-dropzone"
          onDragOver={(e) => e.preventDefault()}
          onDrop={handleDrop}
          style={{
            border: "2px dashed var(--border-color, rgba(255,255,255,0.15))",
            borderRadius: "12px",
            padding: "1.75rem",
            textAlign: "center",
            background: "rgba(255,255,255,0.02)",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            cursor: "pointer",
          }}
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            accept=".pdf"
            style={{ display: "none" }}
          />

          <svg viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="var(--accent, #0a84ff)" strokeWidth="1.6" style={{ marginBottom: "0.75rem" }}>
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
            <path d="M12 18v-6M9 15l3-3 3 3" />
          </svg>

          <h3 style={{ margin: "0 0 0.35rem 0", fontSize: "1.05rem" }}>
            {uploadMutation.isPending ? "Sedang mengekstrak & memproses PDF..." : "Pilih atau Drag & Drop Laporan PDF SDA"}
          </h3>
          <p className="subtext" style={{ margin: "0 0 1rem 0", fontSize: "0.85rem" }}>
            Mendukung dokumen PDF cetakan MS-Tower (PUA font decoding, pembersihan header/footer, ekstraksi multi-skenario).
          </p>

          <div
            onClick={(e) => e.stopPropagation()}
            style={{ display: "inline-flex", alignItems: "center", gap: "0.5rem", fontSize: "0.85rem", background: "rgba(255,255,255,0.04)", padding: "0.4rem 0.8rem", borderRadius: "8px" }}
          >
            <input
              type="checkbox"
              id="cb-opensees"
              checked={runOpensees}
              onChange={(e) => setRunOpensees(e.target.checked)}
            />
            <label htmlFor="cb-opensees" style={{ cursor: "pointer" }}>
              Jalankan Solver FEM OpenSeesPy otomatis untuk validasi geometri (.td & .twr)
            </label>
          </div>
        </div>

        {/* History / Recent Reports Card */}
        <div className="card" style={{ padding: "1.25rem", borderRadius: "12px", background: "rgba(255,255,255,0.02)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem" }}>
            <strong style={{ fontSize: "0.9rem" }}>Riwayat Upload SDA</strong>
            <span className="badge" style={{ fontSize: "0.75rem" }}>
              {reportsQuery.data?.length ?? 0} Dokumen
            </span>
          </div>

          <div style={{ maxHeight: "150px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "0.4rem" }}>
            {reportsQuery.isLoading ? (
              <span className="subtext" style={{ fontSize: "0.85rem" }}>Memuat riwayat...</span>
            ) : reportsQuery.data && reportsQuery.data.length > 0 ? (
              reportsQuery.data.map((r) => (
                <div
                  key={r.id}
                  onClick={() => setActiveReportId(r.id)}
                  style={{
                    padding: "0.5rem 0.65rem",
                    borderRadius: "6px",
                    cursor: "pointer",
                    fontSize: "0.82rem",
                    background: activeReportId === r.id ? "rgba(10, 132, 255, 0.15)" : "rgba(255,255,255,0.03)",
                    border: activeReportId === r.id ? "1px solid var(--accent, #0a84ff)" : "1px solid transparent",
                    transition: "all 0.15s ease",
                  }}
                >
                  <div style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {r.site_id || r.site_name || r.filename}
                  </div>
                  <div className="subtext" style={{ fontSize: "0.72rem", display: "flex", justifyContent: "space-between" }}>
                    <span>{r.tower_type || "Tower"} {r.tower_height_m ? `${r.tower_height_m}m` : ""}</span>
                    <span>{r.created_at ? r.created_at.slice(0, 10) : ""}</span>
                  </div>
                </div>
              ))
            ) : (
              <span className="subtext" style={{ fontSize: "0.82rem" }}>Belum ada laporan PDF yang diunggah.</span>
            )}
          </div>
        </div>
      </div>

      {/* Main Extracted Content */}
      {reportData ? (
        <div className="sda-results-container">
          {/* Site Metadata Bento Bar */}
          <div className="card" style={{ padding: "1.25rem", borderRadius: "12px", marginBottom: "1.25rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "1rem" }}>
              <div>
                <span className="badge" style={{ background: "rgba(10, 132, 255, 0.15)", color: "var(--accent, #0a84ff)", marginBottom: "0.4rem" }}>
                  {reportData.site_metadata?.regional || "Nasional"} · {reportData.site_metadata?.project_id || "SDA Project"}
                </span>
                <h3 style={{ margin: "0.3rem 0", fontSize: "1.3rem" }}>
                  {reportData.site_metadata?.site_id || "SITE"} - {reportData.site_metadata?.site_name || "Nama Site"}
                </h3>
                <div className="subtext" style={{ fontSize: "0.85rem", display: "flex", gap: "1rem", flexWrap: "wrap" }}>
                  <span>Tipe: <strong>{reportData.site_metadata?.tower_type || "N/A"}</strong></span>
                  <span>Tinggi Menara: <strong>{reportData.site_metadata?.tower_height_m ? `${reportData.site_metadata.tower_height_m} m` : "N/A"}</strong></span>
                  {reportData.site_metadata?.building_height_m ? (
                    <span>Tinggi Gedung: <strong>{reportData.site_metadata.building_height_m} m</strong></span>
                  ) : null}
                  <span>Desain Angin: <strong>{reportData.site_metadata?.wind_design_kph ? `${reportData.site_metadata.wind_design_kph} km/h` : "N/A"}</strong></span>
                  <span>Operasional: <strong>{reportData.site_metadata?.wind_oper_kph ? `${reportData.site_metadata.wind_oper_kph} km/h` : "N/A"}</strong></span>
                </div>
              </div>

              {/* Status Badge */}
              {currentScenario?.summary?.status && (
                <div
                  style={{
                    padding: "0.6rem 1rem",
                    borderRadius: "10px",
                    fontWeight: 700,
                    fontSize: "0.95rem",
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "0.5rem",
                    background:
                      currentScenario.summary.status === "NO NEED STRENGTHENING"
                        ? "rgba(48, 209, 88, 0.15)"
                        : "rgba(255, 69, 58, 0.15)",
                    color:
                      currentScenario.summary.status === "NO NEED STRENGTHENING"
                        ? "var(--success, #30d158)"
                        : "var(--danger, #ff453a)",
                    border: `1px solid ${
                      currentScenario.summary.status === "NO NEED STRENGTHENING"
                        ? "var(--success, #30d158)"
                        : "var(--danger, #ff453a)"
                    }`,
                  }}
                >
                  <span>{currentScenario.summary.status === "NO NEED STRENGTHENING" ? "✓" : "⚠"}</span>
                  <span>{currentScenario.summary.status}</span>
                </div>
              )}
            </div>
          </div>

          {/* Scenario Tabs Bar */}
          <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1.25rem", borderBottom: "1px solid rgba(255,255,255,0.08)", paddingBottom: "0.5rem" }}>
            {scenarioKeys.map((sc) => (
              <button
                key={sc}
                type="button"
                className={activeScenario === sc ? "primary" : "secondary"}
                onClick={() => setActiveScenario(sc)}
                style={{
                  padding: "0.45rem 1rem",
                  borderRadius: "20px",
                  fontSize: "0.85rem",
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Skenario: {sc}
              </button>
            ))}
            <button
              type="button"
              className={activeScenario === "COMPARE_ALL" ? "primary" : "secondary"}
              onClick={() => setActiveScenario("COMPARE_ALL")}
              style={{
                padding: "0.45rem 1rem",
                borderRadius: "20px",
                fontSize: "0.85rem",
                fontWeight: 600,
                cursor: "pointer",
                marginLeft: "auto",
              }}
            >
              Matriks Komparasi Skenario
            </button>
          </div>

          {/* Content: Matrix Comparison or Scenario Detail */}
          {activeScenario === "COMPARE_ALL" ? (
            /* Multi-Scenario Matrix Comparison Card */
            <div className="card" style={{ padding: "1.25rem", borderRadius: "12px", marginBottom: "1.5rem" }}>
              <h3 style={{ margin: "0 0 1rem 0", fontSize: "1.1rem" }}>Matriks Komparasi Multi-Skenario SDA</h3>
              <div style={{ overflowX: "auto" }}>
                <table className="table" style={{ width: "100%", fontSize: "0.85rem" }}>
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left" }}>Parameter Evaluasi Struktur</th>
                      <th style={{ textAlign: "center" }}>Satuan</th>
                      {scenarioKeys.map((sc) => (
                        <th key={sc} style={{ textAlign: "right" }}>{sc}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>Stress Ratio Maksimum (SR max)</td>
                      <td style={{ textAlign: "center" }}>ratio</td>
                      {scenarioKeys.map((sc) => {
                        const sr = scenarios[sc]?.summary?.stress_ratios?.max_ratio ?? null;
                        return (
                          <td key={sc} style={{ textAlign: "right", fontWeight: 700, color: sr && sr > 1.0 ? "var(--danger)" : "inherit" }}>
                            {sr !== null ? sr.toFixed(3) : "-"}
                          </td>
                        );
                      })}
                    </tr>
                    <tr>
                      <td>Max Slenderness Ratio (KL/r)</td>
                      <td style={{ textAlign: "center" }}>-</td>
                      {scenarioKeys.map((sc) => {
                        const klr = scenarios[sc]?.summary?.slenderness?.max_klr ?? null;
                        return <td key={sc} style={{ textAlign: "right" }}>{klr !== null ? klr.toFixed(1) : "-"}</td>;
                      })}
                    </tr>
                    <tr>
                      <td>Rotasi Operasional Sway (Deg)</td>
                      <td style={{ textAlign: "center" }}>deg</td>
                      {scenarioKeys.map((sc) => {
                        const v = scenarios[sc]?.summary?.sway_deg ?? null;
                        return <td key={sc} style={{ textAlign: "right" }}>{v !== null ? v.toFixed(3) : "-"}</td>;
                      })}
                    </tr>
                    <tr>
                      <td>Rotasi Operasional Twist (Deg)</td>
                      <td style={{ textAlign: "center" }}>deg</td>
                      {scenarioKeys.map((sc) => {
                        const v = scenarios[sc]?.summary?.twist_deg ?? null;
                        return <td key={sc} style={{ textAlign: "right" }}>{v !== null ? v.toFixed(3) : "-"}</td>;
                      })}
                    </tr>
                    <tr>
                      <td>Translasi Displacement Puncak</td>
                      <td style={{ textAlign: "center" }}>m</td>
                      {scenarioKeys.map((sc) => {
                        const v = scenarios[sc]?.summary?.displacement_m ?? null;
                        return <td key={sc} style={{ textAlign: "right" }}>{v !== null ? v.toFixed(3) : "-"}</td>;
                      })}
                    </tr>
                    <tr>
                      <td>Reaksi Kaki Tekan Maksimum (Pu)</td>
                      <td style={{ textAlign: "center" }}>kN</td>
                      {scenarioKeys.map((sc) => {
                        const v = scenarios[sc]?.summary?.reactions?.max_comp_kn ?? null;
                        return <td key={sc} style={{ textAlign: "right" }}>{v !== null ? v.toFixed(2) : "-"}</td>;
                      })}
                    </tr>
                    <tr>
                      <td>Reaksi Kaki Tarik / Uplift (Tu)</td>
                      <td style={{ textAlign: "center" }}>kN</td>
                      {scenarioKeys.map((sc) => {
                        const v = scenarios[sc]?.summary?.reactions?.max_uplift_kn ?? null;
                        return <td key={sc} style={{ textAlign: "right" }}>{v !== null ? v.toFixed(2) : "-"}</td>;
                      })}
                    </tr>
                    <tr>
                      <td>Reaksi Geser Tumpuan (Vu)</td>
                      <td style={{ textAlign: "center" }}>kN</td>
                      {scenarioKeys.map((sc) => {
                        const v = scenarios[sc]?.summary?.reactions?.max_shear_kn ?? null;
                        return <td key={sc} style={{ textAlign: "right" }}>{v !== null ? v.toFixed(2) : "-"}</td>;
                      })}
                    </tr>
                    <tr>
                      <td>Rasio Angkur (Interaction / Tension)</td>
                      <td style={{ textAlign: "center" }}>ratio</td>
                      {scenarioKeys.map((sc) => {
                        const ab = scenarios[sc]?.summary?.anchor_baseplate;
                        const v = ab?.anchor_interaction_ratio ?? ab?.anchor_tension_ratio ?? null;
                        return <td key={sc} style={{ textAlign: "right" }}>{v !== null ? v.toFixed(3) : "-"}</td>;
                      })}
                    </tr>
                    <tr>
                      <td>Rasio Base Plate (treq / text)</td>
                      <td style={{ textAlign: "center" }}>ratio</td>
                      {scenarioKeys.map((sc) => {
                        const v = scenarios[sc]?.summary?.anchor_baseplate?.baseplate_ratio ?? null;
                        return <td key={sc} style={{ textAlign: "right" }}>{v !== null ? v.toFixed(3) : "-"}</td>;
                      })}
                    </tr>
                    <tr>
                      <td>Total Massa Menara Baja</td>
                      <td style={{ textAlign: "center" }}>kg</td>
                      {scenarioKeys.map((sc) => {
                        const v = scenarios[sc]?.summary?.total_mass_kg ?? null;
                        return <td key={sc} style={{ textAlign: "right" }}>{v !== null ? v.toLocaleString() : "-"}</td>;
                      })}
                    </tr>
                    <tr style={{ fontWeight: 700, borderTop: "2px solid rgba(255,255,255,0.15)" }}>
                      <td>Status Rekomendasi Struktur</td>
                      <td style={{ textAlign: "center" }}>-</td>
                      {scenarioKeys.map((sc) => {
                        const st = scenarios[sc]?.summary?.status || "N/A";
                        return (
                          <td
                            key={sc}
                            style={{
                              textAlign: "right",
                              color: st === "NO NEED STRENGTHENING" ? "var(--success)" : "var(--danger)",
                            }}
                          >
                            {st}
                          </td>
                        );
                      })}
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            /* Selected Scenario Detail */
            <div>
              {/* Bento Grid Summary Cards */}
              <div
                className="bento-grid"
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
                  gap: "1rem",
                  marginBottom: "1.5rem",
                }}
              >
                {/* Card 1: Stress Ratio */}
                <div className="card" style={{ padding: "1rem 1.25rem", borderRadius: "12px" }}>
                  <div className="subtext" style={{ fontSize: "0.78rem", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                    Stress Ratio Terkritis (SR)
                  </div>
                  <div style={{ fontSize: "1.8rem", fontWeight: 700, margin: "0.3rem 0", color: (currentScenario?.summary?.stress_ratios?.max_ratio ?? 0) > 1.0 ? "var(--danger)" : "var(--success)" }}>
                    {currentScenario?.summary?.stress_ratios?.max_ratio !== undefined && currentScenario?.summary?.stress_ratios?.max_ratio !== null
                      ? currentScenario.summary.stress_ratios.max_ratio.toFixed(3)
                      : "N/A"}
                  </div>
                  <div className="subtext" style={{ fontSize: "0.8rem" }}>
                    Leg: <strong>{currentScenario?.summary?.stress_ratios?.leg?.toFixed(3) ?? "-"}</strong> · Bracing: <strong>{currentScenario?.summary?.stress_ratios?.bracing?.toFixed(3) ?? "-"}</strong>
                  </div>
                </div>

                {/* Card 2: Slenderness */}
                <div className="card" style={{ padding: "1rem 1.25rem", borderRadius: "12px" }}>
                  <div className="subtext" style={{ fontSize: "0.78rem", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                    Slenderness Ratio (KL/r)
                  </div>
                  <div style={{ fontSize: "1.8rem", fontWeight: 700, margin: "0.3rem 0" }}>
                    {currentScenario?.summary?.slenderness?.max_klr !== undefined && currentScenario?.summary?.slenderness?.max_klr !== null
                      ? currentScenario.summary.slenderness.max_klr.toFixed(1)
                      : "N/A"}
                  </div>
                  <div className="subtext" style={{ fontSize: "0.8rem" }}>
                    Leg: <strong>{currentScenario?.summary?.slenderness?.leg?.toFixed(1) ?? "-"}</strong> · Bracing: <strong>{currentScenario?.summary?.slenderness?.bracing?.toFixed(1) ?? "-"}</strong>
                  </div>
                </div>

                {/* Card 3: Deformations */}
                <div className="card" style={{ padding: "1rem 1.25rem", borderRadius: "12px" }}>
                  <div className="subtext" style={{ fontSize: "0.78rem", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                    Serviceability (Rotasi & Disp)
                  </div>
                  <div style={{ fontSize: "1.1rem", fontWeight: 700, margin: "0.4rem 0" }}>
                    Sway: <span style={{ color: "var(--accent)" }}>{currentScenario?.summary?.sway_deg ? `${currentScenario.summary.sway_deg.toFixed(3)}°` : "-"}</span>
                  </div>
                  <div className="subtext" style={{ fontSize: "0.8rem" }}>
                    Twist: <strong>{currentScenario?.summary?.twist_deg ? `${currentScenario.summary.twist_deg.toFixed(3)}°` : "-"}</strong> · Disp: <strong>{currentScenario?.summary?.displacement_m ? `${currentScenario.summary.displacement_m.toFixed(3)} m` : "-"}</strong>
                  </div>
                </div>

                {/* Card 4: Support Reactions */}
                <div className="card" style={{ padding: "1rem 1.25rem", borderRadius: "12px" }}>
                  <div className="subtext" style={{ fontSize: "0.78rem", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                    Reaksi Tumpuan Kaki
                  </div>
                  <div style={{ fontSize: "1.1rem", fontWeight: 700, margin: "0.4rem 0" }}>
                    Pu: <span>{currentScenario?.summary?.reactions?.max_comp_kn ? `${currentScenario.summary.reactions.max_comp_kn.toFixed(1)} kN` : "-"}</span>
                  </div>
                  <div className="subtext" style={{ fontSize: "0.8rem" }}>
                    Tu (Uplift): <strong>{currentScenario?.summary?.reactions?.max_uplift_kn ? `${currentScenario.summary.reactions.max_uplift_kn.toFixed(1)} kN` : "-"}</strong> · Vu: <strong>{currentScenario?.summary?.reactions?.max_shear_kn ? `${currentScenario.summary.reactions.max_shear_kn.toFixed(1)} kN` : "-"}</strong>
                  </div>
                </div>

                {/* Card 5: Anchor & Baseplate */}
                <div className="card" style={{ padding: "1rem 1.25rem", borderRadius: "12px" }}>
                  <div className="subtext" style={{ fontSize: "0.78rem", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                    Anchor Bolt & Base Plate
                  </div>
                  <div style={{ fontSize: "1.1rem", fontWeight: 700, margin: "0.4rem 0" }}>
                    Angkur: <span>{currentScenario?.summary?.anchor_baseplate?.anchor_interaction_ratio ?? currentScenario?.summary?.anchor_baseplate?.anchor_tension_ratio ? `${(currentScenario.summary.anchor_baseplate.anchor_interaction_ratio || currentScenario.summary.anchor_baseplate.anchor_tension_ratio)!.toFixed(3)}` : "-"}</span>
                  </div>
                  <div className="subtext" style={{ fontSize: "0.8rem" }}>
                    Baseplate Ratio: <strong>{currentScenario?.summary?.anchor_baseplate?.baseplate_ratio ? `${currentScenario.summary.anchor_baseplate.baseplate_ratio.toFixed(3)}` : "-"}</strong>
                  </div>
                </div>

                {/* Card 6: Tower Mass */}
                <div className="card" style={{ padding: "1rem 1.25rem", borderRadius: "12px" }}>
                  <div className="subtext" style={{ fontSize: "0.78rem", textTransform: "uppercase", letterSpacing: "0.5px" }}>
                    Total Berat Menara
                  </div>
                  <div style={{ fontSize: "1.8rem", fontWeight: 700, margin: "0.3rem 0" }}>
                    {currentScenario?.summary?.total_mass_kg
                      ? `${(currentScenario.summary.total_mass_kg / 1000).toFixed(2)} t`
                      : "N/A"}
                  </div>
                  <div className="subtext" style={{ fontSize: "0.8rem" }}>
                    {currentScenario?.summary?.total_mass_kg ? `${currentScenario.summary.total_mass_kg.toLocaleString()} kg` : "-"}
                  </div>
                </div>
              </div>

              {/* Lower Section: Tabs for Inventory, Member Check, and Raw Files */}
              <div className="card" style={{ padding: "1.25rem", borderRadius: "12px", marginBottom: "1.5rem" }}>
                {/* Sub Tab Navigation */}
                <div style={{ display: "flex", gap: "1rem", borderBottom: "1px solid rgba(255,255,255,0.08)", paddingBottom: "0.75rem", marginBottom: "1rem" }}>
                  <h3 style={{ margin: 0, fontSize: "1.1rem" }}>Inventori Perangkat Antena & Beban Linear</h3>
                  <span className="badge" style={{ alignSelf: "center", fontSize: "0.75rem" }}>
                    {allDevices.length} Perangkat
                  </span>
                </div>

                {/* Filters */}
                <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem", flexWrap: "wrap" }}>
                  <input
                    type="text"
                    placeholder="Cari ID, Tenant, atau Library..."
                    value={deviceFilter}
                    onChange={(e) => setDeviceFilter(e.target.value)}
                    style={{
                      padding: "0.4rem 0.75rem",
                      borderRadius: "8px",
                      background: "rgba(255,255,255,0.05)",
                      border: "1px solid rgba(255,255,255,0.1)",
                      color: "inherit",
                      fontSize: "0.85rem",
                      minWidth: "220px",
                    }}
                  />
                  <select
                    value={deviceStatusFilter}
                    onChange={(e) => setDeviceStatusFilter(e.target.value as any)}
                    style={{
                      padding: "0.4rem 0.75rem",
                      borderRadius: "8px",
                      background: "rgba(255,255,255,0.05)",
                      border: "1px solid rgba(255,255,255,0.1)",
                      color: "inherit",
                      fontSize: "0.85rem",
                    }}
                  >
                    <option value="ALL">Semua Status</option>
                    <option value="EXISTING">EXISTING</option>
                    <option value="PROPOSED">PROPOSED</option>
                  </select>
                </div>

                {/* Device Table */}
                <div style={{ maxHeight: "300px", overflowY: "auto" }}>
                  <table className="table" style={{ width: "100%", fontSize: "0.82rem" }}>
                    <thead>
                      <tr>
                        <th style={{ textAlign: "left" }}>ID Perangkat</th>
                        <th style={{ textAlign: "center" }}>Tipe</th>
                        <th style={{ textAlign: "center" }}>Status</th>
                        <th style={{ textAlign: "center" }}>Face / Leg</th>
                        <th style={{ textAlign: "right" }}>Elevasi (m)</th>
                        <th style={{ textAlign: "right" }}>Azimuth (°)</th>
                        <th style={{ textAlign: "right" }}>Massa (kg)</th>
                        <th style={{ textAlign: "left" }}>Library File (.lib)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredDevices.length > 0 ? (
                        filteredDevices.map((d, i) => (
                          <tr key={`${d.id}-${i}`}>
                            <td style={{ fontWeight: 600 }}>{d.id}</td>
                            <td style={{ textAlign: "center" }}>
                              <span className="badge" style={{ fontSize: "0.7rem" }}>{d.type || (d.elevation_m ? "LARGE" : "LINEAR")}</span>
                            </td>
                            <td style={{ textAlign: "center" }}>
                              <span
                                className="badge"
                                style={{
                                  fontSize: "0.7rem",
                                  background: d.status === "PROPOSED" ? "rgba(10, 132, 255, 0.2)" : "rgba(255,255,255,0.08)",
                                  color: d.status === "PROPOSED" ? "var(--accent)" : "inherit",
                                }}
                              >
                                {d.status}
                              </span>
                            </td>
                            <td style={{ textAlign: "center" }}>{d.face || "-"}</td>
                            <td style={{ textAlign: "right" }}>{d.elevation_m !== undefined ? d.elevation_m.toFixed(1) : "-"}</td>
                            <td style={{ textAlign: "right" }}>{d.azimuth_deg !== undefined ? `${d.azimuth_deg}°` : "-"}</td>
                            <td style={{ textAlign: "right" }}>{d.mass_kg !== undefined ? d.mass_kg.toFixed(1) : "-"}</td>
                            <td className="subtext">{d.lib || "-"}</td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan={8} style={{ textAlign: "center", padding: "1.5rem" }} className="subtext">
                            Tidak ada perangkat yang sesuai dengan filter.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Raw MS-Tower Files Viewer Card */}
              <div className="card" style={{ padding: "1.25rem", borderRadius: "12px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem", flexWrap: "wrap", gap: "0.5rem" }}>
                  <div style={{ display: "flex", gap: "0.4rem" }}>
                    {(["td", "twr", "rpt", "p1"] as const).map((ext) => (
                      <button
                        key={ext}
                        type="button"
                        className={activeFileTab === ext ? "primary" : "secondary"}
                        onClick={() => setActiveFileTab(ext)}
                        style={{
                          padding: "0.3rem 0.8rem",
                          borderRadius: "6px",
                          fontSize: "0.8rem",
                          textTransform: "uppercase",
                        }}
                      >
                        .{ext}
                      </button>
                    ))}
                  </div>

                  <button
                    type="button"
                    className="secondary sm"
                    onClick={() => copyToClipboard(currentScenario?.mst_files?.[activeFileTab] || "")}
                    disabled={!currentScenario?.mst_files?.[activeFileTab]}
                  >
                    Salin Teks File .{activeFileTab}
                  </button>
                </div>

                <div
                  style={{
                    background: "rgba(0, 0, 0, 0.4)",
                    borderRadius: "8px",
                    padding: "1rem",
                    maxHeight: "350px",
                    overflowY: "auto",
                    fontFamily: "var(--font-mono, monospace)",
                    fontSize: "0.8rem",
                    lineHeight: 1.45,
                    whiteSpace: "pre-wrap",
                    color: "rgba(255,255,255,0.85)",
                    border: "1px solid rgba(255,255,255,0.06)",
                  }}
                >
                  {currentScenario?.mst_files?.[activeFileTab] || `// File .${activeFileTab} tidak ditemukan di dalam PDF untuk skenario ini.`}
                </div>
              </div>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

