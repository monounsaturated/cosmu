"use client";

// module: DataTablePage — shared sortable + filterable full-data view.
//
// Renders a search bar, optional sort controls, and a paginated table body.
// Caller supplies:
//   - `columns`: ordered column definitions (key, label, align, sortable, renderCell)
//   - `rows`: typed row data (already filtered server-side or full set for client-side)
//   - `keyOf`: row → stable string key
//
// Sorting and search are client-side; pass `initialSort` and `initialDir` for server-aware
// initial state. Paginated at 25 rows per page (overridable via `pageSize`). On mobile the
// table collapses to stacked cards — each row becomes a small card with key/value pairs.
//
// Does NOT do data fetching — callers pass props from their server component.

import { useMemo, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight } from "lucide-react";
import { SearchInput } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export interface ColumnDef<T> {
  /** Unique key for this column (also used as sort key). */
  key: string;
  /** Column header label. */
  label: string;
  /** Text alignment for header + cells. Default "left". */
  align?: "left" | "right" | "center";
  /** Is this column sortable? Default false. */
  sortable?: boolean;
  /** Render function for the cell value. Receives the full row. */
  renderCell: (row: T) => ReactNode;
  /** Optional card label override (shown on mobile stacked card). Defaults to `label`. */
  cardLabel?: string;
  /** If true, this column is omitted on mobile cards. Default false. */
  hideOnCard?: boolean;
  /** If true, this column is highlighted as the "primary" field on mobile cards. */
  primaryOnCard?: boolean;
}

interface DataTablePageProps<T> {
  columns: ColumnDef<T>[];
  rows: T[];
  keyOf: (row: T) => string;
  /** Default sort column key. */
  initialSort?: string;
  /** Default sort direction. */
  initialDir?: "asc" | "desc";
  /** Rows per page. Default 25. */
  pageSize?: number;
  /** Placeholder text for the search box. */
  searchPlaceholder?: string;
  /** Function to test if a row matches the search query. Default: JSON.stringify match. */
  matchSearch?: (row: T, query: string) => boolean;
  /** Comparator for sorting. Default: tries numeric then lexicographic. */
  comparator?: (a: T, b: T, key: string) => number;
  /** Shown when no rows match after search/filter. */
  emptyLabel?: string;
  /** Optional header action slot (e.g. a "Back" link). */
  headerAction?: ReactNode;
  /** Optional row click handler. */
  onRowClick?: (row: T) => void;
}

