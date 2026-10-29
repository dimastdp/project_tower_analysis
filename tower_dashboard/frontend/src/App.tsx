import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { SiteContext } from "./SiteContext";
import { useToast } from "./components/Toast";
import TowersPage from "./pages/TowersPage";
import LibraryPage from "./pages/LibraryPage";
import InventoryPage from "./pages/InventoryPage";
import AnalysisPage from "./pages/AnalysisPage";
import type { UserRole } from "./types";

const NAV = [
  { to: "/towers", label: "3D Tower", title: "Katalog Tower & 3D Studio" },
  { to: "/library", label: "Perangkat .lib", title: "Library Perangkat MTEL.lib" },
  { to: "/inventory", label: "Inventori", title: "Inventori Site & Potongan 4 Sisi" },
  { to: "/analysis", label: "Analisis TIA-222-G", title: "Analisis TIA-222-G & Kalibrasi MS Tower" },
];

const ROLES: { id: UserRole; label: string }[] = [
  { id: "engineer", label: "Engineer" },
  { id: "devops", label: "DevOps" },
  { id: "pm", label: "PM" },
];

export default function App() {
  const qc = useQueryClient();
  const toast = useToast();
  const [site, setSiteState] = useState<string | null>(() => {
    try { return localStorage.getItem("activeSite"); } catch { return null; }
  });
  const [role, setRole] = useState<UserRole>("engineer");

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
  const libCountQuery = useQuery({
    queryKey: ["library-names"],
    queryFn: () => api.listDevices(""),
  });

  const syncMtel = useMutation({
    mutationFn: api.syncMtelLibrary,
    onSuccess: (res) => {
      toast(`Berhasil sinkronisasi ${res.imported} perangkat dari ${res.source}`);
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
    } catch { /* ignore */ }
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
    document.title = `${page.title} · Tower Studio`;
  }, [page.title]);

  const activeTower = towers.data?.find((t) => t.site_name === site);
  const devs = siteDevices.data ?? [];
  const missingNames = Array.from(new Set(devs.filter((d) => !d.in_library).map((d) => d.device_name)));
  const rec = latestRun.data?.engineering?.recommendation;
  const maxSr = Math.max(
    0,
    ...(latestRun.data?.engineering?.member_checks?.map((m) => m.stress_ratio) ?? [0]),
  );

  let goState: "GO" | "HOLD" | "NOGO" = "HOLD";
  let goText = "Menunggu Verifikasi";
  if (latestRun.data) {
    if ((rec === "NO NEED PERKUATAN" || rec === "AMAN") && missingNames.length === 0 && maxSr <= 1.0) {
      goState = "GO";
      goText = "Layak Instalasi (GO)";
    } else if (rec === "PERKUATAN DULU" || maxSr > 1.0) {
      goState = "NOGO";
      goText = "Perlu Perkuatan (NO-GO)";
    } else {
      goState = "HOLD";
      goText = "Paralel Toleransi";
    }
  }

  return (
    <SiteContext.Provider value={{ site, setSite }}>
      <div className="app-shell">
        {/* Global Apple Frosted Glass Navigation Bar */}
        <header className="cmd-bar">
          <div className="cmd-brand">
            <span className="cmd-brand-mark">TS</span>
            <span>Tower Studio</span>
            <span className="cmd-brand-sub">MS Tower V6 &amp; TIA-222-G · v2.0.0</span>
          </div>

          <nav className="cmd-nav" aria-label="Menu Utama">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                id={`nav-${n.to.replace("/", "")}`}
                className={({ isActive }) => (isActive ? "cmd-tab active" : "cmd-tab")}
              >
                <span>{n.label}</span>
              </NavLink>
            ))}
          </nav>

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

            <div className="role-pills" role="tablist" aria-label="Mode Tampilan Role">
              {ROLES.map((r) => (
                <button
                  key={r.id}
                  type="button"
                  role="tab"
                  aria-selected={role === r.id}
                  className={`role-pill ${role === r.id ? "active" : ""}`}
                  onClick={() => setRole(r.id)}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>
        </header>

        {/* Subtle Apple Telemetry Sub-bar */}
        <div className="status-ribbon">
          <div className="status-ribbon-left">
            <span
              className={`badge ${
                goState === "GO" ? "ok" : goState === "NOGO" ? "danger" : "warn"
              }`}
            >
              {goText}
            </span>

            {activeTower && (
              <>
                <span className="telemetry-sep" />
                <span className="telemetry-item">
                  Geometri:{" "}
                  <strong className="num">
                    {activeTower.height_m}m · {activeTower.total_nodes} Node · {activeTower.total_members} Member
                  </strong>
                </span>
              </>
            )}

            <span className="telemetry-sep" />
            <span className="telemetry-item">
              Inventori:{" "}
              <strong className="num">
                {devs.filter((d) => d.status === "EXISTING").length} Existing +{" "}
                {devs.filter((d) => d.status === "PROPOSED").length} Proposed
              </strong>
            </span>

            {latestRun.data && (
              <>
                <span className="telemetry-sep" />
                <span className="telemetry-item">
                  SR Maks:{" "}
                  <strong
                    className="num"
                    style={{ color: maxSr > 1.0 ? "var(--danger)" : "var(--success)" }}
                  >
                    {maxSr.toFixed(3)}
                  </strong>
                </span>
                <span className="telemetry-item">
                  Sway:{" "}
                  <strong className="num">
                    {(latestRun.data.engineering?.twist_sway_disp?.sway_deg ?? 0).toFixed(4)}°
                  </strong>
                </span>
                <span className="telemetry-item">
                  Pu,max:{" "}
                  <strong className="num">{latestRun.data.max_pu_kn.toFixed(2)} kN</strong>
                </span>
              </>
            )}
          </div>

          <div className="status-ribbon-right">
            {role === "engineer" && (
              <span className="telemetry-item">
                Kalibrasi MS Tower: <strong>SR · Twist/Sway/Disp · Support Reaction</strong>
              </span>
            )}
            {role === "devops" && (
              <>
                <span className="telemetry-item">
                  Katalog <strong className="num">{libCountQuery.data?.length ?? 0}</strong> item
                </span>
                <button
                  type="button"
                  className="secondary sm"
                  disabled={syncMtel.isPending}
                  onClick={() => syncMtel.mutate()}
                >
                  {syncMtel.isPending ? "Sinkronisasi…" : "Sinkronisasi MTEL.lib"}
                </button>
              </>
            )}
            {role === "pm" && (
              <span className="telemetry-item">
                Keputusan Kolokasi: <strong>{rec ?? "Jalankan Analisis"}</strong>
              </span>
            )}

            {missingNames.length > 0 ? (
              <span className="badge warn">
                {missingNames.length} referensi belum di .lib ({missingNames.slice(0, 2).join(", ")})
              </span>
            ) : (
              <span className="badge ok">Semua perangkat terdaftar di .lib</span>
            )}
          </div>
        </div>

        {/* Main Studio Workspace */}
        <main className="workspace">
          <Routes>
            <Route path="/" element={<Navigate to="/towers" replace />} />
            <Route path="/towers" element={<TowersPage />} />
            <Route path="/library" element={<LibraryPage />} />
            <Route path="/inventory" element={<InventoryPage />} />
            <Route path="/analysis" element={<AnalysisPage />} />
            <Route path="*" element={<Navigate to="/towers" replace />} />
          </Routes>
        </main>
      </div>
    </SiteContext.Provider>
  );
}
