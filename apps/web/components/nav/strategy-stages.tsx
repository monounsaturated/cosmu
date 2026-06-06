"use client";

// module: the strategy lifecycle stage strip. Renders on EVERY lifecycle page so you can move between
// the 4 stages from anywhere. The mental model reads left-to-right: Discover → Backtest → Simulation →
// Live. The current stage is highlighted; every tab is a working link.
//
// Relationship to the bottom/section nav: the section nav (Overview / Lab / Strategies / Live / …) is
// for switching SECTIONS. This strip is the LIFECYCLE flow within the trading pipeline. Non-redundant:
// section nav is "where am I in the app", stage strip is "where am I in the pipeline".

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronRight, LineChart, ListChecks, Microscope, Radio } from "lucide-react";
import { cn } from "@/lib/utils";

const STAGES = [
  { href: "/lab", label: "Discover", desc: "idea → spec", icon: Microscope, step: "1" },
  { href: "/strategies", label: "Backtest", desc: "historical data", icon: ListChecks, step: "2" },
  { href: "/forward-test", label: "Simulation", desc: "live data, no money", icon: LineChart, step: "3" },
  { href: "/live", label: "Live", desc: "real capital", icon: Radio, gated: true, step: "4" }
];

function isStageActive(pathname: string, href: string): boolean {
  if (href === "/strategies") return pathname.startsWith("/strategies") || pathname.startsWith("/strategy");
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function StrategyStages() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Strategy lifecycle"
      className="glass flex items-center gap-0.5 overflow-x-auto rounded-lg border border-border/70 p-1"
    >
      {STAGES.map((stage, i) => {
        const active = isStageActive(pathname, stage.href);
        const Icon = stage.icon;
        return (
          <div key={stage.href} className="flex min-w-0 flex-1 items-center">
            <Link
              href={stage.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex min-w-0 flex-1 items-center justify-center gap-2 rounded-md px-3 py-2 text-[12.5px] transition-colors",
                active
                  ? "bg-surface-2/80 text-foreground"
                  : "text-muted hover:bg-surface-2/50 hover:text-foreground",
                stage.gated && !active && "text-quiet"
              )}
            >
              <Icon className={cn("size-4 shrink-0", active ? "text-iris-soft" : "text-quiet")} />
              <span className="flex min-w-0 flex-col leading-tight">
                <span className="truncate font-medium">{stage.label}</span>
                <span className="hidden truncate text-[10px] text-quiet sm:block">{stage.desc}</span>
              </span>
            </Link>
            {i < STAGES.length - 1 && (
              <ChevronRight className="mx-0.5 size-3 shrink-0 text-quiet/40" aria-hidden />
            )}
          </div>
        );
      })}
    </nav>
  );
}
