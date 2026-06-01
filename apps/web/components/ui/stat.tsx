import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { Card } from "./card";

export function Stat({
  label,
  value,
  hint,
  accent,
  icon
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  accent?: "iris" | "up" | "down" | "warn";
  icon?: ReactNode;
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
        <span className="text-[11px] font-medium uppercase tracking-[0.07em] text-quiet">{label}</span>
        {icon ? <span className="text-muted">{icon}</span> : null}
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-tight tabular text-foreground">{value}</div>
      {hint ? <div className="mt-1.5 text-[12px] text-muted">{hint}</div> : null}
    </Card>
  );
}
