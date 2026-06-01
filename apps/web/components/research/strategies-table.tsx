"use client";

// module: strategies list for Research. The old leaderboard, trimmed and made useful: searchable
// by name, sortable by the money/quality columns, row click → /strategy/[id]. Lineage is demoted to
// a quiet secondary line under the name rather than its own column.

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowDown, ArrowUp, Search } from "lucide-react";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { Badge } from "@/components/ui/badge";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { cn, formatPct } from "@/lib/utils";

const statusVariant: Record<string, "up" | "warn" | "down" | "info"> = {
  paper: "up",
  live: "info",
  screening: "warn",
  killed: "down"
};

type SortKey = "name" | "status" | "sleeve_return_pct" | "net_pct" | "deflated_sharpe" | "pbo";

const numericKeys: SortKey[] = ["sleeve_return_pct", "net_pct", "deflated_sharpe", "pbo"];

export function StrategiesTable({ rows }: { rows: LeaderboardRow[] }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("deflated_sharpe");
  const [dir, setDir] = useState<"asc" | "desc">("desc");

  const sorted = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q ? rows.filter((r) => r.name.toLowerCase().includes(q) || r.status.toLowerCase().includes(q)) : rows;
    const mult = dir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * mult;
      return String(av).localeCompare(String(bv)) * mult;
    });
  }, [rows, query, sortKey, dir]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setDir(numericKeys.includes(key) ? "desc" : "asc");
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <div className="relative w-full max-w-xs">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-quiet" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search strategies…"
            className="h-8 w-full rounded-md border border-border bg-background/60 pl-8 pr-2 text-[12.5px] text-foreground outline-none transition-colors placeholder:text-quiet focus-visible:border-iris/60 focus-visible:ring-2 focus-visible:ring-ring/40"
          />
        </div>
        <span className="ml-auto text-[11.5px] text-quiet">{sorted.length} versions</span>
      </div>
      <Table>
        <THead>
          <TR>
            <SortTH label="Strategy" col="name" sortKey={sortKey} dir={dir} onClick={toggleSort} />
            <SortTH label="Status" col="status" sortKey={sortKey} dir={dir} onClick={toggleSort} />
            <SortTH label="Sleeve" col="sleeve_return_pct" sortKey={sortKey} dir={dir} onClick={toggleSort} align="right" />
            <SortTH label="Net" col="net_pct" sortKey={sortKey} dir={dir} onClick={toggleSort} align="right" />
            <SortTH label="D-Sharpe" col="deflated_sharpe" sortKey={sortKey} dir={dir} onClick={toggleSort} align="right" />
            <SortTH label="PBO" col="pbo" sortKey={sortKey} dir={dir} onClick={toggleSort} align="right" />
          </TR>
        </THead>
        <TBody>
          {sorted.map((row) => (
            <TR
              key={row.version_id}
              onClick={() => router.push(`/strategy/${row.version_id}`)}
              className="cursor-pointer transition-colors hover:bg-surface-2/50"
            >
              <TD>
                <div className="font-medium text-foreground">{row.name}</div>
                <div className="text-[11px] text-quiet">{row.lineage}</div>
              </TD>
              <TD>
                <Badge variant={statusVariant[row.status] ?? "muted"}>{row.status}</Badge>
              </TD>
              <TD className={`text-right tabular ${row.sleeve_return_pct >= 0 ? "text-up" : "text-down"}`}>
                {formatPct(row.sleeve_return_pct)}
              </TD>
              <TD className={`text-right tabular ${row.net_pct >= 0 ? "text-up" : "text-down"}`}>{formatPct(row.net_pct)}</TD>
              <TD className="text-right tabular text-foreground">{row.deflated_sharpe.toFixed(2)}</TD>
              <TD className="text-right tabular text-muted">{row.pbo.toFixed(2)}</TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}

function SortTH({
  label,
  col,
  sortKey,
  dir,
  onClick,
  align = "left"
}: {
  label: string;
  col: SortKey;
  sortKey: SortKey;
  dir: "asc" | "desc";
  onClick: (k: SortKey) => void;
  align?: "left" | "right";
}) {
  const active = sortKey === col;
  return (
    <TH className={align === "right" ? "text-right" : undefined}>
      <button
        type="button"
        onClick={() => onClick(col)}
        className={cn(
          "inline-flex items-center gap-1 transition-colors hover:text-foreground",
          align === "right" && "flex-row-reverse",
          active ? "text-foreground" : "text-muted"
        )}
      >
        {label}
        {active ? dir === "asc" ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" /> : null}
      </button>
    </TH>
  );
}
