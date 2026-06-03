// module: lightweight, dependency-free tooltip. An "i"-style trigger (or any children) that reveals
// a small explanation on hover AND keyboard focus. Pure CSS reveal so it works in server components,
// respects reduced-motion (see globals.css), and never blocks layout. Used to disambiguate the money
// figures (SIM / LIVE, per-track % vs aggregate read-out) without cluttering the surface.

import type { ReactNode } from "react";
import { Info } from "lucide-react";
import { cn } from "@/lib/utils";

export function Tooltip({
  content,
  children,
  className,
  side = "bottom"
}: {
  content: ReactNode;
  children?: ReactNode;
  className?: string;
  side?: "top" | "bottom";
}) {
  return (
    <span className={cn("group/tt relative inline-flex items-center", className)}>
      <span
        tabIndex={0}
        role="note"
        className="inline-flex cursor-help items-center rounded-full outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
      >
        {children ?? <Info className="size-3.5 text-quiet transition-colors group-hover/tt:text-iris-soft" />}
      </span>
      <span
        role="tooltip"
        className={cn(
          "tooltip-bubble pointer-events-none absolute left-1/2 z-40 w-[min(78vw,250px)] -translate-x-1/2 rounded-lg border border-border bg-surface px-3 py-2 text-[11.5px] leading-relaxed text-muted opacity-0 shadow-card transition-opacity duration-150 group-hover/tt:opacity-100 group-focus-within/tt:opacity-100",
          side === "bottom" ? "top-full mt-2" : "bottom-full mb-2"
        )}
      >
        {content}
      </span>
    </span>
  );
}
