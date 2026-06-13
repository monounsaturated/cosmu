"use client";

// Generic modal (Iris Bento `.overlay` + `.modal`). Dimmed, blurred backdrop; click-outside or Esc
// closes. Used for confirmations (stop paper / liquidate live) and the Live "Rules" caps editor.
// Controlled via `open`/`onClose`. `actions` render in the right-aligned `.modal-actions` footer.

import type { CSSProperties, ReactNode } from "react";
import { useEffect } from "react";
import { cn } from "@/lib/utils";

export function Modal({
  open,
  onClose,
  title,
  titleColor,
  children,
  actions,
  width
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  titleColor?: string;
  children: ReactNode;
  actions?: ReactNode;
  width?: number;
}) {
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const modalStyle: CSSProperties | undefined = width ? { width } : undefined;

  return (
    <div className={cn("overlay", "open")} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" style={modalStyle}>
        <div className="modal-title" style={titleColor ? { color: titleColor } : undefined}>
          {title}
        </div>
        <div className="modal-body">{children}</div>
        {actions ? <div className="modal-actions">{actions}</div> : null}
      </div>
    </div>
  );
}
