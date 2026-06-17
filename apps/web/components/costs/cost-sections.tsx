// module: Costs page-local sections — Iris Bento port. Page-scoped composition over the bento CSS
// classes (no Tailwind, no shadcn). The Costs surface answers one question — "is the machine's alpha
// worth more than what it costs to run?" — so these sections are framed around opex, run-rate and a
// register of real spend lines, not a wall of synthetic ledger rows.
//
// HONESTY: every figure is real engine/billing data. Live supplier figures are marked "live"; static
// estimates are marked "est." and never dressed up as actuals. There is NO dated cumulative-spend series
// in the CostsResponse contract, so anything that would need one renders an honest empty/em-dash — never
// a fabricated curve or number. Empty / zero states say so plainly.

import type { ReactNode } from "react";
import type { CostByCategory, SpendPoint } from "@cosmu/contracts-ts";
import { EquityChart } from "@/components/charts/equity-chart";
import { cn, formatUsd, formatSigned } from "@/lib/utils";

// ─── Category → bento badge mapping ─────────────────────────────────────────────
// The mockup's four `.cat-badge` tones (infra / trading / data / ai). Supplier and infra categories use
// a slightly different vocabulary (llm/ci) so we fold them onto the same four visual buckets — purely a
// label colour, never a number.
const CAT_LABEL: Record<string, string> = {
  infra: "Infra",
  trading: "Trading",
  data: "Data",
  ai: "AI / LLM",
  llm: "AI / LLM",
  ci: "Infra",
  marketing: "Marketing",
};
const CAT_CLASS: Record<string, string> = {
  infra: "cat-infra",
  trading: "cat-trading",
  data: "cat-data",
  ai: "cat-ai",
  llm: "cat-ai",
  ci: "cat-infra",
  marketing: "cat-data",
};

export function CatBadge({ category }: { category: string }) {
  const key = category.toLowerCase();
  return (
    <span className={cn("cat-badge", CAT_CLASS[key] ?? "cat-infra")}>{CAT_LABEL[key] ?? category}</span>
  );
}

// ─── Stat strip ─────────────────────────────────────────────────────────────────
// The four-cell headline (mockup `statStrip()`). Each cell carries a real number or an honest em-dash.
// `vsEquity` is `opex_vs_alpha` — only shown when the engine actually reports it (else "—").
export type StatCell = {
  label: string;
  value: string;
  sub: string;
  /** Optional tone class for the value (e.g. "up"); omit for default foreground. */
  tone?: string;
  /** When set, the cell becomes a clickable category filter (like the tiles). */
  onClick?: () => void;
  /** Highlight the cell as the active filter. */
  active?: boolean;
};

export function StatStrip({ cells }: { cells: StatCell[] }) {
  return (
    <div className="stat-strip">
      {cells.map((c) => (
        <div
          className={cn("stat-cell", c.onClick && "clk", c.active && "active")}
          key={c.label}
          onClick={c.onClick}
          role={c.onClick ? "button" : undefined}
          aria-pressed={c.onClick ? !!c.active : undefined}
        >
          <div className="stat-l">{c.label}</div>
          <div className={cn("stat-v", c.tone)}>{c.value}</div>
          <div className="stat-s">{c.sub}</div>
        </div>
      ))}
    </div>
  );
}

// ─── Spend chart card ───────────────────────────────────────────────────────────
// The mockup's `costChartCard()` fronts a cumulative-spend curve. `spendSeries` comes from the
// CostsResponse.spend_series field (monthly booked actuals). The chart section is only rendered when
// monthly actuals exist — hiding a blank panel that reads as broken is more honest than an empty
// EquityChart body. The hero stat (total spend) is always shown.
export function SpendChartCard({
  totalToDate,
  spendSeries,
}: {
  totalToDate: number | null;
  spendSeries?: SpendPoint[] | null;
}) {
  // Build the EquityChart input: monotonically increasing cumulative values so the chart reads as a
  // running total (equity-curve style). Each data point is the sum of all months up to that month.
  const chartValues: number[] = [];
  if (spendSeries && spendSeries.length > 0) {
    let running = 0;
    for (const pt of spendSeries) {
      running += pt.amount_usd;
      chartValues.push(running);
    }
  }
  const hasChart = chartValues.length >= 2;

  return (
    <div className="card dh" style={{ padding: "14px 16px", marginBottom: "var(--gap)" }}>
      <div className="hero-top">
        <div>
          <div className="hero-label">Total spend</div>
          <div>
            <span className="hero-val tab">{totalToDate === null ? "—" : formatUsd(totalToDate)}</span>
            <span className="hero-delta tab" style={{ color: "var(--quiet)", fontWeight: 500 }}>
              booked to date
            </span>
          </div>
        </div>
        {hasChart ? (
          <span className="quiet" style={{ fontSize: 10.5, alignSelf: "flex-start", marginTop: 4 }}>
            {spendSeries!.length} months of actuals
          </span>
        ) : null}
      </div>
      {hasChart ? (
        <EquityChart values={chartValues} height={150} />
      ) : (
        <p className="quiet" style={{ fontSize: 11, marginTop: 8 }}>
          Spend history appears here once monthly actuals are booked — the figures above are real totals.
        </p>
      )}
    </div>
  );
}

