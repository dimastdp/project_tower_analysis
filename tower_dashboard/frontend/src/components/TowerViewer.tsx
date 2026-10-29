import { useEffect, useState } from "react";
import Plotly from "plotly.js-dist-min";
import createPlotlyComponent from "react-plotly.js/factory";
import type { Geometry, Member3DStress, SiteDevice } from "../types";

const Plot = createPlotlyComponent(Plotly);

function readTokens() {
  const s = getComputedStyle(document.documentElement);
  const v = (n: string) => s.getPropertyValue(n).trim();
  return {
    primary: v("--primary") || "#2563eb",
    danger: v("--danger") || "#dc2626",
    muted: v("--muted") || "#64748b",
    border: v("--border") || "#e2e8f0",
  };
}

/** Follows light/dark theme by reading the DBD tokens at render time. */
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

/** Build 3D cuboid wireframe edges + mesh triangles for a group of site devices using .lib dimensions. */
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
    const h = Math.max(d.length_m ?? 0.8, 0.28);
    const w = Math.max(d.width_m ?? 0.35, 0.22);
    const dep = Math.max(d.depth_m ?? 0.2, 0.16);
    const rad = ((d.azimuth_deg ?? 45) * Math.PI) / 180;
    const cosA = Math.cos(rad);
    const sinA = Math.sin(rad);

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
      const wx = cx + lx * cosA - ly * sinA;
      const wy = cy + lx * sinA + ly * cosA;
      const wz = cz + lz;
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

    // Mounting arm from tower leg toward device center
    bracketX.push(cx * 0.72, cx, null);
    bracketY.push(cy * 0.72, cy, null);
    bracketZ.push(cz, cz, null);

    mx.push(cx);
    my.push(cy);
    mz.push(cz);
    texts.push(
      `<b>${d.device_name}</b> (${d.status})<br>` +
      `Tenant: ${d.tenant} · Sisi ${d.face ?? "A"} · Qty ${d.qty}<br>` +
      `Elevasi Z: ${cz.toFixed(2)} m · Azimut: ${(d.azimuth_deg ?? 0).toFixed(0)}°<br>` +
      `Dimensi .lib: ${h.toFixed(2)} × ${w.toFixed(2)} × ${dep.toFixed(2)} m` +
      (d.in_library ? `<br>EPA: ${(d.epa_m2 ?? 0).toFixed(3)} m²` : `<br>⚠ Belum ada di .lib`)
    );
  });

  return { edgeX, edgeY, edgeZ, bracketX, bracketY, bracketZ, vx, vy, vz, ti, tj, tk, mx, my, mz, texts };
}

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

  const supports = geometry.nodes.filter((n) => n.support);
  const axis = (title: string) => ({
    title, color: t.muted, gridcolor: t.border, zerolinecolor: t.border, showbackground: false,
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
    // MS Tower V6 Stress Ratio color bands
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
      line: { width: 2, color: t.primary }, hoverinfo: "skip", name: "Members",
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
        line: { width: 3, color: "#64748b" },
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
        opacity: 0.78,
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
        line: { width: 2.5, color: edgeColor },
        hoverinfo: "skip",
        name: `${label} outline`,
      },
      {
        type: "scatter3d",
        mode: "markers",
        x: g.mx,
        y: g.my,
        z: g.mz,
        marker: { size: 3.5, color: edgeColor },
        text: g.texts,
        hovertemplate: "%{text}<extra></extra>",
        name: label,
      },
    );
  };

  addDeviceGroupTraces(exGeo, "#0d9488", "#0f766e", "EXISTING (.lib)");
  addDeviceGroupTraces(prGeo, "#f59e0b", "#b45309", "PROPOSED (.lib)");
  addDeviceGroupTraces(msGeo, "#ef4444", "#991b1b", "Missing in .lib");

  const cameraEyeByFace: Record<string, { x: number; y: number; z: number }> = {
    ALL: { x: 2.1, y: 2.1, z: 0.65 },
    A: { x: 2.4, y: 2.4, z: 0.55 },
    B: { x: 2.4, y: -2.4, z: 0.55 },
    C: { x: -2.4, y: -2.4, z: 0.55 },
    D: { x: -2.4, y: 2.4, z: 0.55 },
  };

  return (
    <Plot
      style={{ width: "100%", height: "100%" }}
      useResizeHandler
      data={traces}
      layout={{
        autosize: true,
        margin: { l: 0, r: 0, t: 0, b: 0 },
        paper_bgcolor: "rgba(0,0,0,0)",
        showlegend: false,
        font: { family: "Inter, system-ui, sans-serif", size: 11 },
        scene: {
          aspectmode: "data",
          xaxis: axis("X (m)"), yaxis: axis("Y (m)"), zaxis: axis("Z (m)"),
          camera: { eye: cameraEyeByFace[highlightFace] ?? cameraEyeByFace.ALL },
        },
      }}
      config={{
        displaylogo: false,
        responsive: true,
        modeBarButtonsToRemove: ["zoom3d", "pan3d", "orbitRotation", "tableRotation", "resetCameraLastSave3d", "hoverClosest3d"],
        toImageButtonOptions: { filename: "tower_3d_devices" },
      }}
    />
  );
}
