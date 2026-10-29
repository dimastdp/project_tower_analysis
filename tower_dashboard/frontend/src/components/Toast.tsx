import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";

interface Toast { id: number; text: string }
const ToastCtx = createContext<(text: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

/** Success toasts, auto-dismissed after 4 s (AFD 3.7). Uses a manual popover so it sits in the top layer. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const region = useRef<HTMLDivElement>(null);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const push = useCallback((text: string) => {
    const id = nextId.current++;
    setToasts((t) => [...t, { id, text }]);
    window.setTimeout(() => dismiss(id), 4000);
  }, [dismiss]);

  useEffect(() => {
    const el = region.current as (HTMLDivElement & { showPopover?: () => void; hidePopover?: () => void }) | null;
    if (!el || !el.showPopover) return; // no Popover API: region stays position:fixed in normal flow
    const open = el.matches(":popover-open");
    if (toasts.length && !open) el.showPopover();
    if (!toasts.length && open) el.hidePopover?.();
  }, [toasts.length]);

  return (
    <ToastCtx.Provider value={push}>
      {children}
      {/* popover attribute set via spread: React 18 typings do not include it */}
      <div ref={region} className="toast-region" role="status" aria-live="polite" {...{ popover: "manual" }}>
        {toasts.map((t) => (
          <div key={t.id} className="toast">
            <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden><path d="m5 10.5 3 3 7-7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
            <span>{t.text}</span>
            <button className="toast-close" aria-label="Dismiss" onClick={() => dismiss(t.id)}>×</button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
