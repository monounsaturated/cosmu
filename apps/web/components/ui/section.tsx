import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function SectionHeader({
  eyebrow,
  title,
  aside,
  className
}: {
  eyebrow: string;
  title: ReactNode;
  aside?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-3", className)}>
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">{eyebrow}</div>
        <h2 className="mt-1.5 text-lg font-semibold tracking-tight text-foreground">{title}</h2>
      </div>
      {aside ? <div className="flex items-center gap-2">{aside}</div> : null}
    </div>
  );
}
