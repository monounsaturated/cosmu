"use client";

// Root error boundary (Next.js App Router). This is the LAST line of defense against a white screen:
// it replaces the ENTIRE document — including the root layout and AppShell — when a render throws above
// every segment boundary. Because the layout (and the `import "./globals.css"` it carries) may be exactly
// what failed, this file ships its own <html>/<body> and CANNOT rely on the CSS variables or `.card`
// classes the rest of the app uses. So it reproduces the Iris Bento look with LITERAL token values
// (the same oklch() the dark default theme defines in globals.css) and inline styles only.
//
// Contained + retryable, never a blank page or a stack trace dump. `reset()` re-attempts the render.

import { useEffect } from "react";

// Literal copies of the dark-default tokens (globals.css :root) — see header for why we can't use var().
const BG = "oklch(0.155 0.017 285)";
const SURF2 = "oklch(0.230 0.020 286)";
const FG = "oklch(0.965 0.004 286)";
const MUTED = "oklch(0.68 0.014 286)";
const QUIET = "oklch(0.52 0.013 286)";
const BORDER = "oklch(0.280 0.015 286)";
const IRIS = "oklch(0.66 0.19 290)";
const IRIS_S = "oklch(0.74 0.135 290)";

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    // A prod client crash is invisible to server logs — leave a console breadcrumb (with the digest).
    console.error("[cosmu] root render error", error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100dvh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: 24,
          background: BG,
          color: FG,
          colorScheme: "dark",
          fontFamily:
            '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif',
        }}
      >
        <div
          style={{
            width: "100%",
            maxWidth: 460,
            background: SURF2,
            border: `1px solid ${BORDER}`,
            borderRadius: 13,
            padding: "48px 28px",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 13,
            textAlign: "center",
            boxShadow: "0 16px 36px -12px rgba(0,0,0,.85)",
          }}
        >
          <svg
            width="26"
            height="26"
            viewBox="0 0 24 24"
            fill="none"
            stroke={QUIET}
            strokeWidth={1.5}
            strokeLinecap="round"
            aria-hidden="true"
          >
            <path d="M10.3 3.6 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.6a2 2 0 0 0-3.4 0Z" />
            <line x1="12" y1="9" x2="12" y2="13.5" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: ".09em", textTransform: "uppercase", color: QUIET }}>
            Something went wrong
          </div>
          <div style={{ fontSize: 13, fontWeight: 500, color: MUTED, maxWidth: 380, lineHeight: 1.6 }}>
            The dashboard hit an unexpected error and stopped rendering. Your data is safe — nothing was changed.
            Reload to try again.
          </div>
          <button
            type="button"
            onClick={() => reset()}
            style={{
              marginTop: 4,
              fontFamily: "inherit",
              fontSize: 13,
              fontWeight: 600,
              color: FG,
              background: IRIS,
              border: "none",
              borderRadius: 8,
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
                fontSize: 11,
                color: IRIS_S,
                marginTop: 2,
              }}
            >
              ref {error.digest}
            </code>
          ) : null}
        </div>
      </body>
    </html>
  );
}
