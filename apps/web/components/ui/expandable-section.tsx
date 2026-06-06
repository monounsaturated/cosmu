"use client";

// module: progressive-disclosure section. Renders `summary` immediately (the digestible view),
// then hides `children` behind a "Show more" toggle. State is local — no persistence needed.
// Use for any page section that dumps too much at once: collapse the secondary detail by default,
// let the operator reveal it on demand.

import { useState, type ReactNode } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";

interface ExpandableSectionProps {
  /** Always-visible summary (the digestible default). */
  summary?: ReactNode;
  /** Hidden detail, revealed on "Show more". */
  children: ReactNode;
  /** Label for the toggle button when collapsed (default: "Show more"). */
  showLabel?: string;
  /** Label for the toggle button when expanded (default: "Show less"). */
  hideLabel?: string;
  /** Start expanded? Default false. */
  defaultOpen?: boolean;
  /** Extra class on the wrapper div. */
  className?: string;
}

export function ExpandableSection({
  summary,
  children,
  showLabel = "Show more",
  hideLabel = "Show less",
  defaultOpen = false,
  className
}: ExpandableSectionProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className={cn("space-y-3", className)}>
      {summary}
      {open && <div className="space-y-3">{children}</div>}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "inline-flex min-h-[44px] w-full items-center justify-center gap-1.5 rounded-lg border border-border/60 bg-surface-2/20 px-4 text-[12.5px] font-medium text-muted",
          "transition-colors hover:border-border hover:bg-surface-2/50 hover:text-foreground",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
        )}
        aria-expanded={open}
      >
        {open ? (
          <>
            <ChevronUp className="size-3.5" /> {hideLabel}
          </>
        ) : (
          <>
            <ChevronDown className="size-3.5" /> {showLabel}
          </>
        )}
      </button>
    </div>
  );
}
