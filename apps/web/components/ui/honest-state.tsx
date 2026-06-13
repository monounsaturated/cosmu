// module: honest empty/connect states (Iris Bento). The product NEVER fabricates a track record.
// When a surface has no real engine data it shows one of these honest states instead of numbers:
//   <NotConnected/>       — the engine is unreachable. Tells the operator EXACTLY what to set.
//   <EmptyState/>         — the engine IS connected but has nothing yet (no survivors, no trades, …).
//   <NotConnectedBanner/> — a slim inline banner so the rest of a page can render its own sub-states.
// Calm and informative, never alarmist, never a "demo".

import type { ReactNode } from "react";

export function NotConnected({ configured = false, what }: { configured?: boolean; what?: ReactNode }) {
  return (
    <div className="card">
      <div className="card-body" style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 11, padding: "52px 16px", textAlign: "center" }}>
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="var(--quiet)" strokeWidth={1.5} strokeLinecap="round" aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <line x1="6.2" y1="6.2" x2="17.8" y2="17.8" />
        </svg>
        <div className="kpi-label" style={{ color: "var(--quiet)" }}>Engine not connected</div>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--muted)", maxWidth: 480, lineHeight: 1.6 }}>
          {what ?? "This surface shows real engine data. Nothing is fabricated here."}
        </div>
        {!configured ? (
          <code style={{ fontFamily: '"SF Mono","Fira Code",ui-monospace,monospace', fontSize: 11.5, color: "var(--iris-s)", background: "var(--surf3)", border: "1px solid var(--border)", borderRadius: "var(--r-sm)", padding: "5px 9px", marginTop: 2 }}>
            set API_BASE_URL to your engine
          </code>
        ) : (
          <p className="quiet" style={{ fontSize: 11.5, maxWidth: 420, lineHeight: 1.5 }}>
            The engine is configured but did not respond. Once it is up, real data appears here.
          </p>
        )}
      </div>
    </div>
  );
}

export function EmptyState({ title, hint, icon }: { title: string; hint?: ReactNode; icon?: ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 8, padding: "40px 16px", textAlign: "center" }}>
      {icon ? <div className="quiet">{icon}</div> : null}
      <div style={{ fontSize: 13, color: "var(--muted)" }}>{title}</div>
      {hint ? <div className="quiet" style={{ fontSize: 11.5, maxWidth: 440, lineHeight: 1.5 }}>{hint}</div> : null}
    </div>
  );
}

export function NotConnectedBanner({ configured = false }: { configured?: boolean }) {
  return (
    <div className="live-banner" style={{ background: "var(--surf2)", borderColor: "var(--border)" }}>
      <span className="quiet" style={{ fontSize: 12 }}>
        Engine not connected — showing honest empty states, not fabricated numbers.
        {!configured ? (
          <>
            {" "}Set <code className="mono" style={{ color: "var(--iris-s)" }}>API_BASE_URL</code>.
          </>
        ) : null}
      </span>
    </div>
  );
}
