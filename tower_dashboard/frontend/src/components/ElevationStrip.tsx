import { useState } from "react";
import type { SiteDevice, TowerFace } from "../types";

interface Props {
  heightM: number;
  topWidthM: number;
  baseWidthM: number;
  devices: SiteDevice[];
  activeFace?: TowerFace | "ALL";
  onFaceChange?: (face: TowerFace | "ALL") => void;
}

const FACES: { id: TowerFace; label: string; dir: string; quad: string }[] = [
  { id: "A", label: "Sisi A", dir: "Utara / NE", quad: "Leg A (+X, +Y)" },
  { id: "B", label: "Sisi B", dir: "Timur / SE", quad: "Leg B (+X, -Y)" },
  { id: "C", label: "Sisi C", dir: "Selatan / SW", quad: "Leg C (-X, -Y)" },
  { id: "D", label: "Sisi D", dir: "Barat / NW", quad: "Leg D (-X, +Y)" },
];

export default function ElevationStrip({
  heightM,
  topWidthM,
  baseWidthM,
  devices,
  activeFace: controlledFace,
  onFaceChange,
}: Props) {
  const [internalFace, setInternalFace] = useState<TowerFace | "ALL">("A");
  const face = controlledFace ?? internalFace;
  const setFace = (next: TowerFace | "ALL") => {
    setInternalFace(next);
    onFaceChange?.(next);
  };

  const H = 400;
  const padT = 22;
  const padB = 26;
  const usable = H - padT - padB;
  const hSafe = Math.max(heightM, 1);
  const maxW = Math.max(baseWidthM, topWidthM, 1.0);
  const pxPerMeterY = usable / hSafe;
  const yOf = (z: number) => padT + usable * (1 - Math.min(Math.max(z / hSafe, 0), 1.06));

  const ticks = Array.from({ length: 6 }, (_, i) => (hSafe * i) / 5);
  const panelCount = Math.max(6, Math.min(14, Math.round(hSafe / 2.2)));

  const countByFace = (f: TowerFace) => devices.filter((d) => (d.face ?? "A") === f).length;

  const stepFace = (delta: number) => {
    const order: (TowerFace | "ALL")[] = ["A", "B", "C", "D", "ALL"];
    const idx = order.indexOf(face);
    const next = order[(idx + delta + order.length) % order.length];
    setFace(next);
  };

  const renderSingleFaceSvg = (targetFace: TowerFace, widthSvg = 300, compact = false) => {
    const cx = compact ? widthSvg * 0.42 : 92;
    const scaleHalfW = compact ? 22 : 34;
    const halfAt = (z: number) => {
      const r = Math.min(Math.max(z / hSafe, 0), 1);
      const wAtZ = baseWidthM - (baseWidthM - topWidthM) * r;
      return (wAtZ / maxW) * scaleHalfW;
    };

    const faceDevices = devices
      .filter((d) => (d.face ?? "A") === targetFace)
      .sort((a, b) => b.elev_z_m - a.elev_z_m);

    // Build lattice bracing lines
    const bracingLines: { x1: number; y1: number; x2: number; y2: number }[] = [];
    for (let p = 0; p < panelCount; p++) {
      const z0 = (hSafe * p) / panelCount;
      const z1 = (hSafe * (p + 1)) / panelCount;
      const y0 = yOf(z0);
      const y1 = yOf(z1);
      const hw0 = halfAt(z0);
      const hw1 = halfAt(z1);
      bracingLines.push({ x1: cx - hw1, y1, x2: cx + hw1, y2: y1 });
      bracingLines.push({ x1: cx - hw0, y1: y0, x2: cx + hw1, y2: y1 });
      bracingLines.push({ x1: cx + hw0, y1: y0, x2: cx - hw1, y2: y1 });
    }

    const meta = FACES.find((f) => f.id === targetFace)!;

    return (
      <svg
        key={targetFace}
        viewBox={`0 0 ${widthSvg} ${H}`}
        role="img"
        aria-label={`Potongan elevasi ${meta.label} (${meta.dir}), ${faceDevices.length} perangkat`}
        className="elev-svg"
      >
        <text x={cx} y={14} textAnchor="middle" className="elev-face-title">
          {meta.label} · {compact ? meta.dir.split(" ")[0] : `${meta.dir} (${meta.quad})`}
        </text>

        {ticks.map((z) => (
          <g key={z}>
            <line x1={compact ? 22 : 30} x2={widthSvg - 8} y1={yOf(z)} y2={yOf(z)} className="elev-grid" />
            <text x={compact ? 19 : 25} y={yOf(z) + 3.5} className="elev-tick">
              {z.toFixed(0)}m
            </text>
          </g>
        ))}

        {/* Tapered tower body */}
        <polygon
          className="elev-tower"
          points={`${cx - halfAt(0)},${yOf(0)} ${cx + halfAt(0)},${yOf(0)} ${cx + halfAt(hSafe)},${yOf(hSafe)} ${cx - halfAt(hSafe)},${yOf(hSafe)}`}
        />
        {bracingLines.map((b, i) => (
          <line key={i} x1={b.x1} y1={b.y1} x2={b.x2} y2={b.y2} className="elev-brace" />
        ))}

        {/* Devices placed on this face with physical .lib dimensions */}
        {faceDevices.map((d, i) => {
          const yCenter = yOf(d.elev_z_m);
          const hw = halfAt(d.elev_z_m);
          const sideSign = i % 2 === 0 ? 1 : -1;
          const xMount = cx + (compact ? hw + 6 : hw + 8 + (i % 3) * 7);
          const hPx = Math.max(7, Math.min(34, (d.length_m ?? 0.8) * pxPerMeterY * 1.15));
          const wPx = Math.max(6, Math.min(18, (d.width_m ?? 0.35) * pxPerMeterY * 1.6));
          const isDish = (d.shape_type ?? "").includes("SH") || d.device_name.startsWith("SH") || d.device_name.startsWith("MW");
          const color = !d.in_library ? "#dc2626" : d.status === "PROPOSED" ? "#d97706" : "#0d9488";
          const fill = !d.in_library ? "rgba(220,38,38,0.18)" : d.status === "PROPOSED" ? "rgba(245,158,11,0.22)" : "rgba(13,148,136,0.20)";

          // Spread label Y slightly to avoid overlap at identical elevations
          const labelY = yCenter + ((i % 3) - 1) * (compact ? 7 : 9);
          const labelX = compact ? cx + hw + 20 : cx + scaleHalfW + 34;

          return (
            <g key={d.id} className="elev-dev-group">
              <title>
                {`[${meta.label}] ${d.device_name} (${d.status}) · ${d.tenant}\n` +
                  `Z = ${d.elev_z_m.toFixed(2)} m · Qty ${d.qty}\n` +
                  `Dimensi .lib: ${(d.length_m ?? 0).toFixed(2)} × ${(d.width_m ?? 0).toFixed(2)} × ${(d.depth_m ?? 0).toFixed(2)} m`}
              </title>
              {/* Bracket line from leg to antenna */}
              <line x1={cx + hw * (sideSign > 0 ? 1 : 0.6)} y1={yCenter} x2={xMount} y2={yCenter} stroke={color} strokeWidth={1.3} />

              {/* Scaled .lib physical shape */}
              {isDish ? (
                <circle
                  cx={xMount}
                  cy={yCenter}
                  r={Math.max(4.5, hPx / 2)}
                  fill={fill}
                  stroke={color}
                  strokeWidth={1.6}
                />
              ) : (
                <rect
                  x={xMount - wPx / 2}
                  y={yCenter - hPx / 2}
                  width={wPx}
                  height={hPx}
                  rx={1.5}
                  fill={fill}
                  stroke={color}
                  strokeWidth={1.5}
                  strokeDasharray={d.in_library ? undefined : "2,1"}
                />
              )}

              {/* Callout leader & label */}
              <line x1={xMount + wPx / 2 + 1} y1={yCenter} x2={labelX - 3} y2={labelY} stroke={color} strokeWidth={0.8} strokeOpacity={0.7} />
              <text x={labelX} y={labelY + 3} fill={color} className="elev-dev-label">
                {compact
                  ? `${d.device_name} (${d.elev_z_m.toFixed(0)}m)`
                  : `${d.device_name} @${d.elev_z_m.toFixed(1)}m (${(d.length_m ?? 0).toFixed(2)}m)`}
              </text>
            </g>
          );
        })}
      </svg>
    );
  };

  return (
    <div className="elev-card">
      <div className="row between wrap-gap" style={{ marginBottom: 8 }}>
        <div className="seg-group" role="tablist" aria-label="Pilih sisi potongan elevasi">
          {FACES.map((f) => (
            <button
              key={f.id}
              type="button"
              role="tab"
              aria-selected={face === f.id}
              className={`seg-btn ${face === f.id ? "active" : ""}`}
              onClick={() => setFace(f.id)}
            >
              {f.label} <span className="seg-count">{countByFace(f.id)}</span>
            </button>
          ))}
          <button
            type="button"
            role="tab"
            aria-selected={face === "ALL"}
            className={`seg-btn ${face === "ALL" ? "active" : ""}`}
            onClick={() => setFace("ALL")}
          >
            4 Sisi (A–D)
          </button>
        </div>

        <div className="row gap-xs">
          <button type="button" className="btn quiet sm" onClick={() => stepFace(-1)} title="Sisi sebelumnya">
            ‹ Prev
          </button>
          <button type="button" className="btn quiet sm" onClick={() => stepFace(1)} title="Sisi berikutnya">
            Next ›
          </button>
        </div>
      </div>

      {face === "ALL" ? (
        <div className="elev-grid-4">
          {FACES.map((f) => (
            <div key={f.id} className="elev-pane" onClick={() => setFace(f.id)} title="Klik untuk memperbesar sisi ini">
              {renderSingleFaceSvg(f.id, 210, true)}
            </div>
          ))}
        </div>
      ) : (
        <div className="elev-single-wrap">{renderSingleFaceSvg(face, 320, false)}</div>
      )}

      <figcaption className="muted elev-caption">
        <span><span className="dot existing" /> EXISTING (.lib)</span>
        <span><span className="dot proposed" /> PROPOSED (.lib)</span>
        <span><span className="dot missing" /> Belum di .lib</span>
        <span className="mono">· Skala dimensi fisik dari MTEL.lib</span>
      </figcaption>
    </div>
  );
}
