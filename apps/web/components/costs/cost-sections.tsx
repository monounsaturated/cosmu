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
import type { CostByCategory, InfraLine, VendorActual } from "@cosmu/contracts-ts";
import type { SupplierRow } from "@/app/data/supplier-costs";
import { EquityChart } from "@/components/charts/equity-chart";
import { EmptyState } from "@/components/ui/honest-state";
import { cn, formatUsd, formatSigned, timeAgo } from "@/lib/utils";

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
};
const CAT_CLASS: Record<string, string> = {
  infra: "cat-infra",
  trading: "cat-trading",
  data: "cat-data",
  ai: "cat-ai",
  llm: "cat-ai",
  ci: "cat-infra",
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
};

export function StatStrip({ cells }: { cells: StatCell[] }) {
  return (
    <div className="stat-strip">
      {cells.map((c) => (
        <div className="stat-cell" key={c.label}>
          <div className="stat-l">{c.label}</div>
          <div className={cn("stat-v", c.tone)}>{c.value}</div>
          <div className="stat-s">{c.sub}</div>
        </div>
      ))}
    </div>
  );
}

// ─── Spend chart card ───────────────────────────────────────────────────────────
// The mockup's `costChartCard()` fronts a cumulative-spend curve. The CostsResponse contract carries NO
// dated spend ledger, so we render the EquityChart's honest empty state (values=[]) — never a fabricated
// curve. `totalToDate` is the one real figure (booked spend), surfaced in the hero without inventing a
// trend.
export function SpendChartCard({ totalToDate }: { totalToDate: number | null }) {
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
      </div>
      <EquityChart
        values={[]}
        height={150}
        emptyHint="No dated spend curve yet — the engine reports point-in-time totals, not a daily ledger. Every figure below is a real total; nothing here is a fabricated trend."
      />
    </div>
  );
}

