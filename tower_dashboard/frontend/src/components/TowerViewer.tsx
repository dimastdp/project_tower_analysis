import { useEffect, useState } from "react";
import Plotly from "plotly.js-dist-min";
import createPlotlyComponent from "react-plotly.js/factory";
import type { Geometry, Member3DStress, SiteDevice } from "../types";

const Plot = createPlotlyComponent(Plotly);

type DragMode3D = "turntable" | "orbit" | "pan" | "zoom";
type CameraPreset = "ISO" | "TOP" | "FRONT" | "RIGHT" | "BACK" | "LEFT";

function readTokens() {
  const s = getComputedStyle(document.documentElement);
  const v = (n: string) => s.getPropertyValue(n).trim();
  return {
    primary: v("--primary") || "#0066cc",
    danger: v("--danger") || "#dc2626",
    muted: v("--muted") || "#64748b",
    border: v("--border") || "#cbd5e1",
  };
}

function useThemeTokens() {
  const [tokens, setTokens] = useState(readTokens);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setTokens(readTokens());
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return tokens;
}

/**
 * Build 3D translucent mesh + wireframe edges for site devices
 * strictly matching their .lib shape_type (BOX, CYL, SH1/SHIELDED/MW Dish)
 * and exact .lib dimensions (Height=dim_m, Width=Af/dim_m, Depth=Asf/dim_m).
 */
