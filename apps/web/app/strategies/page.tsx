import type { ReactNode } from "react";
import { ChartCandlestick, Inbox, Microscope, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { engineConfigured, getLeaderboard, getRealtimeStatus } from "../data";
// getPortfolioSummary is defined in two domain modules, so it is ambiguous through the barrel — import it
// from its canonical module (apps/web/app/data/portfolio.ts) to bind the live MONEY SPLIT into the ribbon.
import { getPortfolioSummary } from "../data/portfolio";
import { RealtimeBadge } from "@/components/strategies/realtime-badge";
import type { LeaderboardRow, PortfolioSummaryResponse } from "@cosmu/contracts-ts";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { StrategiesTable } from "@/components/research/strategies-table";
import { PopulationStrip } from "@/components/strategies/population-strip";
import { StrategyStages } from "@/components/nav/strategy-stages";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";
import { cn, formatPct, formatUsd } from "@/lib/utils";

// Strategies (the screener, docs/PRODUCT.md Epic B) answers ONE question: which Versions deserve my
// attention/capital, on what edge? Every Version runs on its own standalone $100k track, ranked by
// risk-adjusted % (deflated OOS Sharpe). The page leads with the population SHAPE (counts by stage),
// then the v18 sortable/column-pickable screener slices the cohort by HOW it makes money: signal-family
// (derived from referenced features) + asset class · venue · timeframe · status · origin · edge-type.
// Rows link to per-Version detail. No pooled wallet, no demo rows.
export default async function StrategiesPage() {
  const [{ leaderboard, connected }, { realtime }, { summary }] = await Promise.all([
    getLeaderboard(),
    getRealtimeStatus(),
    getPortfolioSummary()
  ]);
  const rows = leaderboard.rows as LeaderboardRow[];

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-7 lg:px-7">
      <SectionHeader
        eyebrow="backtest · strategies"
        title="Every Version, ranked & faceted"
        aside={
          <span className="flex items-center gap-2">
            <RealtimeBadge realtime={realtime} />
            <Badge variant="iris">
              <ChartCandlestick className="size-3" /> ranked by risk-adjusted %
            </Badge>
          </span>
        }
      />

      <StrategyStages />

      {!connected ? (
        <NotConnected
          configured={engineConfigured}
          what="Every Version is judged in net-of-fee % on its own track — no pooled wallet. The faceted, ranked screener appears here once the engine is connected — no demo rows."
        />
      ) : rows.length === 0 ? (
        <>
          <BornNote />
          <Card>
            <CardContent>
              <EmptyState
                title="No Versions yet — the Lab hasn't produced any."
                hint="Once the Lab authors a batch (or you drop an idea in the inbox) and Versions reach Paper, they show up here grouped by stage."
              />
            </CardContent>
          </Card>
        </>
      ) : (
        <>
          {/* Lead with the answer: the population shape, then the live MONEY SPLIT ribbon, then the screener. */}
          <PopulationStrip rows={rows} />
          <SummaryRibbon summary={summary} rows={rows} />
          <Card>
            <CardContent className="pt-5">
              <StrategiesTable rows={rows} />
            </CardContent>
          </Card>
          <BornNote />
        </>
      )}
    </div>
  );
}

