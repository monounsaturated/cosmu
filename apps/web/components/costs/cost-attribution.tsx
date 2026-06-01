// module: CostAttribution — the per-strategy cost-vs-net table for the Costs/ROI view
// (Deliverable #1). For each funded Version it shows opex spent, net earned, and the resulting
// ROI multiple (net / opex), sorted by net so the clearest earners lead. Rows link to the Version
// detail page. Client component (row click → router); honest empty state when there is no
// per-strategy attribution yet. No fabricated rows — renders only what /costs returned.

"use client";

import { useRouter } from "next/navigation";
import type { CostPerStrategy } from "@/app/data";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState } from "@/components/ui/honest-state";
import { cn, formatUsd } from "@/lib/utils";

// ROI multiple: net return per dollar of opex. Undefined when no opex was spent (avoid div-by-zero
// — show an em dash rather than a fabricated ratio).
function roiMultiple(opex: number, net: number): number | null {
  if (opex <= 0) return null;
  return net / opex;
}

export function CostAttribution({ rows }: { rows: CostPerStrategy[] }) {
  const router = useRouter();

  if (!rows || rows.length === 0) {
    return (
      <EmptyState
        title="No per-strategy attribution yet."
        hint="Once Versions are funded and start accruing opex against net P&L, each one's cost-vs-net shows here."
      />
    );
  }

  // Most net first; the clearest contributors lead.
  const ordered = [...rows].sort((a, b) => b.net - a.net);

  return (
    <Table>
      <THead>
        <TR>
          <TH className="sticky-col">Version</TH>
          <TH className="text-right">Opex</TH>
          <TH className="text-right">Net</TH>
          <TH className="text-right">ROI</TH>
        </TR>
      </THead>
      <TBody>
        {ordered.map((row) => {
          const roi = roiMultiple(row.opex, row.net);
          return (
            <TR
              key={row.version_id}
              onClick={() => router.push(`/strategy/${row.version_id}`)}
              className="group cursor-pointer transition-colors hover:bg-surface-2/50"
            >
              <TD className="sticky-col group-hover:bg-surface-2/50">
                <div className="font-medium text-foreground">{row.name}</div>
                <div className="font-mono text-[11px] text-quiet">{row.version_id}</div>
              </TD>
              <TD className="text-right tabular text-muted">{formatUsd(row.opex, 0)}</TD>
              <TD className={cn("text-right tabular", row.net >= 0 ? "text-up" : "text-down")}>
                {row.net >= 0 ? "+" : "-"}
                {formatUsd(Math.abs(row.net), 0)}
              </TD>
              <TD className={cn("text-right tabular", roi === null ? "text-quiet" : roi >= 1 ? "text-up" : "text-warn")}>
                {roi === null ? "—" : `${roi.toFixed(1)}×`}
              </TD>
            </TR>
          );
        })}
      </TBody>
    </Table>
  );
}
