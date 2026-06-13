"use client";

// module: the strategy lifecycle stage strip (Iris Bento). A calm left-to-right read of the pipeline —
// Discover → Backtest → Paper → Live — rendered as a `.chip-row` of links. The current stage is `.active`;
// every chip is a working link. Stages at or before the current one read as reached (iris dot); later ones
// stay quiet. Honest progress, no faking.
//
// Relationship to the section nav: the section nav switches SECTIONS; this strip is the LIFECYCLE flow.
// Used by the Paper and Live surfaces (the v18 Strategies screener leads with its own population strip and
// does not show this).

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const STAGES = [
  { href: "/lab", label: "Discover", dot: "var(--iris)" },
  { href: "/strategies", label: "Backtest", dot: "var(--iris)" },
  { href: "/paper", label: "Paper", dot: "var(--iris)" },
  { href: "/live", label: "Live", dot: "var(--down)" }
];

function isStageActive(pathname: string, href: string): boolean {
  if (href === "/strategies") return pathname.startsWith("/strategies") || pathname.startsWith("/strategy");
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function StrategyStages() {
  const pathname = usePathname();
  const activeIndex = STAGES.findIndex((s) => isStageActive(pathname, s.href));
  return (
    <div className="chip-row" aria-label="Strategy lifecycle" style={{ marginBottom: 4 }}>
      {STAGES.map((stage, i) => {
        const active = isStageActive(pathname, stage.href);
        const reached = activeIndex >= 0 && i <= activeIndex;
        return (
          <Link
            key={stage.href}
            href={stage.href}
            aria-current={active ? "page" : undefined}
            className={cn("chip", active && "active")}
            style={!reached && !active ? { opacity: 0.7 } : undefined}
          >
            <span className="chip-dot" style={{ background: reached || active ? stage.dot : "var(--border-s)" }} />
            {stage.label}
          </Link>
        );
      })}
    </div>
  );
}
