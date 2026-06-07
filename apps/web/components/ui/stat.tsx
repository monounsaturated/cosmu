import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Card } from "./card";

// A single KPI tile — the number is the hero (tabular, optically tight). A thin accent rail on the
// left carries semantic tone without coloring the figure itself. Optional `visual` slot for a
// sparkline/gauge on the right keeps it dense without clutter.
export function Stat({
  label,
  value,
  hint,
  accent,
  icon,
  visual
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  accent?: "iris" | "up" | "down" | "warn";
  icon?: ReactNode;
  visual?: ReactNode;
}) {
  const bar = {
    iris: "before:bg-iris",
    up: "before:bg-up",
    down: "before:bg-down",
    warn: "before:bg-warn"
  }[accent ?? "iris"];
  return (
    <Card
      className={cn(
        "relative overflow-hidden p-4 before:absolute before:left-0 before:top-4 before:bottom-4 before:w-0.5 before:rounded-full",
        bar
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="label-eyebrow">{label}</span>
        {icon ? <span className="text-quiet">{icon}</span> : null}
      </div>
      <div className="mt-2 flex items-end justify-between gap-3">
        <div className="num-hero min-w-0 text-2xl tabular text-foreground">{value}</div>
        {visual ? <div className="shrink-0 pb-0.5">{visual}</div> : null}
      </div>
      {hint ? <div className="mt-1.5 text-[12px] text-muted">{hint}</div> : null}
    </Card>
  );
}
