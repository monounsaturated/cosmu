"use client";

// Segment error boundary (Next.js App Router). Catches a render throw inside a ROUTE while the root layout
// — and therefore the AppShell sidebar/chrome — stays mounted. So unlike global-error.tsx this one lives
// inside the normal document and CAN use the real `.card` classes + Iris Bento CSS variables (it copies the
// visual language of components/ui/honest-state.tsx `NotConnected`). Shows a contained, retryable card so a
// single bad page never white-screens the whole app; `reset()` re-attempts the segment render.

import { useEffect } from "react";

export default function Error({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    // A prod client crash is invisible to server logs — leave a console breadcrumb (with the digest).
    console.error("[cosmu] page render error", error);
  }, [error]);

  return (
    <div className="card">
      <div
        className="card-body"
        style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 11, padding: "52px 16px", textAlign: "center" }}
      >
        <svg
          width="26"
          height="26"
          viewBox="0 0 24 24"
          fill="none"
          stroke="var(--quiet)"
          strokeWidth={1.5}
          strokeLinecap="round"
          aria-hidden="true"
        >
          <path d="M10.3 3.6 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.6a2 2 0 0 0-3.4 0Z" />
          <line x1="12" y1="9" x2="12" y2="13.5" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
        <div className="kpi-label" style={{ color: "var(--quiet)" }}>Something went wrong</div>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--muted)", maxWidth: 480, lineHeight: 1.6 }}>
          This page hit an unexpected error and stopped rendering. Your data is safe — nothing was changed. Reload to try again.
        </div>
        <button
          type="button"
          onClick={() => reset()}
          style={{
            marginTop: 2,
            fontFamily: "inherit",
            fontSize: 13,
            fontWeight: 600,
            color: "var(--fg)",
            background: "var(--iris)",
            border: "none",
            borderRadius: "var(--r-sm)",
            padding: "9px 18px",
            cursor: "pointer",
          }}
        >
          Reload
        </button>
        {error.digest ? (
          <code
            style={{
              fontFamily: '"SF Mono","Fira Code",ui-monospace,monospace',
              fontSize: 11.5,
              color: "var(--iris-s)",
              marginTop: 2,
            }}
          >
            ref {error.digest}
          </code>
        ) : null}
      </div>
    </div>
  );
}
