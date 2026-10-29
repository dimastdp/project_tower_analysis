import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { useSite } from "../SiteContext";
import ConfirmDialog from "../components/ConfirmDialog";
import FileDrop from "../components/FileDrop";
import { useToast } from "../components/Toast";
import TowerViewer from "../components/TowerViewer";

export default function TowersPage() {
  const qc = useQueryClient();
  const { site, setSite } = useSite();
  const toast = useToast();
  const [confirmSite, setConfirmSite] = useState<string | null>(null);
  const [show3DDevices, setShow3DDevices] = useState(true);
  const [faceFilter, setFaceFilter] = useState<"ALL" | "A" | "B" | "C" | "D">("ALL");

  const towers = useQuery({ queryKey: ["towers"], queryFn: api.listTowers });
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

  const upload = useMutation({
    mutationFn: api.uploadTower,
    onSuccess: (t) => {
      qc.invalidateQueries({ queryKey: ["towers"] });
      qc.invalidateQueries({ queryKey: ["geometry", t.site_name] });
      setSite(t.site_name);
      toast(`Disimpan ${t.site_name} (${t.total_nodes} node, ${t.total_members} member)`);
    },
  });

  const remove = useMutation({
    mutationFn: api.deleteTower,
    onSuccess: (_d, name) => {
      qc.invalidateQueries({ queryKey: ["towers"] });
      if (site === name) setSite(null);
      toast(`Dihapus ${name}`);
    },
  });

  const active = towers.data?.find((t) => t.site_name === site);
  const error = (upload.error ?? remove.error ?? towers.error) as Error | null;
  const supportCount = geometry.data?.nodes.filter((n) => n.support).length ?? 0;

  return (
    <div className="split">
      {/* LEFT COLUMN: Site Catalog & Upload Card */}
      <div>
        <section className="sheet-flush" aria-busy={towers.isLoading}>
          <div className="sheet-head">
            <div>
              <h2>Katalog Site Menara (.mst)</h2>
              <span className="sheet-head-sub">
                Pilih site untuk memuat model 3D, inventori, dan analisis
              </span>
            </div>
            {towers.data && towers.data.length > 0 && (
              <span className="badge info num">{towers.data.length} site</span>
            )}
          </div>

          {!towers.data?.length ? (
            <div style={{ padding: 20 }} className="muted">
              Belum ada model menara. Unggah berkas .mst di bawah untuk memulai.
            </div>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Nama Site</th>
                    <th style={{ textAlign: "right" }}>Tinggi</th>
                    <th style={{ textAlign: "right" }}>Member</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {towers.data.map((t) => (
                    <tr
                      key={t.site_name}
                      className={t.site_name === site ? "selected" : ""}
                      onClick={() => setSite(t.site_name)}
                      style={{ cursor: "pointer" }}
                    >
                      <td style={{ wordBreak: "break-word", maxWidth: 155 }}>
                        <strong style={{ fontSize: 12 }}>{t.site_name}</strong>
                      </td>
                      <td className="num" style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                        {t.height_m.toFixed(1)} m
                      </td>
                      <td className="num" style={{ textAlign: "right" }}>
                        {t.total_members}
                      </td>
                      <td style={{ textAlign: "right" }} onClick={(e) => e.stopPropagation()}>
                        <button
                          type="button"
                          className="danger sm"
                          onClick={() => setConfirmSite(t.site_name)}
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

          {active && (
            <div
              style={{
                padding: "12px 16px",
                borderTop: "1px solid var(--border)",
                background: "var(--surface-2)",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 8,
                flexWrap: "wrap",
              }}
            >
              <span style={{ fontSize: 12, color: "var(--ink-secondary)" }}>
                Aktif: <strong>{active.site_name}</strong>
              </span>
              <div style={{ display: "flex", gap: 6 }}>
                <Link to="/inventory" className="btn secondary sm">
                  Buka Inventori
                </Link>
                <Link to="/analysis" className="btn sm">
                  Buka Analisis
                </Link>
              </div>
            </div>
          )}
        </section>

        <section className="sheet-flush">
          <div className="sheet-head">
            <div>
              <h2>Tambah Model Microstran (.mst)</h2>
              <span className="sheet-head-sub">
                Otomatis membaca geometri DAT~, beban TWR~, inventori antena, serta RPT~
              </span>
            </div>
          </div>
          <div style={{ padding: 16 }}>
            <FileDrop
              accept=".mst"
              label="Tarik berkas .mst ke sini atau klik untuk memilih"
              hint="Mendukung seluruh format .mst MS Tower V6."
              busy={upload.isPending}
              busyLabel="Memproses berkas .mst…"
              onFile={(f) => upload.mutate(f)}
            />
            {error && (
              <div className="banner error" role="alert" style={{ marginTop: 10 }}>
                {error.message}
              </div>
            )}
          </div>
        </section>
      </div>

      {/* RIGHT COLUMN: 3D Apple Studio Viewport */}
      <section className="cad-pane">
        <div className="cad-pane-bar">
          <div>
            <div className="cad-pane-title">
              <span>Studio Geometri 3D &amp; Perangkat{site ? ` — ${site}` : ""}</span>
              {active && <span className="badge info">{active.height_m}m Tower</span>}
            </div>
          </div>

          {active && (
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <div className="segmented" role="group" aria-label="Pilih sisi pandang 3D">
                {(["ALL", "A", "B", "C", "D"] as const).map((f) => (
                  <button
                    key={f}
                    type="button"
                    className={faceFilter === f ? "active" : ""}
                    onClick={() => setFaceFilter(f)}
                  >
                    {f === "ALL" ? "Semua Sisi" : `Sisi ${f}`}
                  </button>
                ))}
              </div>
              <button
                type="button"
                className={`sm ${show3DDevices ? "tinted" : "secondary"}`}
                onClick={() => setShow3DDevices((v) => !v)}
              >
                {show3DDevices ? "Perangkat 3D Aktif" : "Tampilkan Perangkat 3D"}
              </button>
            </div>
          )}
        </div>

        {active && (
          <div className="cad-legend">
            <span className="cad-legend-item">
              <span className="cad-Swatch" style={{ background: "#0071E3" }} />
              <span>Struktur ({active.total_members} member)</span>
            </span>
            <span className="cad-legend-item">
              <span className="cad-Swatch" style={{ background: "#FF3B30" }} />
              <span>Tumpuan ({supportCount} titik)</span>
            </span>
            <span className="cad-legend-item">
              <span className="cad-Swatch" style={{ background: "#0D9488" }} />
              <span>Perangkat Existing (.lib)</span>
            </span>
            <span className="cad-legend-item">
              <span className="cad-Swatch" style={{ background: "#F59E0B" }} />
              <span>Perangkat Proposed (.lib)</span>
            </span>
          </div>
        )}

        <div className="viewer" aria-busy={geometry.isLoading}>
          {!site ? (
            <div style={{ padding: 28, color: "#94a3b8" }}>
              Pilih atau unggah model .mst untuk melihat struktur 3D.
            </div>
          ) : geometry.error ? (
            <div className="banner error" role="alert">
              {(geometry.error as Error).message}
            </div>
          ) : geometry.data ? (
            <TowerViewer
              geometry={geometry.data}
              devices={show3DDevices ? (siteDevices.data ?? []) : []}
              highlightFace={faceFilter}
            />
          ) : null}
        </div>

        {active && (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(5, 1fr)",
              padding: "12px 16px",
              background: "var(--surface-2)",
              borderTop: "1px solid var(--border)",
              gap: 10,
            }}
          >
            <div>
              <div className="kpi-label">Tinggi Menara</div>
              <strong className="num">{active.height_m.toFixed(2)} m</strong>
            </div>
            <div>
              <div className="kpi-label">Lebar Puncak</div>
              <strong className="num">{active.top_width_m.toFixed(2)} m</strong>
            </div>
            <div>
              <div className="kpi-label">Lebar Dasar</div>
              <strong className="num">{active.bot_width_m.toFixed(2)} m</strong>
            </div>
            <div>
              <div className="kpi-label">Total Nodes</div>
              <strong className="num">{active.total_nodes.toLocaleString()}</strong>
            </div>
            <div>
              <div className="kpi-label">Total Members</div>
              <strong className="num">{active.total_members.toLocaleString()}</strong>
            </div>
          </div>
        )}
      </section>

      <ConfirmDialog
        open={confirmSite !== null}
        title={`Hapus ${confirmSite ?? ""}?`}
        message="Tindakan ini akan menghapus geometri menara, inventori perangkat site, dan riwayat hasil analisis."
        confirmLabel="Hapus site"
        onConfirm={() => {
          if (confirmSite) remove.mutate(confirmSite);
        }}
        onClose={() => setConfirmSite(null)}
      />
    </div>
  );
}
