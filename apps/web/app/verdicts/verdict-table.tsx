"use client";

// Sortable + filterable verdict table. Client component — uses DataTablePage.

import type { VerdictRow } from "@/app/data";
import type { ColumnDef } from "@/components/ui/data-table-page";
import { DataTablePage } from "@/components/ui/data-table-page";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/honest-state";
import { ClipboardCheck } from "lucide-react";

type VerdictStyle = Record<VerdictRow["status"], { label: string; variant: "up" | "down" | "warn" | "muted" }>;

const COLUMNS: ColumnDef<VerdictRow>[] = [
  {
    key: "thesis",
    label: "Thesis",
    sortable: true,
    primaryOnCard: true,
    renderCell: (r) => (
      <div>
        <div className="font-medium text-foreground">{r.thesis}</div>
        {r.reason && <div className="mt-0.5 text-[11.5px] text-muted leading-relaxed">{r.reason}</div>}
      </div>
    )
  },
  {
    key: "status",
    label: "Verdict",
    sortable: true,
    renderCell: (r) => {
      const style = VERDICT_STYLE_DEFAULT[r.status] ?? VERDICT_STYLE_DEFAULT.FAIL;
      return <Badge variant={style.variant}>{style.label}</Badge>;
    }
  },
  {
    key: "date",
    label: "Date",
    sortable: true,
    renderCell: (r) => <span className="tabular text-[12px] text-quiet">{r.date || "—"}</span>
  },
  {
    key: "deflated_sharpe",
    label: "Deflated Sharpe",
    align: "right",
    sortable: true,
    renderCell: (r) => (
      <span className="tabular text-[12px] text-foreground">
        {r.deflated_sharpe !== null && Number.isFinite(r.deflated_sharpe)
          ? r.deflated_sharpe.toFixed(2)
          : "—"}
      </span>
    )
  },
  {
    key: "trades",
    label: "Trades",
    align: "right",
    sortable: true,
    renderCell: (r) => (
      <span className="tabular text-[12px] text-muted">{r.trades !== null ? r.trades : "—"}</span>
    )
  },
  {
    key: "cost_ratio",
    label: "Cost ratio",
    align: "right",
    sortable: true,
    renderCell: (r) => (
      <span className="tabular text-[12px] text-muted">
        {r.cost_ratio !== null && Number.isFinite(r.cost_ratio)
          ? `${(r.cost_ratio * 100).toFixed(2)}%`
          : "—"}
      </span>
    )
  }
];

// Fallback style if verdictStyle prop is not provided
const VERDICT_STYLE_DEFAULT: VerdictStyle = {
  PASS: { label: "PASS", variant: "up" },
  FAIL: { label: "FAIL", variant: "down" },
  "INSUFFICIENT-DATA": { label: "Insufficient data", variant: "warn" },
  "DATA-BLOCKED": { label: "Data-blocked", variant: "muted" }
};

export function VerdictTable({
  rows,
  verdictStyle: _verdictStyle
}: {
  rows: VerdictRow[];
  verdictStyle?: VerdictStyle;
}) {
  if (rows.length === 0) {
    return (
      <EmptyState
        title="No verdicts yet"
        hint="Every pre-registered thesis appears here once the Gate rules on it — PASS or FAIL. Nothing is fabricated."
        icon={<ClipboardCheck className="size-5" />}
      />
    );
  }

  return (
    <DataTablePage
      columns={COLUMNS}
      rows={rows}
      keyOf={(r) => r.slug}
      initialSort="date"
      initialDir="desc"
      searchPlaceholder="Search thesis, reason…"
      matchSearch={(r, q) =>
        r.thesis.toLowerCase().includes(q) ||
        (r.reason?.toLowerCase().includes(q) ?? false) ||
        r.status.toLowerCase().includes(q)
      }
      emptyLabel="No verdicts match the search."
    />
  );
}