function buildDevice3DGeometry(devices: SiteDevice[]) {
  const edgeX: (number | null)[] = [];
  const edgeY: (number | null)[] = [];
  const edgeZ: (number | null)[] = [];
  const bracketX: (number | null)[] = [];
  const bracketY: (number | null)[] = [];
  const bracketZ: (number | null)[] = [];
  const vx: number[] = [];
  const vy: number[] = [];
  const vz: number[] = [];
  const ti: number[] = [];
  const tj: number[] = [];
  const tk: number[] = [];
  const mx: number[] = [];
  const my: number[] = [];
  const mz: number[] = [];
  const texts: string[] = [];

  const boxTriangles = [
    [0, 1, 2], [0, 2, 3],
    [4, 5, 6], [4, 6, 7],
    [0, 1, 5], [0, 5, 4],
    [2, 3, 7], [2, 7, 6],
    [1, 2, 6], [1, 6, 5],
    [0, 3, 7], [0, 7, 4],
  ];
  const boxEdges = [
    [0, 1], [1, 2], [2, 3], [3, 0],
    [4, 5], [5, 6], [6, 7], [7, 4],
    [0, 4], [1, 5], [2, 6], [3, 7],
  ];

  devices.forEach((d) => {
    const cx = d.x_m ?? 1.1;
    const cy = d.y_m ?? 1.1;
    const cz = d.elev_z_m;
    const shape = (d.shape_type || "BOX").toUpperCase();

    const h = Math.max(d.length_m ?? d.dim_m ?? 0.8, 0.12);
    const w = Math.max(d.width_m ?? 0.35, 0.10);
    const dep = Math.max(d.depth_m ?? 0.18, 0.08);
    const rad = ((d.azimuth_deg ?? 45) * Math.PI) / 180;
    const cosA = Math.cos(rad);
    const sinA = Math.sin(rad);

    const toWorld = (lx: number, ly: number, lz: number): [number, number, number] => [
      cx + lx * cosA - ly * sinA,
      cy + lx * sinA + ly * cosA,
      cz + lz,
    ];

    const isDish =
      shape.includes("SH") ||
      shape === "STD" ||
      shape === "RAD" ||
      d.device_name.toUpperCase().startsWith("MW") ||
      d.device_name.toUpperCase().startsWith("SH");
    const isCyl = shape === "CYL" && !isDish;

    if (isDish) {
      const N_SEG = 12;
      const rDish = h / 2;
      const halfDep = dep / 2;
      const baseIdx = vx.length;
      const frontRing: [number, number, number][] = [];
      const backRing: [number, number, number][] = [];

      for (let s = 0; s < N_SEG; s++) {
        const theta = (2 * Math.PI * s) / N_SEG;
        const ly = rDish * Math.cos(theta);
        const lz = rDish * Math.sin(theta);
        const wf = toWorld(halfDep, ly, lz);
        const wb = toWorld(-halfDep, ly * 0.72, lz * 0.72);
        frontRing.push(wf);
        backRing.push(wb);
        vx.push(wf[0], wb[0]);
        vy.push(wf[1], wb[1]);
        vz.push(wf[2], wb[2]);
      }
      const fCenter = toWorld(halfDep, 0, 0);
      const bCenter = toWorld(-halfDep, 0, 0);
      const fCenterIdx = vx.length;
      vx.push(fCenter[0], bCenter[0]);
      vy.push(fCenter[1], bCenter[1]);
      vz.push(fCenter[2], bCenter[2]);
      const bCenterIdx = fCenterIdx + 1;

      for (let s = 0; s < N_SEG; s++) {
        const next = (s + 1) % N_SEG;
        const f0 = baseIdx + s * 2;
        const b0 = f0 + 1;
        const f1 = baseIdx + next * 2;
        const b1 = f1 + 1;

        ti.push(f0, f1, f0, b0);
        tj.push(f1, b1, b0, f1);
        tk.push(b0, b0, fCenterIdx, bCenterIdx);

        edgeX.push(frontRing[s][0], frontRing[next][0], null);
        edgeY.push(frontRing[s][1], frontRing[next][1], null);
        edgeZ.push(frontRing[s][2], frontRing[next][2], null);

        edgeX.push(backRing[s][0], backRing[next][0], null);
        edgeY.push(backRing[s][1], backRing[next][1], null);
        edgeZ.push(backRing[s][2], backRing[next][2], null);

        if (s % 3 === 0) {
          edgeX.push(frontRing[s][0], backRing[s][0], null);
          edgeY.push(frontRing[s][1], backRing[s][1], null);
          edgeZ.push(frontRing[s][2], backRing[s][2], null);
        }
      }
    } else if (isCyl) {
      const N_SEG = 10;
      const rCyl = w / 2;
      const halfH = h / 2;
      const baseIdx = vx.length;
      const topRing: [number, number, number][] = [];
      const botRing: [number, number, number][] = [];

      for (let s = 0; s < N_SEG; s++) {
        const theta = (2 * Math.PI * s) / N_SEG;
        const lx = rCyl * Math.cos(theta);
        const ly = rCyl * Math.sin(theta);
        const wt = toWorld(lx, ly, halfH);
        const wb = toWorld(lx, ly, -halfH);
        topRing.push(wt);
        botRing.push(wb);
        vx.push(wt[0], wb[0]);
        vy.push(wt[1], wb[1]);
        vz.push(wt[2], wb[2]);
      }

      for (let s = 0; s < N_SEG; s++) {
        const next = (s + 1) % N_SEG;
        const t0 = baseIdx + s * 2;
        const b0 = t0 + 1;
        const t1 = baseIdx + next * 2;
        const b1 = t1 + 1;
        ti.push(t0, t1);
        tj.push(t1, b1);
        tk.push(b0, b0);

        edgeX.push(topRing[s][0], topRing[next][0], null);
        edgeY.push(topRing[s][1], topRing[next][1], null);
        edgeZ.push(topRing[s][2], topRing[next][2], null);

        edgeX.push(botRing[s][0], botRing[next][0], null);
        edgeY.push(botRing[s][1], botRing[next][1], null);
        edgeZ.push(botRing[s][2], botRing[next][2], null);

        if (s % 2 === 0) {
          edgeX.push(topRing[s][0], botRing[s][0], null);
          edgeY.push(topRing[s][1], botRing[s][1], null);
          edgeZ.push(topRing[s][2], botRing[s][2], null);
        }
      }
    } else {
      const localCorners = [
        [-dep / 2, -w / 2, -h / 2],
        [dep / 2, -w / 2, -h / 2],
        [dep / 2, w / 2, -h / 2],
        [-dep / 2, w / 2, -h / 2],
        [-dep / 2, -w / 2, h / 2],
        [dep / 2, -w / 2, h / 2],
        [dep / 2, w / 2, h / 2],
        [-dep / 2, w / 2, h / 2],
      ];

      const baseIdx = vx.length;
      const worldCorners = localCorners.map(([lx, ly, lz]) => {
        const [wx, wy, wz] = toWorld(lx, ly, lz);
        vx.push(wx);
        vy.push(wy);
        vz.push(wz);
        return [wx, wy, wz];
      });

      for (const [a, b, c] of boxTriangles) {
        ti.push(baseIdx + a);
        tj.push(baseIdx + b);
        tk.push(baseIdx + c);
      }
      for (const [a, b] of boxEdges) {
        edgeX.push(worldCorners[a][0], worldCorners[b][0], null);
        edgeY.push(worldCorners[a][1], worldCorners[b][1], null);
        edgeZ.push(worldCorners[a][2], worldCorners[b][2], null);
      }
    }

    bracketX.push(cx * 0.72, cx, null);
    bracketY.push(cy * 0.72, cy, null);
    bracketZ.push(cz, cz, null);

    mx.push(cx);
    my.push(cy);
    mz.push(cz);
    texts.push(
      `<b>${d.device_name}</b> (${d.status} · Bentuk: ${shape})<br>` +
      `Tenant: ${d.tenant} · Sisi ${d.face ?? "A"} · Qty ${d.qty}<br>` +
      `Elevasi Z: ${cz.toFixed(2)} m · Azimut: ${(d.azimuth_deg ?? 0).toFixed(0)}°<br>` +
      `<b>Dimensi Fisik .lib: T=${h.toFixed(2)}m × L=${w.toFixed(2)}m × D=${dep.toFixed(2)}m</b><br>` +
      `Af=${(d.af_m2 ?? h * w).toFixed(3)} m² · Asf=${(d.asf_m2 ?? h * dep).toFixed(3)} m²` +
      (d.in_library ? ` · EPA=${(d.epa_m2 ?? 0).toFixed(3)} m²` : `<br>⚠ Belum di Master .lib (Pendekatan Dimensi)`)
    );
  });

  return { edgeX, edgeY, edgeZ, bracketX, bracketY, bracketZ, vx, vy, vz, ti, tj, tk, mx, my, mz, texts };
}

