import { DragEvent, useId, useState } from "react";

interface Props {
  accept: string;
  label: string;
  hint: string;
  busy: boolean;
  busyLabel: string;
  onFile: (f: File) => void;
}

/** Click-or-drop file picker. The real <input type=file> stays keyboard reachable. */
export default function FileDrop({ accept, label, hint, busy, busyLabel, onFile }: Props) {
  const [over, setOver] = useState(false);
  const id = useId();

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f && !busy) onFile(f);
  };

  return (
    <label
      htmlFor={id}
      className={`dropzone${over ? " over" : ""}${busy ? " busy" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      aria-busy={busy}
    >
      <input
        id={id}
        type="file"
        accept={accept}
        disabled={busy}
        className="visually-hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
      <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden>
        <path d="M12 16V4m0 0-4 4m4-4 4 4M5 15v3a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <strong>{busy ? busyLabel : label}</strong>
      <span className="muted">{hint}</span>
    </label>
  );
}
