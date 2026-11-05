import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { SiteContext, type ViewportFace } from "./SiteContext";
import { useToast } from "./components/Toast";
import TowersPage from "./pages/TowersPage";
import LibraryPage from "./pages/LibraryPage";
import InventoryPage from "./pages/InventoryPage";
import AnalysisPage from "./pages/AnalysisPage";

const NAV = [
  {
    to: "/towers",
    step: "01",
    label: "3D Tower",
    shortLabel: "3D CAD",
    title: "Katalog Tower & 3D CAD Studio",
    desc: "Input .mst/PDF & Viewport 3D",
  },
  {
    to: "/library",
    step: "02",
    label: "Perangkat .lib",
    shortLabel: ".lib",
    title: "Library Perangkat (Project vs Master .lib)",
    desc: "Project .lib & Master MTEL.lib",
  },
  {
    to: "/inventory",
    step: "03",
    label: "Inventori",
    shortLabel: "Inventori",
    title: "Inventori Site & Potongan 4 Sisi",
    desc: "Pemetaan Sisi A–D & Elevasi",
  },
  {
    to: "/analysis",
    step: "04",
    label: "Analisis TIA-222-G",
    shortLabel: "Analisis",
    title: "Analisis TIA-222-G OpenSeesPy & Komparasi MS Tower V6",
    desc: "OpenSeesPy FEM & Report .rpt",
  },
];