const CAMERA_PRESETS: Record<CameraPreset, { eye: { x: number; y: number; z: number }; up: { x: number; y: number; z: number } }> = {
  ISO:   { eye: { x: 2.0, y: 2.0, z: 0.65 }, up: { x: 0, y: 0, z: 1 } },
  TOP:   { eye: { x: 0.01, y: 0.01, z: 3.2 }, up: { x: 0, y: 1, z: 0 } },
  FRONT: { eye: { x: 2.4, y: 2.4, z: 0.45 }, up: { x: 0, y: 0, z: 1 } },
  RIGHT: { eye: { x: 2.4, y: -2.4, z: 0.45 }, up: { x: 0, y: 0, z: 1 } },
  BACK:  { eye: { x: -2.4, y: -2.4, z: 0.45 }, up: { x: 0, y: 0, z: 1 } },
  LEFT:  { eye: { x: -2.4, y: 2.4, z: 0.45 }, up: { x: 0, y: 0, z: 1 } },
};

export default function TowerViewer({
  geometry,
  devices = [],
  highlightFace = "ALL",
  memberStress,
}: {
  geometry: Geometry;
  devices?: SiteDevice[];
  highlightFace?: "ALL" | "A" | "B" | "C" | "D";
  memberStress?: Member3DStress[];
}) {
  const t = useThemeTokens();

  // Interactive 3D CAD state: Drag Mode (Turntable/Orbit/Pan/Zoom), Zoom Scale, Camera Preset, Grid toggle
  const [dragMode, setDragMode] = useState<DragMode3D>("turntable");
  const [zoomScale, setZoomScale] = useState<number>(1.0);
  const [camPreset, setCamPreset] = useState<CameraPreset>("ISO");
  const [showGrid, setShowGrid] = useState<boolean>(true);
  const [viewRevision, setViewRevision] = useState<number>(1);

  // Sync camera preset when highlightFace changes from parent toolbar
  useEffect(() => {
    if (highlightFace === "ALL") setCamPreset("ISO");
    else if (highlightFace === "A") setCamPreset("FRONT");
    else if (highlightFace === "B") setCamPreset("RIGHT");
    else if (highlightFace === "C") setCamPreset("BACK");
    else if (highlightFace === "D") setCamPreset("LEFT");
    setViewRevision((r) => r + 1);
  }, [highlightFace]);

  const supports = geometry.nodes.filter((n) => n.support);
  const axis = (title: string) => ({
    title: showGrid ? title : "",
    color: t.muted,
    gridcolor: t.border,
    zerolinecolor: t.border,
    showbackground: showGrid,
    backgroundcolor: "rgba(241, 245, 249, 0.45)",
    showgrid: showGrid,
    zeroline: showGrid,
    showticklabels: showGrid,
  });

  const visibleDevices =
    highlightFace === "ALL" ? devices : devices.filter((d) => (d.face ?? "A") === highlightFace);

  const existingDevs = visibleDevices.filter((d) => d.status === "EXISTING" && d.in_library);
  const proposedDevs = visibleDevices.filter((d) => d.status === "PROPOSED" && d.in_library);
  const missingDevs = visibleDevices.filter((d) => !d.in_library);

  const exGeo = buildDevice3DGeometry(existingDevs);
  const prGeo = buildDevice3DGeometry(proposedDevs);
  const msGeo = buildDevice3DGeometry(missingDevs);

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const traces: any[] = [];

  if (memberStress && memberStress.length > 0) {
    const bands = [
      { key: "zero", label: "SR = 0.00", color: "#94a3b8", width: 1.8, match: (sr: number) => sr <= 0.001 },
      { key: "b50", label: "0.00 < SR < 0.50", color: "#2563eb", width: 2.4, match: (sr: number) => sr > 0.001 && sr < 0.5 },
      { key: "b75", label: "0.50 ≤ SR < 0.75", color: "#06b6d4", width: 2.8, match: (sr: number) => sr >= 0.5 && sr < 0.75 },
      { key: "b90", label: "0.75 ≤ SR < 0.90", color: "#16a34a", width: 3.0, match: (sr: number) => sr >= 0.75 && sr < 0.9 },
      { key: "b100", label: "0.90 ≤ SR ≤ 1.00", color: "#eab308", width: 3.5, match: (sr: number) => sr >= 0.9 && sr <= 1.0 },
      { key: "over", label: "SR > 1.00 (OVERSTRESS)", color: "#dc2626", width: 4.8, match: (sr: number) => sr > 1.0 },
    ];

    for (const band of bands) {
      const bx: (number | null)[] = [];
      const by: (number | null)[] = [];
      const bz: (number | null)[] = [];
      const hx: number[] = [];
      const hy: number[] = [];
      const hz: number[] = [];
      const htext: string[] = [];

      for (const m of memberStress) {
        if (!band.match(m.stress_ratio)) continue;
        bx.push(m.x1, m.x2, null);
        by.push(m.y1, m.y2, null);
        bz.push(m.z1, m.z2, null);
        hx.push((m.x1 + m.x2) / 2);
        hy.push((m.y1 + m.y2) / 2);
        hz.push((m.z1 + m.z2) / 2);
        htext.push(
          `<b>Member #${m.id}</b> (${m.typ} · Panel ${m.pnl})<br>` +
          `Profil: ${m.sec_name} · KL/r = ${m.kl_over_r.toFixed(0)}<br>` +
          `Pu = ${m.pu_kn.toFixed(1)} kN / φPn = ${m.phi_pn_kn.toFixed(1)} kN<br>` +
          `<b>Stress Ratio (SR): ${m.stress_ratio.toFixed(3)}</b> ${m.stress_ratio > 1 ? "⚠ OVERSTRESS" : "✓ AMAN"}`
        );
      }

      if (bx.length > 0) {
        traces.push({
          type: "scatter3d",
          mode: "lines",
          x: bx,
          y: by,
          z: bz,
          line: { width: band.width, color: band.color },
          hoverinfo: "skip",
          name: band.label,
        });
        traces.push({
          type: "scatter3d",
          mode: "markers",
          x: hx,
          y: hy,
          z: hz,
          marker: { size: band.key === "over" ? 4.5 : 2.5, color: band.color, opacity: band.key === "over" ? 0.95 : 0.65 },
          text: htext,
          hovertemplate: "%{text}<extra></extra>",
          name: band.label,
        });
      }
    }
  } else {
    const x: (number | null)[] = [];
    const y: (number | null)[] = [];
    const z: (number | null)[] = [];
    for (const [x1, y1, z1, x2, y2, z2] of geometry.segments) {
      x.push(x1, x2, null);
      y.push(y1, y2, null);
      z.push(z1, z2, null);
    }
    traces.push({
      type: "scatter3d", mode: "lines", x, y, z,
      line: { width: 2.3, color: t.primary }, hoverinfo: "skip", name: "Members",
    });
  }

  traces.push({
    type: "scatter3d", mode: "markers",
    x: supports.map((n) => n.x), y: supports.map((n) => n.y), z: supports.map((n) => n.z),
    marker: { size: 5, color: t.danger }, name: "Supports",
    hovertemplate: "Support<br>X %{x:.2f} Y %{y:.2f} Z %{z:.2f} m<extra></extra>",
  });

  const addDeviceGroupTraces = (
    g: ReturnType<typeof buildDevice3DGeometry>,
    fillColor: string,
    edgeColor: string,
    label: string,
  ) => {
    if (!g.mx.length) return;
    traces.push(
      {
        type: "scatter3d",
        mode: "lines",
        x: g.bracketX,
        y: g.bracketY,
        z: g.bracketZ,
        line: { width: 2.5, color: "#64748b" },
        hoverinfo: "skip",
        name: `${label} bracket`,
      },
      {
        type: "mesh3d",
        x: g.vx,
        y: g.vy,
        z: g.vz,
        i: g.ti,
        j: g.tj,
        k: g.tk,
        color: fillColor,
        opacity: 0.36,
        flatshading: true,
        hoverinfo: "skip",
        name: label,
      },
      {
        type: "scatter3d",
        mode: "lines",
        x: g.edgeX,
        y: g.edgeY,
        z: g.edgeZ,
        line: { width: 2.0, color: edgeColor },
        opacity: 0.88,
        hoverinfo: "skip",
        name: `${label} outline`,
      },
      {
        type: "scatter3d",
        mode: "markers",
        x: g.mx,
        y: g.my,
        z: g.mz,
        marker: { size: 3.5, color: edgeColor, opacity: 0.9 },
        text: g.texts,
        hovertemplate: "%{text}<extra></extra>",
        name: label,
      },
    );
  };

  addDeviceGroupTraces(exGeo, "#0d9488", "#0f766e", "EXISTING (.lib)");
  addDeviceGroupTraces(prGeo, "#f59e0b", "#b45309", "PROPOSED (.lib)");
  addDeviceGroupTraces(msGeo, "#ef4444", "#991b1b", "Missing in .lib");

  const basePreset = CAMERA_PRESETS[camPreset] ?? CAMERA_PRESETS.ISO;
  const activeCamera = {
    eye: {
      x: basePreset.eye.x * zoomScale,
      y: basePreset.eye.y * zoomScale,
      z: basePreset.eye.z * zoomScale,
    },
    up: basePreset.up,
    center: { x: 0, y: 0, z: 0 },
  };

  const handleZoom = (factor: number) => {
    setZoomScale((prev) => Math.min(Math.max(prev * factor, 0.35), 2.8));
    setViewRevision((r) => r + 1);
  };

  const handleResetCamera = () => {
    setZoomScale(1.0);
    setCamPreset("ISO");
    setDragMode("turntable");
    setViewRevision((r) => r + 1);
  };

  return (
    <div className="cad-viewport-wrapper" style={{ position: "relative", width: "100%", height: "100%" }}>
      {/* Left Docked 3D CAD Navigation & Camera Toolbar (Rotate / Orbit / Pan / Zoom / View Presets) */}
      <div className="cad-3d-dock" role="toolbar" aria-label="Kontrol Navigasi 3D CAD">
        <div className="cad-dock-section">
          <span className="cad-dock-label">Mode Mouse</span>
          <button
            type="button"
            className={`cad-dock-btn ${dragMode === "turntable" ? "active" : ""}`}
            onClick={() => setDragMode("turntable")}
            title="Putar 3D mengelilingi sumbu Z vertikal menara (Turntable)"
          >
            ↻ Putar Z
          </button>
          <button
            type="button"
            className={`cad-dock-btn ${dragMode === "orbit" ? "active" : ""}`}
            onClick={() => setDragMode("orbit")}
            title="Putar bebas 360 derajat (3D Orbit)"
          >
            🌐 Orbit 3D
          </button>
          <button
            type="button"
            className={`cad-dock-btn ${dragMode === "pan" ? "active" : ""}`}
            onClick={() => setDragMode("pan")}
            title="Geser posisi kamera (Pan)"
          >
            ✥ Pan / Geser
          </button>
          <button
            type="button"
            className={`cad-dock-btn ${dragMode === "zoom" ? "active" : ""}`}
            onClick={() => setDragMode("zoom")}
            title="Perbesar / perkecil dengan drag mouse"
          >
            🔍 Zoom Drag
          </button>
        </div>

        <div className="cad-dock-divider" />

        <div className="cad-dock-section">
          <span className="cad-dock-label">Kamera</span>
          <div className="cad-dock-row">
            <button
              type="button"
              className="cad-dock-icon-btn"
              onClick={() => handleZoom(0.8)}
              title="Perbesar (Zoom In)"
            >
              ＋
            </button>
            <button
              type="button"
              className="cad-dock-icon-btn"
              onClick={() => handleZoom(1.25)}
              title="Perkecil (Zoom Out)"
            >
              －
            </button>
            <button
              type="button"
              className="cad-dock-icon-btn"
              onClick={handleResetCamera}
              title="Reset tampilan kamera ke Isometrik"
            >
              ⌂
            </button>
          </div>
          <div className="cad-dock-grid">
            {(["ISO", "TOP", "FRONT", "RIGHT"] as const).map((preset) => (
              <button
                key={preset}
                type="button"
                className={`cad-dock-mini ${camPreset === preset ? "active" : ""}`}
                onClick={() => {
                  setCamPreset(preset);
                  setViewRevision((r) => r + 1);
                }}
              >
                {preset === "ISO" ? "Iso" : preset === "TOP" ? "Atas" : preset === "FRONT" ? "Depan" : "Kanan"}
              </button>
            ))}
          </div>
          <button
            type="button"
            className={`cad-dock-btn ${showGrid ? "active" : ""}`}
            onClick={() => setShowGrid((v) => !v)}
            style={{ marginTop: 2 }}
          >
            {showGrid ? "⊞ Grid: ON" : "⊞ Grid: OFF"}
          </button>
        </div>
      </div>

      {/* Bottom Interactive CAD Controls Hint Pill */}
      <div className="cad-viewport-hud">
        <span>
          Mode: <strong>{dragMode === "turntable" ? "Putar Sumbu Z" : dragMode === "orbit" ? "Orbit 3D Bebas" : dragMode === "pan" ? "Pan (Geser)" : "Zoom"}</strong>
        </span>
        <span className="telemetry-sep" />
        <span>Klik Kiri + Drag: <strong>{dragMode.toUpperCase()}</strong></span>
        <span className="telemetry-sep" />
        <span>Klik Kanan + Drag: <strong>PAN</strong></span>
        <span className="telemetry-sep" />
        <span>Scroll: <strong>ZOOM</strong></span>
      </div>

      <Plot
        style={{ width: "100%", height: "100%" }}
        useResizeHandler
        data={traces}
        layout={{
          autosize: true,
          margin: { l: 0, r: 0, t: 0, b: 0 },
          paper_bgcolor: "rgba(0,0,0,0)",
          showlegend: false,
          dragmode: dragMode,
          uirevision: `${dragMode}-${viewRevision}`,
          font: { family: "Inter, system-ui, sans-serif", size: 11 },
          scene: {
            aspectmode: "data",
            dragmode: dragMode,
            xaxis: axis("X (m)"),
            yaxis: axis("Y (m)"),
            zaxis: axis("Z (m)"),
            camera: activeCamera,
          },
        }}
        config={{
          displaylogo: false,
          responsive: true,
          scrollZoom: true,
          displayModeBar: true,
          toImageButtonOptions: { filename: "tower_3d_devices" },
        }}
      />
    </div>
  );
}
