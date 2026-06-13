import Link from "next/link";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { Card, CardContent } from "@/components/ui/card";
import { Tooltip } from "@/components/ui/tooltip";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { EmptyState } from "@/components/ui/honest-state";
import { cn, formatPct, formatUsd } from "@/lib/utils";

// The Paper track ledger (v18 "Recent trades" card, bound honestly). The Paper surface fetches the
// leaderboard + the aggregate overview curve — neither carries a per-FILL blotter (Execution[] lives on
// the strategy-detail endpoint, not here). So instead of fabricating fills, this is the REAL per-track
// money roll-up: each funded track's deployed capital, current marked value, and net-of-fee P&L in $ + %.
// It is the per-track read the mockup's trades card stands in for, sourced only from real fields.
//
// HONESTY: a track that has not accrued a dollar mark (value_usd / pnl_usd === null) renders "—" in those
// cells — never a 0. If NO track carries any dollar mark, the whole table collapses to an honest empty
// state. The footnote points the operator to the per-fill blotter on each strategy sheet.
function num(v: number | null | undefined): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

export function TrackLedger({ rows }: { rows: LeaderboardRow[] }) {
  // Only render rows in a stable, decision-relevant order: biggest absolute marked P&L first, then by name.
  const ordered = [...rows].sort((a, b) => {
    const pa = num(a.pnl_usd);
    const pb = num(b.pnl_usd);
    if (pa !== null && pb !== null && pa !== pb) return Math.abs(pb) - Math.abs(pa);
    if (pa !== null && pb === null) return -1;
    if (pa === null && pb !== null) return 1;
    return a.name.localeCompare(b.name);
  });

  const anyMarked = rows.some((r) => num(r.value_usd) !== null || num(r.pnl_usd) !== null);

  return (
    <Card>
      <CardContent className="pt-5">
        <div className="mb-3 flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-quiet">Per-track P&amp;L</span>
          <span className="inline-flex items-center gap-1 text-[11px] text-quiet">
            net of fees · since funding
            <Tooltip content="The real money roll-up for each funded paper track: capital deployed, current marked value, and net-of-fee P&L since the Gate funded it. The per-fill trade blotter lives on each strategy's detail sheet — open a track to see its fills." />
          </span>
        </div>

        {!anyMarked ? (
          <EmptyState
            title="No marked track value yet."
            hint="A track shows its deployed capital and net-of-fee P&L here once it accrues marked history. Nothing is fabricated until then — open a track to see its per-fill blotter."
          />
        ) : (
          <Table>
            <THead>
              <TR>
                <TH className="sticky-col whitespace-nowrap">Strategy</TH>
                <TH className="whitespace-nowrap">Class · venue · tf</TH>
                <TH className="whitespace-nowrap text-right">Invested</TH>
                <TH className="whitespace-nowrap text-right">Value</TH>
                <TH className="whitespace-nowrap text-right">P&amp;L</TH>
              </TR>
            </THead>
            <TBody>
              {ordered.map((row) => {
                const value = num(row.value_usd);
                const pnl = num(row.pnl_usd);
                const pct = num(row.pnl_pct);
                // Invested = current value − net P&L, only when both real marks exist.
                const invested = value !== null && pnl !== null ? value - pnl : null;
                const pnlPos = pnl !== null && pnl >= 0;
                return (
                  <TR key={row.version_id} className="transition-colors hover:bg-surface-2/50">
                    <TD className="sticky-col whitespace-nowrap">
                      <Link
                        href={`/strategy/${row.version_id}`}
                        className="font-medium text-foreground hover:text-iris-soft"
                      >
                        {row.name}
                      </Link>
                    </TD>
                    <TD className="whitespace-nowrap text-[11.5px] text-muted">
                      {row.asset_class} · {row.venue} · {row.timeframe}
                    </TD>
                    <TD className="whitespace-nowrap text-right tabular text-muted">
                      {invested === null ? "—" : formatUsd(invested)}
                    </TD>
                    <TD className="whitespace-nowrap text-right tabular text-foreground">
                      {value === null ? "—" : formatUsd(value)}
                    </TD>
                    <TD className="whitespace-nowrap text-right">
                      <div className={cn("tabular", pnl === null ? "text-quiet" : pnlPos ? "text-up" : "text-down")}>
                        {pnl === null ? "—" : formatUsd(pnl)}
                      </div>
                      <div className={cn("tabular text-[11px]", pct === null ? "text-quiet" : pct >= 0 ? "text-up" : "text-down")}>
                        {pct === null ? "—" : formatPct(pct)}
                      </div>
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
