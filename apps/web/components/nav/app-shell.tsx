"use client";

// module: the app shell (Iris Bento `.shell`). A fixed bento sidebar — the ONLY persistent chrome —
// plus the `.main` content column. There is no top header: each page renders its own `.toolbar-row`
// (page title + page controls + theme toggle) via the shared <Toolbar/>. The sidebar collapses to an
// icon rail (toggle persisted to localStorage → `body.sb-collapsed`, the class the bento CSS targets;
// it also auto-collapses under 880px purely via CSS). Footer carries a live engine-health dot. Nav
// per-stage counts are fetched client-side from the engine proxy (shown only when real, never faked).

import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { CosmuMark } from "@/components/brand/logo";
import { SideNav, type NavCounts } from "@/components/nav/app-nav";
import { TipLayer } from "@/components/ui/tip-layer";
import { ENGINE_CONFIGURED, engineFetch } from "@/lib/engine";
import { cn } from "@/lib/utils";

type DotState = "on" | "off" | "warn";

function isPaper(status: string | null | undefined): boolean {
  const s = (status ?? "").toLowerCase();
  return s === "paper" || s === "forward_test" || s === "forward";
}

export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [counts, setCounts] = useState<NavCounts | undefined>(undefined);
  const [dot, setDot] = useState<DotState>("off");
  const [tip, setTip] = useState("Checking engine…");

  // Restore the persisted collapse choice and mirror it onto <body> (the class the bento CSS targets).
  useEffect(() => {
    let next = false;
    try {
      next = localStorage.getItem("cosmu.sidebar") === "1";
    } catch {
      /* ignore */
    }
    setCollapsed(next);
  }, []);
  useEffect(() => {
    document.body.classList.toggle("sb-collapsed", collapsed);
  }, [collapsed]);

  function toggle() {
    setCollapsed((c) => {
      const next = !c;
      try {
        localStorage.setItem("cosmu.sidebar", next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }

  // Engine health → footer dot. Probe /health, enrich with /autonomy/status; failure is an honest "off".
  useEffect(() => {
    if (!ENGINE_CONFIGURED) {
      setDot("off");
      setTip("Engine not configured — set NEXT_PUBLIC_API_BASE_URL");
      return;
    }
    let alive = true;
    async function probe() {
      try {
        const health = await engineFetch("/health");
        if (!health.ok) {
          if (alive) {
            setDot("off");
            setTip("Engine unreachable");
          }
          return;
        }
        let live = false;
        let running = false;
        try {
          const res = await engineFetch("/autonomy/status");
          if (res.ok) {
            const data = (await res.json()) as { running?: boolean; live_enabled?: boolean };
            live = Boolean(data.live_enabled);
            running = Boolean(data.running);
          }
        } catch {
          /* keep connected; no enrichment */
        }
        if (alive) {
          setDot(live ? "warn" : "on");
          setTip(live ? "Engine On · live armed" : running ? "Engine On · running (paper)" : "Engine On · idle");
        }
      } catch {
        if (alive) {
          setDot("off");
          setTip("Engine unreachable");
        }
      }
    }
    probe();
    const id = setInterval(probe, 15_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  // Best-effort nav counts from the leaderboard (client-side via the proxy; never blocks first paint).
  useEffect(() => {
    if (!ENGINE_CONFIGURED) return;
    let alive = true;
    (async () => {
      try {
        const res = await engineFetch("/leaderboard");
        if (!res.ok) return;
        const data = (await res.json()) as { rows?: { status?: string }[] };
        const rows = data.rows ?? [];
        if (!alive || rows.length === 0) return;
        setCounts({
          strategies: rows.length,
          paper: rows.filter((r) => isPaper(r.status)).length,
          live: rows.filter((r) => (r.status ?? "").toLowerCase() === "live").length
        });
      } catch {
        /* leave counts hidden */
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="sb-logo">
          <div className="sb-mark" style={{ background: "none", border: "none", boxShadow: "none", padding: 0 }}>
            <CosmuMark size={26} />
          </div>
          <div className="sb-text">
            <div className="sb-name">Cosmu</div>
          </div>
          <button className="sb-tog" onClick={toggle} title="Collapse / expand sidebar" aria-label="Collapse sidebar" type="button">
            <svg className="ic-collapse" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <rect width="18" height="18" x="3" y="3" rx="2" /><path d="M9 3v18" /><path d="m16 15-3-3 3-3" />
            </svg>
            <svg className="ic-expand" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <rect width="18" height="18" x="3" y="3" rx="2" /><path d="M9 3v18" /><path d="m14 9 3 3-3 3" />
            </svg>
          </button>
        </div>

        <SideNav counts={counts} />

        <div className="sb-footer">
          <div className="sb-dot-wrap" data-tip={tip}>
            <span className={cn("sb-dot", dot === "off" && "off", dot === "warn" && "warn")} />
          </div>
        </div>
      </aside>

      <div className="main">{children}</div>

      <TipLayer />
    </div>
  );
}