// ─── Category tiles ─────────────────────────────────────────────────────────────
// The mockup's `.cat-tiles .cat-tile` grid, fed the REAL CostsResponse.by_category. Each tile shows the
// lifetime/total $ for the category + a category badge. Renders nothing when the engine returned no
// categories (never a fabricated split).
// The four canonical buckets — ALWAYS shown (even at $0), folding the engine's category vocab
// (ci→infra, llm→ai) into them. No hover tooltip.
export const TILE_ORDER = ["infra", "trading", "data", "ai"] as const;
type TileBucket = (typeof TILE_ORDER)[number];
const TILE_FOLD: Record<string, TileBucket> = { infra: "infra", ci: "infra", data: "data", trading: "trading", llm: "ai", ai: "ai" };
export const foldTile = (c: string): TileBucket => TILE_FOLD[c.toLowerCase()] ?? "infra";

// Filter key — like foldTile but keeps "other" distinct (it has no tile; it lives in the "Other" box).
// Used to match the active filter against a row's category.
export const catKey = (c: string): string => (c.toLowerCase() === "other" ? "other" : foldTile(c));

export function CategoryTiles({
  categories,
  active,
  onPick,
}: {
  categories: CostByCategory[];
  /** Active category filter; when set the matching tile is highlighted. */
  active?: string | null;
  /** When provided the tiles become clickable filters. */
  onPick?: (cat: string) => void;
}) {
  const totals: Record<TileBucket, number> = { infra: 0, trading: 0, data: 0, ai: 0 };
  for (const c of categories) totals[foldTile(c.category)] += c.amount;
  return (
    <div className="cat-tiles">
      {TILE_ORDER.map((cat) => {
        const isActive = active != null && catKey(active) === cat;
        return (
          <div
            className={cn("cat-tile", isActive && "active")}
            key={cat}
            onClick={onPick ? () => onPick(cat) : undefined}
            role={onPick ? "button" : undefined}
            aria-pressed={onPick ? isActive : undefined}
          >
            <CatBadge category={cat} />
            <div className="stat-v" style={{ marginTop: 8 }}>
              {formatUsd(totals[cat])}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Per-strategy ROI table ─────────────────────────────────────────────────────
// The literal "opex vs alpha" question at the strategy grain, rendered as a `.mini-tbl`. ROI is "—" when
// opex is zero (undefined ratio). Net P&L is sim/forward — never conflated with live money here; it's the
// per-strategy net the engine attributes.
export function RoiTable({
  rows,
}: {
  rows: { version_id: string; name: string; opex: number; net: number }[];
}) {
  return (
    <div className="tbl-scroll">
      <table className="mini-tbl">
        <thead>
          <tr>
            <th>Strategy</th>
            <th className="r">Opex</th>
            <th className="r">Net P&amp;L</th>
            <th className="r">ROI</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const profitable = r.net >= 0;
            const roi = r.opex > 0 ? r.net / r.opex : null;
            return (
              <tr key={r.version_id}>
                <td>
                  <span style={{ fontWeight: 500, color: "var(--fg)" }}>{r.name}</span>
                  <span className="quiet mono" style={{ display: "block", fontSize: 9.5, marginTop: 1 }}>
                    {r.version_id.slice(0, 8)}
                  </span>
                </td>
                <td className="r tab muted">{formatUsd(r.opex, 2)}</td>
                <td className={cn("r tab", profitable ? "up" : "dn")}>{formatSigned(r.net)}</td>
                <td className={cn("r tab", roi === null ? "quiet" : roi >= 1 ? "up" : roi >= 0 ? "gold" : "dn")}>
                  {roi !== null ? `${(roi * 100).toFixed(0)}%` : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Card header with a label + optional aside ──────────────────────────────────
// The mockup's `tline()` — a `.card-hdr .ck-hd` row with the section label and an optional right-aligned
// note (e.g. a count) plus, on the register, the "+ Add cost" control. That control is honest: it writes
// an operator override to localStorage (this browser), clearly labelled "set" — it never claims to reach a
// backend write endpoint the contract doesn't have.
export function CardHead({ label, aside }: { label: string; aside?: ReactNode }) {
  return (
    <div className="card-hdr ck-hd">
      <span className="card-lbl">{label}</span>
      {aside ? <span className="sub" style={{ marginLeft: "auto" }}>{aside}</span> : null}
    </div>
  );
}
