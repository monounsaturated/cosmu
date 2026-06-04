import { ArrowRight, LineChart, Microscope, Radio, ShieldCheck, TrendingDown, TrendingUp } from "lucide-react";
import type { ReactNode } from "react";
import Link from "next/link";
import { engineConfigured, getLeaderboard } from "../data";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Stat } from "@/components/ui/stat";
import { SectionHeader } from "@/components/ui/section";
import { StrategyStages } from "@/components/nav/strategy-stages";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";
import { formatPct, formatSigned } from "@/lib/utils";

// Forward-test answers ONE question: which survivors are PROVING themselves on real prices, each on
// its OWN track — no pooled wallet. A strategy must show positive net-of-fee P&L here before you
// launch it Live. This is the per-strategy reconciliation: Lab (born) → Strategies (screened) →
// Forward-test (proven, per-strategy) → Live (you launch the winners). No "Paper", no shared Wallet.
export default async function ForwardTestPage() {
  const { leaderboard, connected } = await getLeaderboard();
  const rows = (leaderboard.rows as LeaderboardRow[]).filter((r) => r.status.toLowerCase() === "forward_test");

  if (!connected) {
    return (
      <div className="mx-auto max-w-[1100px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
        <SectionHeader eyebrow="forward-test" title="Which survivors are proving themselves?" />
        <StrategyStages />
        <NotConnected
          configured={engineConfigured}
          what="Forward-test shows each survivor's own live-data track — net-of-fee P&L, per strategy, no real money and no pooled wallet. All real, never fabricated."
        />
      </div>
    );
  }

  // Rank by net-of-fee P&L — the only thing that earns a launch.
  const ranked = [...rows].sort((a, b) => b.net_pct - a.net_pct);
  const passing = ranked.filter((r) => r.net_pct > 0).length;
  const best = ranked.length ? ranked[0].net_pct : 0;

  return (
    <div className="mx-auto max-w-[1100px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-7 lg:px-7">
      <SectionHeader
        eyebrow="forward-test"
        title="Which survivors are proving themselves?"
        aside={<Badge variant="iris"><LineChart className="size-3" /> per strategy · real prices · no real money</Badge>}
      />

      <StrategyStages />

      {/* The model, in one line — kills the old pooled-wallet mental model. */}
      <Card>
        <CardContent className="py-4">
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] leading-relaxed text-muted">
            <ShieldCheck className="size-4 shrink-0 text-up" />
            <span>
              Each survivor trades <span className="font-medium text-foreground">its own track</span> on real prices —
              there is <span className="font-medium text-foreground">no pooled wallet</span>. A strategy must show
              positive net-of-fee P&amp;L here before you launch it as a standalone Live bot with its own capital.
            </span>
          </p>
        </CardContent>
      </Card>

      {/* KPIs — counts, not a pooled equity curve. */}
      <section className="grid grid-cols-3 gap-3">
        <Stat label="In forward-test" value={ranked.length} accent="iris" icon={<LineChart className="size-4" />} />
        <Stat
          label="Passing (net > 0)"
          value={`${passing}/${ranked.length}`}
          accent={passing > 0 ? "up" : "warn"}
          icon={<TrendingUp className="size-4" />}
        />
        <Stat
          label="Best net"
          value={ranked.length ? <span className={best >= 0 ? "text-up" : "text-down"}>{formatPct(best)}</span> : "—"}
          accent={best >= 0 ? "up" : "down"}
        />
      </section>

      {/* Per-strategy tracks */}
      {ranked.length === 0 ? (
        <Card>
          <CardContent>
            <EmptyState
              title="Nothing in forward-test yet."
              hint="Survivors of the Gate land here to prove themselves on real prices. Author candidates in the Lab, or drop a thesis via Claude Code (see Commands)."
            />
          </CardContent>
        </Card>
      ) : (
        <section className="grid gap-3 sm:grid-cols-2">
          {ranked.map((r) => {
            const up = r.net_pct >= 0;
            // ADVISORY maturity (engine: master/forward_maturity.py) — surfaced, NEVER enforced. live_ready means
            // the track both matured (>= FORWARD_TEST_MIN_DAYS) and is net-positive; the operator still decides.
            const ageDays = Math.floor(r.forward_age_days);
            return (
              <Card key={r.version_id}>
                <CardContent className="space-y-3 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-[13.5px] font-medium text-foreground">{r.name}</div>
                      <div className="truncate text-[11px] text-quiet">{r.lineage}</div>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <Badge variant={up ? "up" : "down"}>{up ? "passing" : "underwater"}</Badge>
                      {r.live_ready ? (
                        <Badge variant="iris"><ShieldCheck className="size-3" /> live-ready · advisory</Badge>
                      ) : (
                        <Badge variant="muted">maturing · advisory</Badge>
                      )}
                    </div>
                  </div>
                  <div className="grid grid-cols-3 gap-2 text-center">
                    <Metric label="Net (fees in)" value={formatSigned(r.net_pct) + "%"} tone={up ? "text-up" : "text-down"} icon={up ? <TrendingUp className="size-3" /> : <TrendingDown className="size-3" />} />
                    <Metric label="Forward age" value={`${ageDays}d`} tone="text-foreground" />
                    <Metric label="Overfit (PBO)" value={formatPct(r.pbo * 100, 0)} tone={r.pbo <= 0.2 ? "text-up" : r.pbo <= 0.5 ? "text-warn" : "text-down"} />
                  </div>
                  <div className="flex items-center gap-2 pt-0.5">
                    <Link
                      href={`/strategy/${r.version_id}`}
                      className="inline-flex items-center gap-1.5 rounded-md border border-border/70 bg-surface-2/40 px-2.5 py-1.5 text-[12px] font-medium text-muted transition-colors hover:border-border hover:text-foreground"
                    >
                      <Microscope className="size-3.5" /> View
                    </Link>
                    <Link
                      href="/live"
                      className="inline-flex items-center gap-1.5 rounded-md border border-border/70 bg-surface-2/40 px-2.5 py-1.5 text-[12px] font-medium text-foreground transition-colors hover:border-info/60 hover:bg-info/10 hover:text-info"
                    >
                      <Radio className="size-3.5 text-info" /> Launch Live <ArrowRight className="size-3.5" />
                    </Link>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </section>
      )}
    </div>
  );
}

function Metric({ label, value, tone, icon }: { label: string; value: string; tone: string; icon?: ReactNode }) {
  return (
    <div className="rounded-md border border-border/50 bg-surface-2/30 px-2 py-2">
      <div className={`flex items-center justify-center gap-1 text-[14px] font-semibold tabular ${tone}`}>
        {icon}
        {value}
      </div>
      <div className="mt-0.5 text-[10px] uppercase tracking-wide text-quiet">{label}</div>
    </div>
  );
}
