"use client";

// SubscriptionsTable — the "Subscriptions & renewals" register.
//
// READ-ONLY mirror of the code-maintained cost register (apps/web/app/data/cost-register.ts) — costs are
// edited in code, never in the browser. Columns: Source · Category · Recurring (currently billed? yes/no) ·
// Last paid · Next renewal · Lifetime (real spend, prominent) │ Est. /mo · Est. /yr (derived from the
// recurring flag + price). Click any header to sort (asc → desc → off).

import { useMemo, useState } from "react";
import { CatBadge } from "./cost-sections";
import { type CostLine } from "@/app/data/cost-register";
import { formatUsd } from "@/lib/utils";

function fmtD(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

const money = (v: number) => (Math.round(v) === 0 ? "$0" : formatUsd(Math.round(v)));

function DateCell({ value }: { value: string | null }) {
  if (!value) return <span className="quiet">—</span>;
  return <span className="tab">{fmtD(value)}</span>;
}

type SortKey = "source" | "category" | "recurring" | "lastPaid" | "renews" | "lifetime" | "estMo" | "estYr";
type SortDir = "asc" | "desc";

const sortVal = (r: CostLine, k: SortKey): string | number => {
  switch (k) {
    case "source": return r.source.toLowerCase();
    case "category": return r.category;
    case "recurring": return r.recurring ? 1 : 0;
    case "lastPaid": return r.lastPaid ?? "";
    case "renews": return r.renews ?? "";
    case "lifetime": return r.lifetime;
    case "estMo": return r.estMo;
    case "estYr": return r.estYr;
  }
};

export function SubscriptionsTable({ rows }: { rows: CostLine[] }) {
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir } | null>(null);

  // Click cycles asc → desc → off, so a click can always be undone.
  const clickHeader = (key: SortKey) =>
    setSort((p) => (p?.key !== key ? { key, dir: "asc" } : p.dir === "asc" ? { key, dir: "desc" } : null));

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const arr = [...rows];
    arr.sort((a, b) => {
      const av = sortVal(a, sort.key);
      const bv = sortVal(b, sort.key);
      const cmp = typeof av === "number" && typeof bv === "number" ? av - bv : String(av).localeCompare(String(bv));
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return arr;
  }, [rows, sort]);

  // /yr displays as the rounded /mo × 12 so each row reads "est/mo × 12 = est/yr" exactly.
  const yr = (estMo: number) => Math.round(estMo) * 12;
  const totLife = rows.reduce((s, r) => s + Math.round(r.lifetime), 0);
  const totMo = rows.reduce((s, r) => s + Math.round(r.estMo), 0);
  const totYr = totMo * 12;

  // A separator bar before the estimate block.
  const sep = { borderLeft: "1px solid var(--border)" } as const;
  const arrow = (k: SortKey) => (sort?.key === k ? (sort.dir === "asc" ? " ▲" : " ▼") : "");

  const Th = ({ k, label, align, style }: { k: SortKey; label: string; align?: boolean; style?: React.CSSProperties }) => (
    <th
      className={align ? "r sortable" : "sortable"}
      style={{ cursor: "pointer", userSelect: "none", ...style }}
      onClick={() => clickHeader(k)}
      aria-sort={sort?.key === k ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
    >
      {label}
      <span className="iris" style={{ fontSize: 9 }}>{arrow(k)}</span>
    </th>
  );

  return (
    <div className="tbl-scroll">
      <table className="mini-tbl subs-tbl">
        <thead>
          <tr>
            <Th k="source" label="Source" />
            <Th k="category" label="Category" />
            <Th k="recurring" label="Recurring" />
            <Th k="lastPaid" label="Last paid" align />
            <Th k="renews" label="Next renewal" align />
            <Th k="lifetime" label="Lifetime" align />
            <Th k="estMo" label="Est. / mo" align style={sep} />
            <Th k="estYr" label="Est. / yr" align />
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.source}>
              <td>
                <span style={{ fontWeight: 500, color: "var(--fg)" }}>{r.source}</span>
              </td>
              <td>
                {r.category === "other" ? (
                  <span className="muted" style={{ fontSize: 11 }}>Other</span>
                ) : (
                  <CatBadge category={r.category} />
                )}
              </td>
              <td>
                <span className={`rec-badge ${r.recurring ? "rec-yes" : "rec-no"}`}>{r.recurring ? "yes" : "no"}</span>
              </td>
              <td className="r muted">
                <DateCell value={r.lastPaid} />
              </td>
              <td className="r">
                <DateCell value={r.renews} />
              </td>
              {/* Lifetime — real spend, white & in evidence. */}
              <td className="r tab" style={{ color: "var(--fg)", fontWeight: 600 }}>{money(r.lifetime)}</td>
              {/* Estimates — derived, muted. */}
              <td className="r tab muted" style={sep}>{money(r.estMo)}</td>
              <td className="r tab muted">{money(yr(r.estMo))}</td>
            </tr>
          ))}
          <tr className="sub-row">
            <td style={{ fontWeight: 600, color: "var(--fg)" }}>Total</td>
            <td colSpan={4} className="quiet" style={{ fontSize: 9.5 }}>
              {rows.length} source{rows.length === 1 ? "" : "s"} · maintained in code
            </td>
            <td className="r tab" style={{ color: "var(--fg)", fontWeight: 700 }}>{money(totLife)}</td>
            <td className="r tab muted" style={{ ...sep, fontWeight: 600 }}>{money(totMo)}</td>
            <td className="r tab muted" style={{ fontWeight: 600 }}>{money(totYr)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