// The v18 summary ribbon — a calm, dense strip that surfaces the LIVE money split (real capital, real P&L)
// the population counts above do NOT carry. HONEST by construction: when no Version is live (has_live ===
// false, the engine default) it says so plainly; null money fields render an explicit "—", never 0. The
// derived live % is only shown when BOTH the equity and the net P&L are real numbers — never fabricated.
function SummaryRibbon({ summary, rows }: { summary: PortfolioSummaryResponse; rows: LeaderboardRow[] }) {
  const liveEquity = numOrNull(summary.live_equity);
  const livePnl = numOrNull(summary.live_pnl_net);
  // Reconstruct the cost basis (equity − P&L) to express the live P&L as a percent, only when both are real.
  const basis = liveEquity !== null && livePnl !== null ? liveEquity - livePnl : null;
  const livePct = basis && basis > 0 && livePnl !== null ? (livePnl / basis) * 100 : null;

  // Honest paper read: the best (highest) net-of-fee % across the paper cohort, if any paper Version exists.
  const paperRows = rows.filter((r) => isPaper(r.status));
  const bestPaper = paperRows.reduce<number | null>((best, r) => {
    const v = numOrNull(r.paper_return_pct);
    if (v === null) return best;
    return best === null || v > best ? v : best;
  }, null);

  return (
    <div className="card-grad flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg border border-border/70 px-5 py-3 shadow-card">
      {summary.has_live && liveEquity !== null ? (
        <>
          <RibbonItem label="Live" labelClass="text-gold">
            <span className="tabular text-foreground">{formatUsd(liveEquity)}</span>
          </RibbonItem>
          <RibbonItem label="P&L">
            {livePnl === null ? (
              <span className="text-quiet">—</span>
            ) : (
              <span className={cn("tabular font-semibold", livePnl > 0 ? "text-up" : livePnl < 0 ? "text-down" : "text-muted")}>
                {signedUsd(livePnl)}
                {livePct !== null ? <span className="ml-1 font-normal">({formatPct(livePct, 0)})</span> : null}
              </span>
            )}
          </RibbonItem>
        </>
      ) : (
        <RibbonItem label="Live">
          <span className="text-[12px] text-quiet">No Version live — sim only</span>
        </RibbonItem>
      )}

      <span className="hidden h-3.5 w-px bg-border sm:inline-block" aria-hidden />

      <RibbonItem label="Best paper">
        {bestPaper === null ? (
          <span className="text-quiet">—</span>
        ) : (
          <span className={cn("tabular", bestPaper >= 0 ? "text-up" : "text-down")}>{formatPct(bestPaper, 2)}</span>
        )}
      </RibbonItem>

      <div className="ml-auto flex items-center gap-5">
        <RibbonItem label="Live">
          <span className="tabular text-foreground">{summary.positions_count_live}</span>
        </RibbonItem>
        <RibbonItem label="Paper">
          <span className="tabular text-foreground">{paperRows.length}</span>
        </RibbonItem>
      </div>
    </div>
  );
}

function RibbonItem({ label, labelClass, children }: { label: string; labelClass?: string; children: ReactNode }) {
  return (
    <span className="flex items-center gap-1.5 whitespace-nowrap">
      <span className={cn("text-[10px] font-semibold uppercase tracking-[0.07em] text-quiet", labelClass)}>{label}</span>
      <span className="text-[12px]">{children}</span>
    </span>
  );
}

function numOrNull(v: number | null | undefined): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function signedUsd(v: number): string {
  const sign = v > 0 ? "+" : v < 0 ? "-" : "";
  return `${sign}${formatUsd(Math.abs(v))}`;
}

function isPaper(status: string | null | undefined): boolean {
  const s = (status ?? "").toLowerCase();
  return s === "paper" || s === "forward_test" || s === "forward";
}

// Two authoring paths, one Gate — the model in one read, kept calm and secondary (it sits under the
// table once a cohort exists, and above the empty state when one doesn't). No decorative icon banner.
function BornNote() {
  return (
    <Card>
      <CardContent className="py-4">
        <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-center">
          <NoteItem icon={<Microscope className="size-3.5" />} title="The machine authors them">
            autonomously in the{" "}
            <Link href="/lab" className="text-iris-soft hover:underline">
              Lab
            </Link>{" "}
            — seeds, mutations and wildcards, around the clock.
          </NoteItem>
          <NoteItem icon={<Inbox className="size-3.5" />} title="You drop ideas">
            a thesis or Pine script, into the inbox via Claude Code.
          </NoteItem>
          <p className="flex items-center gap-1.5 text-[11.5px] text-quiet sm:justify-end">
            <ShieldCheck className="size-3.5 shrink-0 text-up" />
            <span>
              Both flow through the <span className="font-medium text-foreground">same Gate</span>.
            </span>
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

function NoteItem({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <div className="flex items-start gap-2 text-[12px] leading-relaxed text-muted">
      <span className="mt-0.5 shrink-0 text-quiet">{icon}</span>
      <span>
        <span className="font-medium text-foreground">{title}</span> {children}
      </span>
    </div>
  );
}
