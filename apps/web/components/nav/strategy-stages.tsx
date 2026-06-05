"use client";

// module: the strategy lifecycle filter strip. The stages (Discover → Screened → Forward-test → Live)
// used to be top-level nav tabs; they're now stage-filters that live INSIDE Strategies. Rendered at the
// top of /strategies and each stage route so the mental model (discover → screen → prove → live) reads
// straight off the strip and deep links land with the right segment lit. Each segment is a real route.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LineChart, ListChecks, Microscope, Radio } from "lucide-react";
import { cn } from "@/lib/utils";

const STAGES = [
  { href: "/lab", label: "Discover", desc: "research", icon: Microscope },
  { href: "/strategies", label: "Screened", desc: "pipeline", icon: ListChecks },
  { href: "/strategies", label: "Forward-test", desc: "proving", icon: LineChart },
  { href: "/live", label: "Live", desc: "real money", icon: Radio, gated: true }
];

function isStageActive(pathname: string, href: string): boolean {
  if (href === "/strategies") return pathname.startsWith("/strategies") || pathname.startsWith("/strategy");
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function StrategyStages() {
  const pathname = usePathname();
  // First match wins — prevents two stages sharing a href (e.g. Screened + Forward-test both
  // pointing to /strategies) from both appearing active at once.
  let claimed = false;
  return (
    <nav
      aria-label="Strategy lifecycle"
      className="glass flex gap-1 overflow-x-auto rounded-lg border border-border/70 p-1"
    >
      {STAGES.map((stage) => {
        const matches = isStageActive(pathname, stage.href);
        const active = matches && !claimed;
        if (matches) claimed = true;
        const Icon = stage.icon;
        return (
          <Link
            key={stage.href}
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
        );
      })}
    </nav>
  );
}