export default function App() {
  const qc = useQueryClient();
  const toast = useToast();
  const [site, setSiteState] = useState<string | null>(() => {
    try {
      return localStorage.getItem("activeSite");
    } catch {
      return null;
    }
  });
  const [editMode, setEditMode] = useState<boolean>(false);
  const [activeFace, setActiveFace] = useState<ViewportFace>("ALL");
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(false);

  const towers = useQuery({ queryKey: ["towers"], queryFn: api.listTowers });
  const siteDevices = useQuery({
    queryKey: ["inventory", site],
    queryFn: () => api.listSiteDevices(site!),
    enabled: !!site,
  });
  const latestRun = useQuery({
    queryKey: ["analysis", site],
    queryFn: () => api.latestAnalysis(site!),
    enabled: !!site,
  });

  const syncMtel = useMutation({
    mutationFn: api.syncMtelLibrary,
    onSuccess: (res) => {
      toast(`Tersimpan & sinkron ${res.imported} perangkat dari ${res.source}`);
      qc.invalidateQueries({ queryKey: ["library"] });
      qc.invalidateQueries({ queryKey: ["library-names"] });
      qc.invalidateQueries({ queryKey: ["inventory", site] });
    },
  });

  const { pathname } = useLocation();
  const page = NAV.find((n) => pathname.startsWith(n.to)) ?? NAV[0];

  const setSite = (s: string | null) => {
    setSiteState(s);
    try {
      if (s) localStorage.setItem("activeSite", s);
      else localStorage.removeItem("activeSite");
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    if (!towers.data) return;
    if (!site || !towers.data.some((t) => t.site_name === site)) {
      const prop = towers.data.find((t) => t.site_name === "PROPOSED");
      setSite((prop ?? towers.data[0])?.site_name ?? null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [towers.data]);

  useEffect(() => {
    document.title = `${page.title} · Tower Studio CAD`;
  }, [page.title]);

  const activeTower = towers.data?.find((t) => t.site_name === site);
  const devs = siteDevices.data ?? [];
  const existingCount = devs.filter((d) => d.status === "EXISTING").length;
  const proposedCount = devs.filter((d) => d.status === "PROPOSED").length;
  const missingNames = Array.from(
    new Set(devs.filter((d) => !d.in_library).map((d) => d.device_name)),
  );

  const rec = latestRun.data?.engineering?.recommendation;
  const maxSr = Math.max(
    0,
    ...(latestRun.data?.engineering?.member_checks?.map((m) => m.stress_ratio) ?? [0]),
  );

  let goState: "GO" | "HOLD" | "NOGO" = "HOLD";
  let goLabel = "HOLD · Verifikasi";
  if (latestRun.data) {
    if ((rec === "NO NEED PERKUATAN" || rec === "AMAN") && missingNames.length === 0 && maxSr <= 1.0) {
      goState = "GO";
      goLabel = "GO · Layak";
    } else if (rec === "PERKUATAN DULU" || maxSr > 1.0) {
      goState = "NOGO";
      goLabel = "NO-GO · Perkuatan";
    } else {
      goState = "HOLD";
      goLabel = "HOLD · Toleransi";
    }
  }

  return (
    <SiteContext.Provider
      value={{
        site,
        setSite,
        editMode,
        setEditMode,
        activeFace,
        setActiveFace,
      }}
    >
      <div className={`desktop-app-frame ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
        {/* LEFT DOCKED ENGINEERING SIDEBAR */}
        <aside className="app-sidebar" aria-label="Sidebar Aplikasi Engineering">
          <div className="sidebar-brand">
            <div className="sidebar-brand-left">
              <span className="cmd-brand-mark">TS</span>
              {!sidebarCollapsed && (
                <div className="sidebar-brand-text">
                  <strong>Tower Studio</strong>
                  <span>CAD &amp; FEM Workbench</span>
                </div>
              )}
            </div>
            <button
              type="button"
              className="sidebar-collapse-btn"
              onClick={() => setSidebarCollapsed((v) => !v)}
              title={sidebarCollapsed ? "Perluas Sidebar" : "Ciutkan Sidebar"}
            >
              {sidebarCollapsed ? "»" : "«"}
            </button>
          </div>

          {/* Workflow Stepper Navigation */}
          <div className="sidebar-section">
            {!sidebarCollapsed && <div className="sidebar-section-label">ALUR REKAYASA STRUKTUR</div>}
            <nav className="sidebar-nav" aria-label="Alur Kerja">
              {NAV.map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  className={({ isActive }) => `sidebar-nav-item ${isActive ? "active" : ""}`}
                  title={n.title}
                >
                  <span className="sidebar-step-badge">{n.step}</span>
                  {!sidebarCollapsed && (
                    <div className="sidebar-nav-copy">
                      <span className="sidebar-nav-title">{n.label}</span>
                      <span className="sidebar-nav-desc">{n.desc}</span>
                    </div>
                  )}
                </NavLink>
              ))}
            </nav>
          </div>

          {/* Project / Site Explorer Tree inside Sidebar */}
          <div className="sidebar-section sidebar-sites-section">
            {!sidebarCollapsed && (
              <div className="sidebar-section-label">
                <span>PROJECT EXPLORER</span>
                <span className="num">{towers.data?.length ?? 0}</span>
              </div>
            )}
            <div className="sidebar-site-list">
              {towers.data?.map((t) => {
                const isSelected = t.site_name === site;
                return (
                  <button
                    key={t.site_name}
                    type="button"
                    onClick={() => setSite(t.site_name)}
                    className={`sidebar-site-item ${isSelected ? "active" : ""}`}
                    title={`${t.site_name} (${t.height_m}m · ${t.total_members} member)`}
                  >
                    <span className="sidebar-site-dot" />
                    {sidebarCollapsed ? (
                      <span className="mono" style={{ fontSize: 10 }}>
                        {t.site_name.slice(0, 3)}
                      </span>
                    ) : (
                      <>
                        <span className="sidebar-site-name">{t.site_name}</span>
                        <span className="sidebar-site-meta num">{t.height_m}m</span>
                      </>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Sidebar Bottom Quick Actions */}
          <div className="sidebar-footer">
            {site && (
              <a
                href={api.exportBundleRarUrl(site)}
                download={`${site}_MSTOWER_TD_TWR_BUNDLE.rar`}
                className="sidebar-action-btn primary"
                title="Konversi & unduh bundel native MS-Tower (.td, .twr, .lib, .rpt, .p1) dalam arsip .rar"
              >
                <span>📦</span>
                {!sidebarCollapsed && <span>Export .td/.twr (.rar)</span>}
              </a>
            )}
            <button
              type="button"
              disabled={syncMtel.isPending}
              onClick={() => syncMtel.mutate()}
              className="sidebar-action-btn"
              title="Sinkronkan database perangkat dengan Master MTEL.lib"
            >
              <span>⟳</span>
              {!sidebarCollapsed && (
                <span>{syncMtel.isPending ? "Sinkronisasi…" : "Sync Master .lib"}</span>
              )}
            </button>
          </div>
        </aside>

        {/* RIGHT MAIN APPLICATION AREA */}
        <div className="app-main-column">
          {/* 1 & 2. Global Top Application Navbar */}
          <header className="cmd-bar">
            {/* Left: Active Workspace Breadcrumb */}
            <div className="cmd-brand">
              <span className="app-breadcrumb-root">Workspace</span>
              <span className="app-breadcrumb-sep">/</span>
              <strong className="app-breadcrumb-site">{site ?? "Pilih Site"}</strong>
              <span className="app-breadcrumb-sep">/</span>
              <span className="app-breadcrumb-page">{page.label}</span>
            </div>

            {/* 2. Center: Primary Navigation Tabs with High-Contrast Active Blue Underline */}
            <nav className="cmd-nav-underline" aria-label="Menu Utama">
              {NAV.map((n) => (
                <NavLink
                  key={n.to}
                  to={n.to}
                  id={`nav-${n.to.replace("/", "")}`}
                  className={({ isActive }) =>
                    `cmd-tab-underline ${isActive ? "active" : ""}`
                  }
                >
                  <span>{n.label}</span>
                </NavLink>
              ))}
            </nav>

            {/* 1. Right: Unified Site Selector + GO/NO-GO Status + Edit Mode + Save/Sync */}
            <div className="cmd-controls">
              <div className="site-selector-group">
                <label htmlFor="site-selector">Site</label>
                <select
                  id="site-selector"
                  value={site ?? ""}
                  onChange={(e) => setSite(e.target.value || null)}
                  disabled={!towers.data?.length}
                >
                  {!towers.data?.length && <option value="">Belum ada site</option>}
                  {towers.data?.map((t) => (
                    <option key={t.site_name} value={t.site_name}>
                      {t.site_name} ({t.height_m}m)
                    </option>
                  ))}
                </select>
              </div>

              <span
                className={`header-status-pill ${
                  goState === "GO" ? "ok" : goState === "NOGO" ? "danger" : "warn"
                }`}
                title={`Status Struktur: ${goLabel}`}
              >
                <span className="status-dot" />
                <span>{goLabel}</span>
              </span>

              <button
                type="button"
                role="switch"
                aria-checked={editMode}
                onClick={() => {
                  const next = !editMode;
                  setEditMode(next);
                  toast(next ? "Edit Mode diaktifkan" : "Edit Mode dinonaktifkan");
                }}
                className={`edit-mode-toggle ${editMode ? "active" : ""}`}
              >
                <span className="edit-dot" />
                <span>Edit Mode</span>
              </button>

              <button
                type="button"
                disabled={syncMtel.isPending}
                onClick={() => syncMtel.mutate()}
                className="sync-action-btn"
              >
                <span>{syncMtel.isPending ? "Menyimpan…" : "Save / Sync"}</span>
              </button>
            </div>
          </header>

          {/* 4. Compact Single-Line Telemetry Readout Bar */}
          <div className="compact-telemetry-bar" aria-live="polite">
            <div className="telemetry-inline-group">
              <span className="telemetry-chip">
                Tinggi:{" "}
                <strong className="num">
                  {activeTower ? `${activeTower.height_m.toFixed(1)}m` : "—"}
                </strong>
              </span>

              <span className="telemetry-sep" />

              <span className="telemetry-chip">
                Struktur:{" "}
                <strong className="num">
                  {activeTower
                    ? `${activeTower.total_nodes} Node · ${activeTower.total_members} Member`
                    : "—"}
                </strong>
              </span>

              <span className="telemetry-sep" />

              <span className="telemetry-chip">
                SR Maks:{" "}
                <strong
                  className="num"
                  style={{
                    color: latestRun.data
                      ? maxSr > 1.0
                        ? "var(--danger)"
                        : "var(--success)"
                      : "var(--muted)",
                  }}
                >
                  {latestRun.data ? maxSr.toFixed(3) : "—"}
                </strong>
              </span>

              <span className="telemetry-sep" />

              <span className="telemetry-chip">
                Sway:{" "}
                <strong className="num">
                  {latestRun.data
                    ? `${(latestRun.data.engineering?.twist_sway_disp?.sway_deg ?? 0).toFixed(4)}°`
                    : "—"}
                </strong>
              </span>

              <span className="telemetry-sep" />

              <span className="telemetry-chip">
                Pu,max:{" "}
                <strong className="num">
                  {latestRun.data ? `${latestRun.data.max_pu_kn.toFixed(2)} kN` : "—"}
                </strong>
              </span>

              <span className="telemetry-sep" />

              <span className="telemetry-chip">
                Inventori:{" "}
                <strong className="num">
                  {existingCount} Ex + {proposedCount} Prop
                </strong>
              </span>
            </div>

            <div className="telemetry-inline-right">
              {editMode && <span className="badge info">Mode Edit Aktif</span>}
              {missingNames.length > 0 ? (
                <span className="badge warn">
                  {missingNames.length} dev auto-approach ({missingNames.slice(0, 2).join(", ")})
                </span>
              ) : (
                <span className="badge ok">Katalog .lib Comply</span>
              )}
            </div>
          </div>

          {/* Main Workbench Canvas */}
          <main className="workspace">
            <Routes>
              <Route path="/" element={<Navigate to="/towers" replace />} />
              <Route path="/towers" element={<TowersPage />} />
              <Route path="/library" element={<LibraryPage />} />
              <Route path="/inventory" element={<InventoryPage />} />
              <Route path="/analysis" element={<AnalysisPage />} />
              <Route path="/sda-extractor" element={<Navigate to="/towers" replace />} />
              <Route path="*" element={<Navigate to="/towers" replace />} />
            </Routes>
          </main>

          {/* Bottom Desktop Program Status Bar */}
          <footer className="app-statusbar">
            <div className="statusbar-left">
              <span className="statusbar-indicator">
                <span className="statusbar-dot" />
                OpenSeesPy 3D FEM Ready
              </span>
              <span className="statusbar-sep">|</span>
              <span>Standar: ANSI/TIA-222-G &amp; MS-Tower V6</span>
              <span className="statusbar-sep">|</span>
              <span>
                Site Aktif: <strong>{site ?? "—"}</strong>
              </span>
            </div>
            <div className="statusbar-right">
              <span>3D CAD: Klik Kiri Rotate/Orbit · Klik Kanan Pan · Scroll Zoom</span>
              <span className="statusbar-sep">|</span>
              <span className="mono">v2.3.0 Studio</span>
            </div>
          </footer>
        </div>
      </div>
    </SiteContext.Provider>
  );
}