export function DataTablePage<T>({
  columns,
  rows,
  keyOf,
  initialSort,
  initialDir = "desc",
  pageSize = 25,
  searchPlaceholder = "Search…",
  matchSearch,
  comparator,
  emptyLabel = "No rows match.",
  headerAction,
  onRowClick
}: DataTablePageProps<T>) {
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<string | undefined>(initialSort);
  const [sortDir, setSortDir] = useState<"asc" | "desc">(initialDir);
  const [page, setPage] = useState(0);

  // Search
  const searched = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    if (matchSearch) return rows.filter((r) => matchSearch(r, q));
    return rows.filter((r) => JSON.stringify(r).toLowerCase().includes(q));
  }, [rows, query, matchSearch]);

  // Sort
  const sorted = useMemo(() => {
    if (!sortKey) return searched;
    return [...searched].sort((a, b) => {
      const cmp = comparator
        ? comparator(a, b, sortKey)
        : defaultComparator(a, b, sortKey);
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [searched, sortKey, sortDir, comparator]);

  // Pagination
  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const paginated = sorted.slice(safePage * pageSize, (safePage + 1) * pageSize);

  function toggleSort(key: string) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
    setPage(0);
  }

  function handleSearch(v: string) {
    setQuery(v);
    setPage(0);
  }

  return (
    <div className="space-y-4">
      {/* Search + header action */}
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput
          className="flex-1 sm:flex-none"
          value={query}
          onChange={(e) => handleSearch(e.target.value)}
          onClear={() => handleSearch("")}
          placeholder={searchPlaceholder}
        />
        <span className="ml-auto text-[11.5px] text-quiet tabular">
          {sorted.length.toLocaleString()} row{sorted.length !== 1 ? "s" : ""}
          {query ? ` · filtered from ${rows.length.toLocaleString()}` : ""}
        </span>
        {headerAction}
      </div>

      {/* Table — desktop */}
      {sorted.length === 0 ? (
        <div className="rounded-md border border-dashed border-border/60 px-3 py-10 text-center text-[12px] text-quiet">
          {emptyLabel}
        </div>
      ) : (
        <>
          {/* Desktop table */}
          <div className="hidden w-full overflow-x-auto sm:block">
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr>
                  {columns.map((col) => (
                    <th
                      key={col.key}
                      className={cn(
                        "border-b border-border/60 px-3 py-2.5 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-quiet",
                        col.align === "right" ? "text-right" : col.align === "center" ? "text-center" : "text-left",
                        col.sortable && "cursor-pointer select-none hover:text-foreground transition-colors"
                      )}
                      onClick={col.sortable ? () => toggleSort(col.key) : undefined}
                    >
                      <span className="inline-flex items-center gap-1">
                        {col.label}
                        {col.sortable ? (
                          sortKey === col.key ? (
                            sortDir === "asc" ? (
                              <ArrowUp className="size-3 text-iris-soft" />
                            ) : (
                              <ArrowDown className="size-3 text-iris-soft" />
                            )
                          ) : (
                            <ArrowUpDown className="size-3 opacity-40" />
                          )
                        ) : null}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {paginated.map((row) => (
                  <tr
                    key={keyOf(row)}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                    className={cn(
                      "border-b border-border/60 last:border-0 transition-colors hover:bg-surface-2/40",
                      onRowClick && "cursor-pointer"
                    )}
                  >
                    {columns.map((col) => (
                      <td
                        key={col.key}
                        className={cn(
                          "px-3 py-3 align-middle",
                          col.align === "right" ? "text-right" : col.align === "center" ? "text-center" : ""
                        )}
                      >
                        {col.renderCell(row)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile stacked cards */}
          <div className="space-y-2 sm:hidden">
            {paginated.map((row) => {
              const primary = columns.find((c) => c.primaryOnCard);
              const rest = columns.filter((c) => !c.primaryOnCard && !c.hideOnCard);
              return (
                <div
                  key={keyOf(row)}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  className={cn(
                    "rounded-lg border border-border/60 bg-surface-2/20 p-3.5 space-y-2",
                    onRowClick && "cursor-pointer hover:bg-surface-2/40 transition-colors"
                  )}
                >
                  {primary && (
                    <div className="text-[13.5px] font-medium text-foreground">
                      {primary.renderCell(row)}
                    </div>
                  )}
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
                    {rest.map((col) => (
                      <div key={col.key}>
                        <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-quiet">
                          {col.cardLabel ?? col.label}
                        </div>
                        <div className={cn("mt-0.5 text-[12.5px]", col.align === "right" ? "text-right" : "")}>
                          {col.renderCell(row)}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Pagination */}
          {pageCount > 1 && (
            <div className="flex items-center justify-between gap-3 pt-1">
              <button
                type="button"
                disabled={safePage === 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                className="inline-flex items-center gap-1 rounded-md border border-border/60 bg-surface-2/20 px-3 py-1.5 text-[12px] text-muted transition-colors hover:border-border hover:bg-surface-2/50 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
              >
                <ChevronLeft className="size-3.5" /> Prev
              </button>
              <span className="text-[12px] text-quiet tabular">
                {safePage + 1} / {pageCount}
              </span>
              <button
                type="button"
                disabled={safePage >= pageCount - 1}
                onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
                className="inline-flex items-center gap-1 rounded-md border border-border/60 bg-surface-2/20 px-3 py-1.5 text-[12px] text-muted transition-colors hover:border-border hover:bg-surface-2/50 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
              >
                Next <ChevronRight className="size-3.5" />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// Default comparator: numeric when both values parse as numbers, else lexicographic.
function defaultComparator<T>(a: T, b: T, key: string): number {
  const av = (a as Record<string, unknown>)[key];
  const bv = (b as Record<string, unknown>)[key];
  const an = typeof av === "number" ? av : parseFloat(String(av ?? ""));
  const bn = typeof bv === "number" ? bv : parseFloat(String(bv ?? ""));
  if (!isNaN(an) && !isNaN(bn)) return an - bn;
  return String(av ?? "").localeCompare(String(bv ?? ""));
}
