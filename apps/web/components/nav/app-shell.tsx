"use client";

// module: the app shell. A collapsible icon-rail sidebar (Supabase / shadcn sidebar-07 behaviour:
// full labels expanded, icon-only + tooltips collapsed, state persisted), a mobile drawer, and the
// top header with the theme toggle. Wraps every page.

import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { Activity, Lock, PanelLeft, PanelLeftClose } from "lucide-react";
import { CosmuMark, CosmuWordmark } from "@/components/brand/logo";
import { Badge } from "@/components/ui/badge";
import { MobileNav, SideNavLinks } from "@/components/nav/app-nav";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { cn } from "@/lib/utils";

export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);

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

        <div className="mt-auto flex flex-col gap-3">
          {!collapsed && (
            <div className="rounded-lg border border-border/70 bg-surface-2/40 p-3">
              <div className="flex items-center gap-2 text-[12px] font-medium text-foreground">
                <Lock className="size-3.5 text-warn" />
                Capital valve
              </div>
              <p className="mt-1.5 text-[11.5px] leading-snug text-quiet">
                LLM proposes, deterministic disposes. Live orders gated behind the toggle.
              </p>
            </div>
          )}
          <button
            type="button"
            onClick={toggle}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className={cn(
              "flex items-center gap-2 rounded-md border border-transparent py-2 text-[12.5px] text-muted transition-colors hover:border-border hover:bg-surface-2/60 hover:text-foreground",
              collapsed ? "justify-center px-0" : "px-3"
            )}
          >
            {collapsed ? <PanelLeft className="size-[17px]" /> : <PanelLeftClose className="size-[17px]" />}
            {!collapsed && <span>Collapse</span>}
          </button>
        </div>
      </aside>

      <main className="min-w-0">
        <header className="glass sticky top-0 z-20 flex items-center justify-between gap-4 border-b border-border/70 px-5 py-3 lg:px-7">
          <div className="flex items-center gap-2.5 text-[13px] text-muted">
            <MobileNav />
            <span className="relative flex size-2">
              <span className="animate-pulse-dot absolute inline-flex size-2 rounded-full bg-up/70" />
              <span className="relative inline-flex size-2 rounded-full bg-up" />
            </span>
            <Activity className="size-4 text-up" />
            <span className="hidden sm:inline">Paper farming on live-shadow data · scorer deterministic</span>
            <span className="sm:hidden">Paper farming</span>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="warn">
              <Lock className="size-3" />
              Live off by default
            </Badge>
            <ThemeToggle />
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}
