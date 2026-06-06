"use client";

// Sortable supplier table for the full cost ledger.

import { Wifi, WifiOff } from "lucide-react";
import type { SupplierRow } from "@/app/data/supplier-costs";
import type { ColumnDef } from "@/components/ui/data-table-page";
import { DataTablePage } from "@/components/ui/data-table-page";
import { Badge } from "@/components/ui/badge";
import { formatUsd, timeAgo } from "@/lib/utils";

const COLUMNS: ColumnDef<SupplierRow>[] = [
  {
    key: "name",
    label: "Supplier",
    sortable: true,
    primaryOnCard: true,
    renderCell: (r) => (
      <div className="flex items-center gap-2">
        <span className="font-medium text-foreground">{r.name}</span>
        <Badge
          variant={r.category === "llm" ? "iris" : r.category === "data" ? "info" : "muted"}
          className="text-[10px]"
        >
          {r.category}
        </Badge>
      </div>
    )
  },
  {
    key: "role",
    label: "Role",
    renderCell: (r) => (
      <span className="max-w-[260px] truncate text-[12px] text-quiet">{r.role}</span>
    )
  },
  {
    key: "amount_usd",
    label: "$/mo",
    align: "right",
    sortable: true,
    renderCell: (r) =>
      r.amount_usd === 0 ? (
        <span className="text-up text-[11px]">free / $0</span>
      ) : (
        <span className="tabular text-foreground">{formatUsd(r.amount_usd)}</span>
      )
  },
  {
    key: "source",
    label: "Source",
    renderCell: (r) =>
      r.source === "live" ? (
        <span className="inline-flex items-center gap-1 text-[11px] text-up">
          <Wifi className="size-3" /> live
        </span>
      ) : (
        <span className="inline-flex items-center gap-1 text-[11px] text-muted">
          <WifiOff className="size-3" /> est.
        </span>
      )
  },
  {
    key: "fetched_at",
    label: "Fetched",
    align: "right",
    sortable: true,
    renderCell: (r) => {
      const ago = timeAgo(r.fetched_at);
      return <span className="tabular text-[11px] text-quiet">{ago ? `${ago}` : "—"}</span>;
    }
  }
];

export function SupplierTable({ rows, total }: { rows: SupplierRow[]; total: number }) {
  return (
    <div className="space-y-4">
      <DataTablePage
        columns={COLUMNS}
        rows={rows}
        keyOf={(r) => r.name}
        initialSort="amount_usd"
        initialDir="desc"
        searchPlaceholder="Search supplier, role…"
        matchSearch={(r, q) =>
          r.name.toLowerCase().includes(q) ||
          r.role.toLowerCase().includes(q) ||
          r.category.toLowerCase().includes(q)
        }
        emptyLabel="No suppliers match."
      />
      <div className="flex items-center justify-between border-t border-border/50 pt-3 text-[12.5px]">
        <span className="text-quiet">Total (real + estimates)</span>
        <span className="font-semibold tabular text-foreground">{formatUsd(total)}</span>
      </div>
    </div>
  );
}
