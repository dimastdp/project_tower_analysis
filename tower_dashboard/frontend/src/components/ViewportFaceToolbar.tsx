import type { ViewportFace } from "../SiteContext";

export const VIEWPORT_FACES: { id: ViewportFace; label: string }[] = [
  { id: "ALL", label: "Semua Sisi" },
  { id: "A", label: "Sisi A" },
  { id: "B", label: "Sisi B" },
  { id: "C", label: "Sisi C" },
  { id: "D", label: "Sisi D" },
];

export function ViewportFaceToolbar({
  activeFace,
  onChange,
  showDevices,
  onToggleDevices,
}: {
  activeFace: ViewportFace;
  onChange: (face: ViewportFace) => void;
  showDevices?: boolean;
  onToggleDevices?: () => void;
}) {
  return (
    <div
      className="floating-viewport-toolbar"
      role="toolbar"
      aria-label="Kontrol Viewport Sisi 3D"
    >
      <div className="flex items-center gap-0.5" role="group" aria-label="Pilih sisi pandang 3D">
        {VIEWPORT_FACES.map((f) => {
          const isActive = activeFace === f.id;
          return (
            <button
              key={f.id}
              type="button"
              onClick={() => onChange(f.id)}
              className={`floating-face-pill ${isActive ? "active" : ""}`}
            >
              {f.label}
            </button>
          );
        })}
      </div>

      {onToggleDevices && (
        <>
          <span className="floating-toolbar-sep" />
          <button
            type="button"
            onClick={onToggleDevices}
            className={`floating-device-pill ${showDevices ? "active" : ""}`}
          >
            {showDevices ? "Overlay .lib: ON" : "Overlay .lib: OFF"}
          </button>
        </>
      )}
    </div>
  );
}

