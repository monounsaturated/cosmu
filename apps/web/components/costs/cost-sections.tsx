// module: Costs page-local sections. Page-scoped composition over the shared design-system primitives
// (Card / Badge / Table / viz). The Costs surface answers one question — "is the machine's alpha worth
// more than what it costs to run?" — so these sections are framed around opex-vs-alpha, not a wall of
// spend rows.
//
// HONESTY: every figure is real engine/billing data. Live supplier figures are marked "live"; static
// estimates are marked "est." and never dressed up as actuals. Empty / zero states say so plainly.

import type { ReactNode } from "react";
import { Wifi, WifiOff } from "lucide-react";
import type { CostByCategory, VendorActual } from "@cosmu/contracts-ts";
import type { SupplierRow } from "@/app/data/supplier-costs";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { GaugeBar } from "@/components/ui/viz";
import { cn, formatUsd, formatSigned, timeAgo } from "@/lib/utils";

// ─── Section heading (page-local) ──────────────────────────────────────────────
// A quiet sub-section header: a label, an optional one-line meaning, and an aside (e.g. a total).
// Smaller than the shared SectionHeader — used to separate the stacked ledger sections.
export function CostSection({
  title,
  meaning,
  aside,
  children,
}: {
  title: string;
  meaning?: string;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="flex items-baseline gap-2.5">
          <h2 className="text-[13px] font-semibold tracking-tight text-foreground">{title}</h2>
          {meaning ? <span className="text-[11.5px] text-quiet">{meaning}</span> : null}
        </div>
        {aside ? <div className="shrink-0">{aside}</div> : null}
      </div>
      {children}
    </section>
  );
}

// ─── Spend-by-category breakdown ───────────────────────────────────────────────
// A single proportional bar + legend, drawn from the REAL CostsResponse.by_category. Proportional
// widths read faster than a table; the $ figures stay the source of truth. Renders nothing when the
// engine returned no categories — never a fabricated split.
const CAT_TONES = ["bg-iris", "bg-info/80", "bg-up/80", "bg-warn/80", "bg-iris-soft", "bg-down/70"];

