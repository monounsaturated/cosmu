"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { Activity, Lock } from "lucide-react";
import { CosmuWordmark } from "@/components/brand/logo";
import { Badge } from "@/components/ui/badge";
import { TopNav } from "@/components/nav/top-nav";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { ENGINE_CONFIGURED, engineFetch } from "@/lib/engine";
import { cn } from "@/lib/utils";

type EngineStatus = { state: string; live: boolean; connected: boolean; checked: boolean };

function useEngineStatus(): EngineStatus {
  const [status, setStatus] = useState<EngineStatus>({ state: "", live: false, connected: false, checked: false });
  useEffect(() => {
    if (!ENGINE_CONFIGURED) {
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
  const engine = useEngineStatus();

  const statusLabel = engine.connected
    ? engine.live ? "Live armed" : engine.state === "running" ? "Running" : "Connected"
    : engine.checked ? "Offline" : "Connecting…";
  const statusColor = engine.live ? "text-info" : engine.connected ? "text-up" : "text-quiet";

  return (
    <div className="flex min-h-screen flex-col">
      <header className="glass sticky top-0 z-20 flex items-center justify-between gap-4 border-b border-border/70 px-5 py-3">
        <div className="flex items-center gap-5">
          <CosmuWordmark />
          <TopNav />
        </div>
        <div className="flex items-center gap-3">
          <div className="hidden items-center gap-2 text-[12.5px] sm:flex">
            <span className="relative flex size-2">
              <span className={cn("animate-pulse-dot absolute inline-flex size-2 rounded-full", engine.connected ? "bg-up/70" : "bg-quiet/50")} />
              <span className={cn("relative inline-flex size-2 rounded-full", engine.connected ? "bg-up" : "bg-quiet")} />
            </span>
            <Activity className={cn("size-3.5", statusColor)} />
            <span className={statusColor}>{statusLabel}</span>
          </div>
          {engine.live ? (
            <Badge variant="info"><Activity className="size-3" /> Live</Badge>
          ) : (
            <Badge variant="muted"><Lock className="size-3" /> Sim</Badge>
          )}
          <ThemeToggle />
        </div>
      </header>
      <main className="flex-1">
        {children}
      </main>
    </div>
  );
}
