"use client";

// Generic right-side sheet (Iris Bento `.side-panel`). Slides in from the right with NO backdrop dim
// (deliberate — the table behind stays visible, matching the reference). Esc closes. Used by the
// Strategies screener to show a Version's detail sheet. Controlled via `open`/`onClose`.

import type { ReactNode } from "react";
import { useEffect } from "react";
import { cn } from "@/lib/utils";

export function SidePanel({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <div className={cn("side-panel", open && "open")} aria-hidden={!open}>
      <div className="panel-header">
        <span className="panel-title">{title}</span>
        <button className="panel-close" onClick={onClose} title="Close (Esc)" aria-label="Close" type="button">
          ✕
        </button>
      </div>
      <div className="panel-body">{open ? children : null}</div>
    </div>
  );
}
