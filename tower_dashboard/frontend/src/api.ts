// The ONLY module that calls fetch (TRD 2.4).
import type {
  AnalysisParams,
  AnalysisResult,
  Geometry,
  LibraryDevice,
  LibraryDeviceInput,
  MsTowerReportResult,
  PreflightResult,
  SiteDevice,
  SiteDeviceInput,
  Tower,
} from "./types";

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError("Cannot reach the API server. Start the backend on port 8000.", 0);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    let detail: string;
    if (typeof body.detail === "string") detail = body.detail;
    else if (Array.isArray(body.detail))
      detail = body.detail.map((d: { loc?: unknown[]; msg?: string }) =>
        `${(d.loc ?? []).slice(-1)[0] ?? "field"}: ${d.msg ?? "invalid"}`).join("; ");
    else detail = res.statusText || `Request failed (${res.status})`;
    throw new ApiError(detail, res.status);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const enc = encodeURIComponent;

function fileForm(file: File): FormData {
  const fd = new FormData();
  fd.append("file", file);
  return fd;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  listTowers: () => request<Tower[]>("/towers"),
  uploadTower: (file: File) =>
    request<Tower>("/towers/upload", { method: "POST", body: fileForm(file) }),
  deleteTower: (site: string) => request<void>(`/towers/${enc(site)}`, { method: "DELETE" }),
  geometry: (site: string) => request<Geometry>(`/towers/${enc(site)}/geometry`),

  importLibrary: (file: File) =>
    request<{ imported: number }>("/library/devices/import", { method: "POST", body: fileForm(file) }),
  syncMtelLibrary: () =>
    request<{ imported: number; source: string }>("/library/devices/sync-mtel", { method: "POST" }),
  listDevices: (q: string) => request<LibraryDevice[]>(`/library/devices?q=${enc(q)}`),
  upsertLibraryDevice: (body: LibraryDeviceInput) =>
    request<LibraryDevice>("/library/devices", json(body)),
  deleteLibraryDevice: (deviceName: string) =>
    request<void>(`/library/devices/${enc(deviceName)}`, { method: "DELETE" }),
  exportLibraryUrl: "/api/library/devices/export",

  listSiteDevices: (site: string) => request<SiteDevice[]>(`/sites/${enc(site)}/devices`),
  addSiteDevice: (site: string, body: SiteDeviceInput) =>
    request<{ id: number }>(`/sites/${enc(site)}/devices`, json(body)),
  deleteSiteDevice: (site: string, id: number) =>
    request<void>(`/sites/${enc(site)}/devices/${id}`, { method: "DELETE" }),
  applyDeviceSuggestion: (
    site: string,
    deviceId: number,
    targetDeviceName: string,
    mode: "replace" | "clone_to_lib",
  ) =>
    request<{ mode: string; device_name?: string; old_name?: string; new_name?: string; based_on?: string }>(
      `/sites/${enc(site)}/devices/${deviceId}/apply-suggestion`,
      json({ target_device_name: targetDeviceName, mode }),
    ),

  preflightAnalysis: (site: string) => request<PreflightResult>(`/sites/${enc(site)}/preflight`),
  runAnalysis: (site: string, params: number | AnalysisParams) => {
    const body: AnalysisParams =
      typeof params === "number" ? { wind_speed_ms: params } : params;
    return request<AnalysisResult>(`/sites/${enc(site)}/analysis`, json(body));
  },
  latestAnalysis: (site: string) =>
    request<AnalysisResult>(`/sites/${enc(site)}/analysis/latest`).catch((e: ApiError) => {
      if (e.status === 404 && e.message.startsWith("No analysis")) return null;
      throw e;
    }),
  analysisReport: (site: string) =>
    request<MsTowerReportResult>(`/sites/${enc(site)}/analysis/report`),
  exportExcelUrl: (site: string) => `/api/sites/${enc(site)}/analysis/export/excel`,
  exportRptUrl: (site: string) => `/api/sites/${enc(site)}/analysis/export/rpt`,
};
