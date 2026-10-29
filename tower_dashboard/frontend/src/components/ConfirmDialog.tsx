import { useEffect, useId, useRef } from "react";

interface Props {
  open: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  onConfirm: () => void;
  onClose: () => void;
}

/** Destructive confirmation using a native modal <dialog>; Cancel gets initial focus. */
export default function ConfirmDialog({ open, title, message, confirmLabel, onConfirm, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      className="confirm"
      aria-labelledby={titleId}
      onClose={() => {
        const d = ref.current!;
        if (d.returnValue === "confirm") onConfirm();
        d.returnValue = "";
        onClose();
      }}
    >
      <h2 id={titleId}>{title}</h2>
      <p>{message}</p>
      <form method="dialog" className="dialog-actions">
        <button className="btn danger-fill" value="confirm">{confirmLabel}</button>
        <button className="btn" value="cancel" autoFocus>Cancel</button>
      </form>
    </dialog>
  );
}
