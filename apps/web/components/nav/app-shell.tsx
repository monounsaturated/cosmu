"use client";

// module: the app shell. A collapsible icon-rail sidebar (Supabase / shadcn sidebar-07 behaviour:
// full labels expanded, icon-only + tooltips collapsed, state persisted), a mobile drawer, and the
// top header with the theme toggle. Wraps every page.

import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { Lock, PanelLeft, PanelLeftClose, ShieldCheck } from "lucide-react";
import { CosmuMark, CosmuWordmark } from "@/components/brand/logo";
import { Badge } from "@/components/ui/badge";
import { BottomNav, SideNavLinks } from "@/components/nav/app-nav";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { ENGINE_CONFIGURED, engineFetch } from "@/lib/engine";
import { cn } from "@/lib/utils";

type EngineStatus = { state: string; live: boolean; connected: boolean; checked: boolean };

// Connectivity is resolved from the REAL liveness endpoint (/health): if /health answers OK the header
// reads "Connected" (Sim/Live), otherwise "Offline". The autonomy status only ENRICHES the label
// (running, live armed) and never gates connectivity — so the header can never get stuck on "Connecting…".
function useEngineStatus(): EngineStatus {
  const [status, setStatus] = useState<EngineStatus>({ state: "", live: false, connected: false, checked: false });
  useEffect(() => {
    if (!ENGINE_CONFIGURED) {
      // No engine wired at all — that's a settled, honest "Offline", not a pending connect.
      setStatus((s) => ({ ...s, checked: true }));
      return;
    }
    let alive = true;
    async function probe() {
      try {
        const health = await engineFetch("/health");
        if (!health.ok) {
          if (alive) setStatus((s) => ({ ...s, connected: false, checked: true }));
          return;
        }
        // Connected. Best-effort enrich with live/running state; failure here never flips connected.
        let live = false;
        let state = "idle";
        try {
          const res = await engineFetch("/autonomy/status");
          if (res.ok) {
            const data = (await res.json()) as { running?: boolean; live_enabled?: boolean };
            live = Boolean(data.live_enabled);
            state = data.running ? "running" : "idle";
          }
        } catch {
          /* keep connected; just no enrichment */
        }
        if (alive) setStatus({ state, live, connected: true, checked: true });
      } catch {
        if (alive) setStatus((s) => ({ ...s, connected: false, checked: true }));
      }
    }
    probe();
    const id = setInterval(probe, 15_000);
    return () => { alive = false; clearInterval(id); };
  }, []);
  return status;
}

export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const engine = useEngineStatus();

  useEffect(() => {
    try {
      setCollapsed(localStorage.getItem("cosmu.sidebar") === "1");
    } catch {
      /* ignore */
    }
  }, []);

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

  const statusLabel = engine.connected
    ? engine.live ? "Live armed" : engine.state === "running" ? "Running · Paper" : "Connected · Paper"
    : engine.checked ? "Offline" : "Connecting…";
  const statusColor = engine.live ? "text-info" : engine.connected ? "text-up" : "text-quiet";
  const dotColor = engine.live ? "bg-info" : engine.connected ? "bg-up" : "bg-quiet";

  return (
    <div
      className={cn(
        "mx-auto grid min-h-screen max-w-[1560px] grid-cols-1 transition-[grid-template-columns] duration-200",
        collapsed ? "lg:grid-cols-[64px_minmax(0,1fr)]" : "lg:grid-cols-[248px_minmax(0,1fr)]"
      )}
    >
      <aside className={cn("glass sticky top-0 hidden h-screen flex-col border-r border-border/70 py-4 lg:flex", collapsed ? "px-2" : "px-4")}>
        <div className={cn("flex items-center pb-4", collapsed ? "justify-center" : "justify-between px-1")}>
          {collapsed ? <CosmuMark size={28} /> : <CosmuWordmark />}
        </div>

        <SideNavLinks collapsed={collapsed} />

        <div className="mt-auto pt-3">
          {collapsed ? (
            <div
              className="mx-auto flex size-9 items-center justify-center rounded-lg border border-border/70 bg-surface-2/40 text-iris-soft"
              title="Safety: live trading is off until you arm it. The Gate decides what gets money — never the model."
            >
              <ShieldCheck className="size-4" />
            </div>
          ) : (
            <div className="rounded-lg border border-border/70 bg-surface-2/40 p-3">
              <div className="flex items-center gap-2 text-[12px] font-medium text-foreground">
                <ShieldCheck className="size-3.5 text-iris-soft" />
                Safety
              </div>
              <p className="mt-1.5 text-[11.5px] leading-snug text-quiet">
                Live trading is off until you arm it. The Gate decides what gets money — never the model.
              </p>
            </div>
          )}
        </div>
      </aside>

      <main className="min-w-0 pb-[calc(64px+env(safe-area-inset-bottom))] lg:pb-0">
        <header className="header-safe glass sticky top-0 z-20 flex min-h-[52px] items-center justify-between gap-4 border-b border-border/70 px-4 py-2.5 sm:px-5 sm:py-3 lg:px-7">
          <div className="flex items-center gap-2.5">
            <span className="lg:hidden">
              <CosmuMark size={26} />
            </span>
            <button
              type="button"
              onClick={toggle}
              title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              className="hidden size-9 items-center justify-center rounded-md border border-border/70 text-quiet transition-colors hover:bg-surface-2/60 hover:text-foreground lg:inline-flex"
            >
              {collapsed ? <PanelLeft className="size-[18px]" /> : <PanelLeftClose className="size-[18px]" />}
            </button>
            {/* Connectivity — a single, contained status pill. The dot is the live truth; the label
                enriches it. Calm by default, never alarmist. */}
            <span className="inline-flex items-center gap-2 rounded-full border border-border/70 bg-surface-2/40 px-2.5 py-1 text-[12.5px]">
              <span className="relative flex size-2">
                <span className={cn("animate-pulse-dot absolute inline-flex size-2 rounded-full", engine.connected ? "opacity-70" : "opacity-50", dotColor)} />
                <span className={cn("relative inline-flex size-2 rounded-full", dotColor)} />
              </span>
              <span className={cn("hidden font-medium sm:inline", statusColor)}>{statusLabel}</span>
              <span className={cn("font-medium sm:hidden", statusColor)}>{engine.connected ? (engine.live ? "Live" : "Sim") : engine.checked ? "Off" : "…"}</span>
            </span>
          </div>
          <div className="flex items-center gap-2">
            {engine.live ? (
              <Badge variant="info" dot>Live</Badge>
            ) : (
              <Badge variant="muted"><Lock className="size-3" /> Paper only</Badge>
            )}
            <ThemeToggle />
          </div>
        </header>
        {children}
      </main>

      <BottomNav />
    </div>
  );
}