export function CategoryBreakdown({ categories }: { categories: CostByCategory[] }) {
  const cats = [...categories].filter((c) => c.amount > 0).sort((a, b) => b.amount - a.amount);
  if (cats.length === 0) return null;
  const total = cats.reduce((s, c) => s + c.amount, 0) || 1;
  return (
    <Card>
      <CardContent className="space-y-3 py-4">
        <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-surface-2">
          {cats.map((c, i) => (
            <div
              key={c.category}
              className={cn("h-full", CAT_TONES[i % CAT_TONES.length])}
              style={{ width: `${(c.amount / total) * 100}%` }}
              title={`${c.category}: ${formatUsd(c.amount)}`}
            />
          ))}
        </div>
        <ul className="space-y-1.5">
          {cats.map((c, i) => (
            <li key={c.category} className="flex items-center gap-2.5 text-[12.5px]">
              <span className={cn("size-2.5 shrink-0 rounded-[3px]", CAT_TONES[i % CAT_TONES.length])} aria-hidden />
              <span className="flex-1 capitalize text-muted">{c.category}</span>
              <span className="tabular text-quiet">{((c.amount / total) * 100).toFixed(0)}%</span>
              <span className="w-16 text-right font-medium tabular text-foreground">{formatUsd(c.amount)}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

// ─── Vendor actuals (actual vs budget) ─────────────────────────────────────────
// The engine's REAL per-vendor billing actuals against their budget for the period — previously
// computed by the engine but never surfaced. A gauge per vendor reads "how close to the cap" at a
// glance; over-budget rows tint red. Only rendered when the engine returned actuals.
export function VendorActuals({ vendors }: { vendors: VendorActual[] }) {
  const rows = [...vendors].sort((a, b) => b.amount - a.amount);
  if (rows.length === 0) return null;
  return (
    <Card>
      <CardContent className="space-y-3 py-4">
        <ul className="space-y-3">
          {rows.map((v) => {
            const over = v.budget > 0 && v.amount > v.budget;
            const frac = v.budget > 0 ? v.amount / v.budget : 0;
            return (
              <li key={`${v.vendor}-${v.period}`} className="space-y-1.5">
                <div className="flex items-baseline justify-between gap-3 text-[12.5px]">
                  <div className="flex items-baseline gap-2">
                    <span className="font-medium text-foreground">{v.vendor}</span>
                    <span className="text-[11px] capitalize text-quiet">{v.category}</span>
                  </div>
                  <div className="flex items-baseline gap-2 tabular">
                    <span className={cn("font-semibold", over ? "text-down" : "text-foreground")}>
                      {formatUsd(v.amount, 2)}
                    </span>
                    <span className="text-[11px] text-quiet">
                      / {v.budget > 0 ? formatUsd(v.budget, 2) : "no budget"}
                    </span>
                  </div>
                </div>
                <GaugeBar
                  value={v.amount}
                  max={v.budget > 0 ? v.budget : v.amount}
                  marker={v.budget > 0 ? 1 : undefined}
                  tone={over ? "down" : frac > 0.85 ? "warn" : "up"}
                />
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}

// ─── Supplier source chip ──────────────────────────────────────────────────────
// "live" = fetched from the real billing API this render; "est." = a clearly-labelled static estimate.
function SourceChip({ source }: { source: SupplierRow["source"] }) {
  return source === "live" ? (
    <span className="inline-flex items-center gap-1 text-[11px] text-up">
      <Wifi className="size-3" /> live
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-[11px] text-muted">
      <WifiOff className="size-3" /> est.
    </span>
  );
}

// ─── Supplier preview table ────────────────────────────────────────────────────
// The top suppliers by cost. Compact, calm, with a total row. The full sortable ledger lives at
// /costs/ledger — this is the glanceable summary.
export function SupplierPreviewTable({ rows, total }: { rows: SupplierRow[]; total: number }) {
  return (
    <Card>
      <CardContent className="p-0">
        <Table>
          <THead>
            <TR>
              <TH className="pl-4 sticky-col">Supplier</TH>
              <TH>Role</TH>
              <TH className="text-right">$/mo</TH>
              <TH className="pr-4">Source</TH>
            </TR>
          </THead>
          <TBody>
            {rows.map((row) => {
              const isFree = row.amount_usd === 0;
              return (
                <TR key={row.name}>
                  <TD className="pl-4 font-medium text-foreground sticky-col">
                    <div className="flex items-center gap-2">
                      {row.name}
                      <Badge
                        variant={row.category === "llm" ? "iris" : row.category === "data" ? "info" : "muted"}
                        className="text-[10px]"
                      >
                        {row.category}
                      </Badge>
                    </div>
                  </TD>
                  <TD className="max-w-[280px] truncate text-quiet">{row.role}</TD>
                  <TD className="text-right tabular text-foreground">
                    {isFree ? <span className="text-[11px] text-up">free / $0</span> : formatUsd(row.amount_usd)}
                  </TD>
                  <TD className="pr-4">
                    <SourceChip source={row.source} />
                  </TD>
                </TR>
              );
            })}
            <TR className="bg-surface-2/30 font-semibold hover:bg-surface-2/30">
              <TD className="pl-4 text-foreground sticky-col">Total</TD>
              <TD className="text-[11px] text-quiet">live + estimates</TD>
              <TD className="text-right tabular text-foreground">{formatUsd(total)}</TD>
              <TD className="pr-4" />
            </TR>
          </TBody>
        </Table>
      </CardContent>
    </Card>
  );
}

// ─── Per-strategy ROI card ─────────────────────────────────────────────────────
// One card per strategy that has attributed opex: opex spent vs net P&L, with the ROI multiple. This
// is the literal "opex vs alpha" question at the strategy grain. Honest "—" when ROI is undefined.
export function RoiCard({
  name,
  versionId,
  opex,
  net,
}: {
  name: string;
  versionId: string;
  opex: number;
  net: number;
}) {
  const profitable = net >= 0;
  const roi = opex > 0 ? net / opex : null;
  return (
    <Card>
      <CardContent className="space-y-3 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-[13.5px] font-medium text-foreground">{name}</div>
            <div className="truncate font-mono text-[10.5px] text-quiet">{versionId.slice(0, 8)}</div>
          </div>
          <Badge variant={profitable ? "up" : "down"}>{profitable ? "profitable" : "underwater"}</Badge>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <RoiCell label="Opex" value={formatUsd(opex, 2)} tone="text-muted" />
          <RoiCell label="Net P&L" value={formatSigned(net)} tone={profitable ? "text-up" : "text-down"} />
          <RoiCell
            label="ROI"
            value={roi !== null ? `${(roi * 100).toFixed(0)}%` : "—"}
            tone={roi === null ? "text-quiet" : roi >= 1 ? "text-up" : roi >= 0 ? "text-warn" : "text-down"}
          />
        </div>
      </CardContent>
    </Card>
  );
}

function RoiCell({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="rounded-md border border-border/50 bg-surface-2/30 px-2 py-2 text-center">
      <div className={cn("text-[14px] font-semibold tabular", tone)}>{value}</div>
      <div className="mt-0.5 text-[10px] uppercase tracking-wide text-quiet">{label}</div>
    </div>
  );
}

// ─── LLM calls summary ─────────────────────────────────────────────────────────
// Total calls + total cost, with a "by task" mini bar chart. Free-tier ($0) is shown plainly, not
// hidden. Empty state when no calls recorded yet.
export function LlmCallsSummary({
  callCount,
  totalCost,
  byTask,
  empty,
}: {
  callCount: number;
  totalCost: number;
  byTask: Record<string, unknown>;
  empty: ReactNode;
}) {
  if (callCount === 0) return <>{empty}</>;
  const tasks = Object.entries(byTask)
    .map(([task, count]) => ({ task, count: Number(count) }))
    .sort((a, b) => b.count - a.count);
  const top = Math.max(1, ...tasks.map((t) => t.count));
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-[12.5px]">
        <div>
          <span className="text-quiet">Total calls</span>{" "}
          <span className="font-semibold tabular text-foreground">{callCount.toLocaleString()}</span>
        </div>
        <div>
          <span className="text-quiet">Total cost</span>{" "}
          <span className="font-semibold tabular text-up">
            {totalCost === 0 ? "$0 — free tier" : formatUsd(totalCost, 4)}
          </span>
        </div>
      </div>
      {tasks.length > 0 ? (
        <div className="space-y-1.5 border-t border-border/40 pt-3">
          <div className="text-[10.5px] font-semibold uppercase tracking-[0.1em] text-quiet">Calls by task</div>
          {tasks.map((t) => (
            <div key={t.task} className="flex items-center gap-2.5 text-[12px]">
              <span className="w-28 shrink-0 truncate capitalize text-muted">{t.task}</span>
              <div className="h-2.5 flex-1 overflow-hidden rounded bg-surface-2">
                <div className="h-full rounded bg-iris/75" style={{ width: `${Math.max((t.count / top) * 100, 4)}%` }} />
              </div>
              <span className="w-8 shrink-0 text-right font-medium tabular text-foreground">{t.count}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// ─── Refreshed-at note ─────────────────────────────────────────────────────────
export function RefreshedAt({ at }: { at: string }) {
  const ago = timeAgo(at);
  if (!ago) return null;
  return <span className="text-[11px] text-quiet">refreshed {ago} · 30 min cache</span>;
}
