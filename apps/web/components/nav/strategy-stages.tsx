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
  // Index of the current stage drives the "how far along" read: stages at or before the active one
  // are treated as reached (calm iris numbers); later stages stay quiet. Honest progress, no faking.
  const activeIndex = STAGES.findIndex((s) => isStageActive(pathname, s.href));
  return (
    <nav
      aria-label="Strategy lifecycle"
      className="glass flex items-center gap-0.5 overflow-x-auto rounded-lg border border-border/70 p-1"
    >
      {STAGES.map((stage, i) => {
        const active = isStageActive(pathname, stage.href);
        const reached = activeIndex >= 0 && i <= activeIndex;
        const Icon = stage.icon;
        return (
          <div key={stage.href} className="flex min-w-0 flex-1 items-center">
            <Link
              href={stage.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "group flex min-w-0 flex-1 items-center justify-center gap-2.5 rounded-md px-3 py-2 text-[12.5px] outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring/45",
                active
                  ? "bg-surface-2/80 text-foreground"
                  : "text-muted hover:bg-surface-2/50 hover:text-foreground",
                stage.gated && !active && "text-quiet"
              )}
            >
              {/* Numbered node — a calm step marker. Reached steps carry the iris tint; later steps stay quiet. */}
              <span
                className={cn(
                  "flex size-5 shrink-0 items-center justify-center rounded-full border text-[10.5px] font-semibold tabular transition-colors",
                  active
                    ? "border-iris/45 bg-iris/12 text-iris-soft"
                    : reached
                      ? "border-border-strong text-muted"
                      : "border-border text-quiet"
                )}
                aria-hidden
              >
                {stage.step}
              </span>
              <span className="flex min-w-0 flex-col leading-tight">
                <span className="flex items-center gap-1.5 truncate font-medium">
                  <Icon className={cn("size-3.5 shrink-0", active ? "text-iris-soft" : "text-quiet")} />
                  {stage.label}
                </span>
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
