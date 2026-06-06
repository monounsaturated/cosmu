// module: DataPreview — renders the top N (default 5) most-recent/important rows of a data type
// with a clear "View all →" link to a dedicated full-data page.
//
// Role vs ExpandableSection: DataPreview = at-a-glance summary that links OUT to a full page
// (navigation). ExpandableSection = expand MORE of the same section IN-PLACE (progressive
// disclosure). They are non-redundant: use DataPreview when there is a richer, paginated/sortable
// dedicated page to go to; use ExpandableSection to reveal secondary details that belong on the
// same page.

import type { ReactNode } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface DataPreviewProps {
  /** Link to the full-data page. Required — a preview without a destination is just a table. */
  href: string;
  /** "View all" label suffix (e.g. "all 42 strategies"). Default: "View all" */
  viewAllLabel?: string;
  /** Total item count, shown next to "View all". */
  total?: number;
  /** Preview rows — caller slices to N before passing. */
  children: ReactNode;
  /** Empty state content — rendered when children is empty. */
  empty?: ReactNode;
  /** Extra classes on the wrapper. */
  className?: string;
}

export function DataPreview({
  href,
  viewAllLabel,
  total,
  children,
  empty,
  className
}: DataPreviewProps) {
  const label = viewAllLabel ?? "View all";
  const countStr = typeof total === "number" ? ` ${total.toLocaleString()}` : "";

  return (
    <div className={cn("space-y-3", className)}>
      {children ?? empty}
      <Link
        href={href}
        className={cn(
          "inline-flex min-h-[40px] w-full items-center justify-center gap-1.5 rounded-lg border border-border/60 bg-surface-2/20 px-4 text-[12.5px] font-medium text-muted",
          "transition-colors hover:border-border hover:bg-surface-2/50 hover:text-foreground",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
        )}
      >
        {label}{countStr}
        <ArrowRight className="size-3.5" />
      </Link>
    </div>
  );
}