// ─── Category tiles ─────────────────────────────────────────────────────────────
// The mockup's `.cat-tiles .cat-tile` grid, fed the REAL CostsResponse.by_category. Each tile shows the
// lifetime/total $ for the category + a category badge. Renders nothing when the engine returned no
// categories (never a fabricated split).
export function CategoryTiles({ categories }: { categories: CostByCategory[] }) {
  const cats = [...categories].filter((c) => c.amount > 0).sort((a, b) => b.amount - a.amount);
  if (cats.length === 0) return null;
  return (
    <div className="cat-tiles">
      {cats.map((c) => (
        <div className="cat-tile" key={c.category} data-tip={`${c.category}: ${formatUsd(c.amount, 2)}`}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <CatBadge category={c.category} />
          </div>
          <div className="stat-v" style={{ marginTop: 8 }}>
            {formatUsd(c.amount)}
          </div>
          <div className="stat-s" style={{ textTransform: "capitalize" }}>
            total · {c.category}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Register row model ─────────────────────────────────────────────────────────
// One unified "cost source" row, assembled from the three REAL inputs the contract gives us:
//   - supplier rows  (live/estimated monthly spend, fetched directly from billing APIs)
//   - infra lines    (engine-reported plan-tier estimates, with a range + note)
//   - vendor actuals (engine-reported real spend vs budget this period)
// Vendor actuals, when present, override the supplier/infra amount for the same vendor (they are the
// realest figure we have). Headroom is "—" unless a real budget cap exists.
export type RegisterRow = {
  vendor: string;
  category: string;
  /** Current spend figure ($/period) or null when only a range is known. */
  amount: number | null;
  /** Honest range string when no point estimate (e.g. "$5–$20"), else null. */
  range: string | null;
  /** Budget cap for this vendor, or null when uncapped. */
  budget: number | null;
  /** Period label (e.g. "monthly", "May 2026"), or null. */
  period: string | null;
  /** "live" billing fetch, "est" estimate, or "actual" engine-reported actual. */
  source: "live" | "est" | "actual";
  /** Optional one-line note (infra lines carry these). */
  note?: string | null;
};

export function buildRegister(
  suppliers: SupplierRow[],
  infraLines: InfraLine[],
  vendorActuals: VendorActual[],
): RegisterRow[] {
  const byVendor = new Map<string, RegisterRow>();
  const keyOf = (v: string) => v.trim().toLowerCase();

  // 1) supplier billing rows — the live/estimated base layer.
  for (const s of suppliers) {
    byVendor.set(keyOf(s.name), {
      vendor: s.name,
      category: s.category,
      amount: s.amount_usd,
      range: null,
      budget: null,
      period: "monthly",
      source: s.source,
      note: s.role,
    });
  }

  // 2) engine infra lines — fill vendors the supplier layer doesn't know, and attach honest ranges.
  for (const l of infraLines) {
    const k = keyOf(l.vendor);
    const hasRange = l.amount_min !== l.amount_max && (l.amount_min > 0 || l.amount_max > 0);
    const range = hasRange ? `${formatUsd(l.amount_min)}–${formatUsd(l.amount_max)}` : null;
    const existing = byVendor.get(k);
    if (existing) {
      // Keep the supplier figure but enrich with the range/note when the supplier had none.
      if (!existing.note && l.note) existing.note = l.note;
      if (existing.range === null && range) existing.range = range;
    } else {
      byVendor.set(k, {
        vendor: l.vendor,
        category: l.category,
        amount: range ? null : l.amount,
        range,
        budget: null,
        period: "est. / mo",
        source: "est",
        note: l.note || null,
      });
    }
  }

  // 3) vendor actuals — the realest figure; override the amount + attach the real budget/period.
  for (const v of vendorActuals) {
    const k = keyOf(v.vendor);
    const existing = byVendor.get(k);
    if (existing) {
      existing.amount = v.amount;
      existing.range = null;
      existing.budget = v.budget > 0 ? v.budget : null;
      existing.period = v.period || existing.period;
      existing.source = "actual";
    } else {
      byVendor.set(k, {
        vendor: v.vendor,
        category: v.category,
        amount: v.amount,
        range: null,
        budget: v.budget > 0 ? v.budget : null,
        period: v.period || null,
        source: "actual",
      });
    }
  }

  const ORDER: Record<string, number> = { infra: 0, ci: 0, data: 1, trading: 1, llm: 2, ai: 2 };
  return [...byVendor.values()].sort((a, b) => {
    const oa = ORDER[a.category.toLowerCase()] ?? 9;
    const ob = ORDER[b.category.toLowerCase()] ?? 9;
    if (oa !== ob) return oa - ob;
    return (b.amount ?? 0) - (a.amount ?? 0);
  });
}

// ─── Source chip ────────────────────────────────────────────────────────────────
// "live" = real billing API this render · "actual" = engine-reported real spend · "est." = estimate.
function SourceChip({ source }: { source: RegisterRow["source"] }) {
  if (source === "live") return <span className="up" style={{ fontSize: 10.5 }}>live</span>;
  if (source === "actual") return <span className="iris" style={{ fontSize: 10.5 }}>actual</span>;
  return <span className="quiet" style={{ fontSize: 10.5 }}>est.</span>;
}

// ─── Register table ─────────────────────────────────────────────────────────────
// The mockup's `registerTbl()` rendered as a real `.mini-tbl`: one row per cost source with vendor,
// category, amount/range, budget/headroom and period. Headroom is "—" when uncapped (no budget). A total
// row sums the known point amounts (rows that only carry a range are excluded from the sum, since adding
// a midpoint would fabricate precision).
export function RegisterTable({ rows }: { rows: RegisterRow[] }) {
  const totalKnown = rows.reduce((s, r) => s + (r.amount ?? 0), 0);
  return (
    <div className="tbl-scroll">
      <table className="mini-tbl">
        <thead>
          <tr>
            <th>Source</th>
            <th>Category</th>
            <th className="r">Amount</th>
            <th className="r">Budget</th>
            <th className="r">Headroom</th>
            <th className="r">Period</th>
            <th>Origin</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const headroom = r.budget !== null && r.amount !== null ? r.budget - r.amount : null;
            const over = headroom !== null && headroom < 0;
            const isFree = r.amount === 0;
            return (
              <tr key={r.vendor}>
                <td>
                  <span style={{ fontWeight: 500, color: "var(--fg)" }}>{r.vendor}</span>
                  {r.note ? (
                    <span className="quiet" style={{ display: "block", fontSize: 9.5, marginTop: 1, maxWidth: 260, whiteSpace: "normal", lineHeight: 1.35 }}>
                      {r.note}
                    </span>
                  ) : null}
                </td>
                <td>
                  <CatBadge category={r.category} />
                </td>
                <td className="r tab">
                  {r.amount !== null ? (
                    isFree ? <span className="up" style={{ fontSize: 10.5 }}>free / $0</span> : formatUsd(r.amount, 2)
                  ) : r.range ? (
                    <span className="muted">{r.range}</span>
                  ) : (
                    <span className="quiet">—</span>
                  )}
                </td>
                <td className="r tab muted">{r.budget !== null ? formatUsd(r.budget, 2) : <span className="quiet">—</span>}</td>
                <td className="r tab">
                  {headroom !== null ? (
                    <span className={over ? "dn" : "up"}>{formatSigned(headroom)}</span>
                  ) : (
                    <span className="quiet">—</span>
                  )}
                </td>
                <td className="r muted" style={{ whiteSpace: "nowrap" }}>{r.period ?? <span className="quiet">—</span>}</td>
                <td>
                  <SourceChip source={r.source} />
                </td>
              </tr>
            );
          })}
          <tr>
            <td style={{ fontWeight: 600, color: "var(--fg)" }}>Total</td>
            <td className="quiet" style={{ fontSize: 9.5 }}>known point figures</td>
            <td className="r tab" style={{ fontWeight: 600 }}>{formatUsd(totalKnown, 2)}</td>
            <td className="r" />
            <td className="r" />
            <td className="r" />
            <td />
          </tr>
        </tbody>
      </table>
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

// ─── LLM calls summary ──────────────────────────────────────────────────────────
// Total calls + total cost, with a "by task" mini bar list. Free-tier ($0) is shown plainly, not hidden.
// Honest empty when no calls recorded yet.
export function LlmCallsSummary({
  callCount,
  totalCost,
  byTask,
}: {
  callCount: number;
  totalCost: number;
  byTask: Record<string, unknown>;
}) {
  if (callCount === 0) {
    return (
      <EmptyState
        title="No LLM calls recorded yet."
        hint="Every call through the LLM gateway is recorded here once the engine has run at least one autonomous tick."
      />
    );
  }
  const tasks = Object.entries(byTask)
    .map(([task, count]) => ({ task, count: Number(count) }))
    .sort((a, b) => b.count - a.count);
  const top = Math.max(1, ...tasks.map((t) => t.count));
  return (
    <div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "8px 24px", fontSize: 12.5, marginBottom: tasks.length ? 12 : 0 }}>
        <div>
          <span className="quiet">Total calls</span>{" "}
          <span className="tab" style={{ fontWeight: 600, color: "var(--fg)" }}>{callCount.toLocaleString()}</span>
        </div>
        <div>
          <span className="quiet">Total cost</span>{" "}
          <span className="tab up" style={{ fontWeight: 600 }}>{totalCost === 0 ? "$0 — free tier" : formatUsd(totalCost, 4)}</span>
        </div>
      </div>
      {tasks.length > 0 ? (
        <div style={{ borderTop: "1px solid var(--hairline)", paddingTop: 11 }}>
          <div className="card-lbl" style={{ marginBottom: 7 }}>Calls by task</div>
          {tasks.map((t) => (
            <div key={t.task} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12, marginBottom: 6 }}>
              <span className="muted" style={{ width: 120, flexShrink: 0, textTransform: "capitalize", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {t.task}
              </span>
              <div style={{ flex: 1, height: 9, borderRadius: 5, background: "var(--surf3)", overflow: "hidden" }}>
                <div style={{ height: "100%", borderRadius: 5, background: "var(--iris)", width: `${Math.max((t.count / top) * 100, 4)}%` }} />
              </div>
              <span className="tab" style={{ width: 32, flexShrink: 0, textAlign: "right", fontWeight: 500, color: "var(--fg)" }}>{t.count}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// ─── Card header with a label + optional aside ──────────────────────────────────
// The mockup's `tline()` — a `.card-hdr .ck-hd` row with the section label and an optional right-aligned
// note (e.g. a count or "real dates"). No "+ Add cost" button: the CostsResponse contract has no write
// endpoint, so we never offer a control that cannot do anything.
export function CardHead({ label, aside }: { label: string; aside?: ReactNode }) {
  return (
    <div className="card-hdr ck-hd">
      <span className="card-lbl">{label}</span>
      {aside ? <span className="sub" style={{ marginLeft: "auto" }}>{aside}</span> : null}
    </div>
  );
}

// ─── Refreshed-at note ──────────────────────────────────────────────────────────
export function RefreshedAt({ at }: { at: string }) {
  const ago = timeAgo(at);
  if (!ago) return null;
  return <span className="quiet" style={{ fontSize: 11 }}>refreshed {ago} · 30 min cache</span>;
}
