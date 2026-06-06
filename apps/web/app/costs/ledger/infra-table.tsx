"use client";

// Sortable infra lines table for the full cost ledger.

import type { InfraLine } from "@/app/data";
import type { ColumnDef } from "@/components/ui/data-table-page";
import { DataTablePage } from "@/components/ui/data-table-page";
import { Badge } from "@/components/ui/badge";
import { formatUsd } from "@/lib/utils";

const COLUMNS: ColumnDef<InfraLine>[] = [
  {
    key: "vendor",
    label: "Vendor",
    sortable: true,
    primaryOnCard: true,
    renderCell: (r) => <span className="font-medium text-foreground">{r.vendor}</span>
  },
  {
    key: "category",
    label: "Category",
    renderCell: (r) => (
      <Badge variant={r.category === "infra" ? "iris" : "muted"} className="text-[10px]">
        {r.category}
      </Badge>
    )
  },
  {
    key: "amount",
    label: "Mid / mo",
    align: "right",
    sortable: true,
    renderCell: (r) =>
      r.amount_max === 0 ? (
        <span className="text-up text-[11px]">free</span>
      ) : (
        <span className="tabular text-foreground">{formatUsd(r.amount)}</span>
      )
  },
  {
    key: "range",
    label: "Range",
    align: "right",
    renderCell: (r) =>
      r.amount_max === 0 ? (
        <span className="tabular text-[11px] text-muted">—</span>
      ) : (
        <span className="tabular text-[11px] text-muted">
          {formatUsd(r.amount_min)}–{formatUsd(r.amount_max)}
        </span>
      )
  },
  {
    key: "note",
    label: "Role",
    renderCell: (r) => (
      <span className="max-w-[220px] truncate text-[12px] text-quiet">{r.note}</span>
    )
  }
];

export function InfraTable({ rows }: { rows: InfraLine[] }) {
  return (
    <DataTablePage
      columns={COLUMNS}
      rows={rows}
      keyOf={(r) => r.vendor}
      initialSort="amount"
      initialDir="desc"
      searchPlaceholder="Search vendor, role…"
      matchSearch={(r, q) =>
        r.vendor.toLowerCase().includes(q) ||
        r.note.toLowerCase().includes(q) ||
        r.category.toLowerCase().includes(q)
      }
      emptyLabel="No infra lines match."
    />
  );
}
