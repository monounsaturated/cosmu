"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

type ModalShellProps = {
  title: string;
  description?: string;
  wide?: boolean;
  children: ReactNode;
  onClose: () => void;
};

const focusableSelector = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])"
].join(",");

export function ModalShell({ title, description, wide, children, onClose }: ModalShellProps) {
  const [mounted, setMounted] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    const body = document.body;
    const previousActive = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = body.style.overflow;
    const openCount = Number(body.dataset.modalOpenCount ?? "0") + 1;
    body.dataset.modalOpenCount = String(openCount);
    body.style.overflow = "hidden";

    window.setTimeout(() => {
      const firstFocusable = dialogRef.current?.querySelector<HTMLElement>(focusableSelector);
      (firstFocusable ?? dialogRef.current)?.focus();
    }, 0);

    return () => {
      const nextCount = Math.max(0, Number(body.dataset.modalOpenCount ?? "1") - 1);
      if (nextCount === 0) {
        delete body.dataset.modalOpenCount;
        body.style.overflow = previousOverflow;
      } else {
        body.dataset.modalOpenCount = String(nextCount);
      }
      previousActive?.focus?.();
    };
  }, [mounted]);

  if (!mounted) return null;

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }

    if (event.key !== "Tab") return;

    const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(focusableSelector) ?? [])
      .filter((element) => element.offsetParent !== null || element === document.activeElement);
    if (focusable.length === 0) {
      event.preventDefault();
      dialogRef.current?.focus();
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return createPortal(
    <div className="modal-overlay" onMouseDown={onClose}>
      <div
        ref={dialogRef}
        className={`modal-content ${wide ? "modal-content-wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        onKeyDown={handleKeyDown}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="modal-grabber" aria-hidden="true" />
        <div className="modal-header">
          <div className="modal-title-block">
            <h2 id={titleId}>{title}</h2>
            {description ? <p id={descriptionId}>{description}</p> : null}
          </div>
          <button className="modal-close" type="button" onClick={onClose} aria-label="Close dialog">
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body
  );
}
