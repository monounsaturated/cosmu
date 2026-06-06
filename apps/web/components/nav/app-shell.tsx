"use client";

// module: the app shell. A collapsible icon-rail sidebar (Supabase / shadcn sidebar-07 behaviour:
// full labels expanded, icon-only + tooltips collapsed, state persisted), a mobile drawer, and the
// top header with the theme toggle. Wraps every page.

import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { Activity, Lock, PanelLeft, PanelLeftClose, ShieldCheck } from "lucide-react";
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
    ? engine.live ? "Live armed" : engine.state === "running" ? "Running · Simulation" : "Connected · Simulation"
    : engine.checked ? "Offline" : "Connecting…";
  const statusColor = engine.live ? "text-info" : engine.connected ? "text-up" : "text-quiet";

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

        <div className="mt-auto">
          {!collapsed && (
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

      <main className="min-w-0 pb-[calc(56px+env(safe-area-inset-bottom))] lg:pb-0">
        <header className="glass sticky top-0 z-20 flex items-center justify-between gap-4 border-b border-border/70 px-5 py-3 lg:px-7">
          <div className="flex items-center gap-2.5 text-[13px] text-muted">
            <span className="lg:hidden">
              <CosmuMark size={26} />
            </span>
            <button
              type="button"
              onClick={toggle}
              title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              className="hidden size-9 items-center justify-center rounded-md border border-border/70 text-muted transition-colors hover:bg-surface-2/60 hover:text-foreground lg:inline-flex"
            >
              {collapsed ? <PanelLeft className="size-[18px]" /> : <PanelLeftClose className="size-[18px]" />}
            </button>
            <span className="relative flex size-2">
              <span className={cn("animate-pulse-dot absolute inline-flex size-2 rounded-full", engine.connected ? "bg-up/70" : "bg-quiet/50")} />
              <span className={cn("relative inline-flex size-2 rounded-full", engine.connected ? "bg-up" : "bg-quiet")} />
            </span>
            <Activity className={cn("size-4", statusColor)} />
            <span className={cn("hidden sm:inline", statusColor)}>{statusLabel}</span>
            <span className={cn("sm:hidden", statusColor)}>{engine.connected ? (engine.live ? "Live" : "Simulation") : engine.checked ? "Off" : "…"}</span>
          </div>
          <div className="flex items-center gap-2">
            {engine.live ? (
              <Badge variant="info"><Activity className="size-3" /> Live</Badge>
            ) : (
              <Badge variant="muted"><Lock className="size-3" /> Simulation only</Badge>
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
