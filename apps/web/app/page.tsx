// Dashboard — the fund read-out (docs/PRODUCT.md Epic A; VISION §1.1, §11). In one glance: are we making
// money, net of every cost, and is the machine healthy? It shows aggregate equity (Σ of all standalone
// tracks — a read-out, NOT a pooled wallet), P&L net of all costs, an opex-vs-alpha gauge, a data-freshness
// + Mind-consensus banner, and the global live toggle (off by default). HONEST: when the engine is
// unreachable we render a single "not connected" state and never a fabricated read-out.

import Link from "next/link";
import { Activity, ArrowRight, Brain, Database, DollarSign, Scale, TrendingUp } from "lucide-react";
import { engineConfigured, getIntelligence, getMind, getOverview } from "./data";
import type { CostSlice, MindResponse } from "@cosmu/contracts-ts";
import type { DataSource } from "./data";
import { NotConnected } from "@/components/ui/honest-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Stat } from "@/components/ui/stat";
import { Tooltip } from "@/components/ui/tooltip";
import { MoneyState, moneyMode } from "@/components/ui/money-state";
import { TvChart } from "@/components/charts/tv-chart";
import { ChartEmpty } from "@/components/charts/chart-kit";
import { GlobalLiveToggle } from "@/components/live/global-live-toggle";
import { cn, formatSigned, formatUsd, timeAgo } from "@/lib/utils";

export default async function DashboardPage() {
  const [{ overview, connected }, { mind }, { intelligence }] = await Promise.all([
    getOverview(),
    getMind(),
    getIntelligence()
  ]);

  if (!connected) {
    return (
      <div className="mx-auto max-w-[1200px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
        <Header live={false} connected={false} />
        <NotConnected
          configured={engineConfigured}
          what="The Dashboard is the fund read-out — aggregate equity, P&L net of all costs, and machine health. Connect the engine to see real numbers; nothing is fabricated."
        />
      </div>
    );
  }

  const equity = overview.equity_curve;
  const latestEquity = equity.length > 0 ? equity[equity.length - 1].value : null;
  const money = moneyMode({ live: overview.live_enabled });

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
      <Header live={overview.live_enabled} connected />

      {/* Health banner: data freshness + the committee's current read. */}
      <ReadBanner mind={mind} sources={intelligence.data_freshness} />

      {/* The three numbers that answer "are we making money?" */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Stat
          label="Aggregate equity"
          value={latestEquity == null ? "—" : formatUsd(latestEquity)}
          hint="Σ of all standalone tracks — a read-out, not a pooled wallet."
          icon={<TrendingUp className="size-4" />}
        />
        <Stat
          label="P&L · net of all costs"
          value={<span className={cn(overview.pnl_net >= 0 ? "text-up" : "text-down")}>{formatSigned(overview.pnl_net)}</span>}
          hint="Net of fees, slippage, funding, and opex."
          accent={overview.pnl_net >= 0 ? "up" : "down"}
          icon={<DollarSign className="size-4" />}
        />
        <OpexAlphaGauge ratio={overview.opex_vs_alpha} />
      </div>

      {/* Aggregate equity curve. */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            Aggregate equity (SIM + live)
            <Tooltip content="The Σ of every standalone forward-test track, marked to market. This is a read-out — there is no pooled wallet you trade from." />
          </CardTitle>
          <MoneyState mode={money} />
        </CardHeader>
        <CardContent>
          {equity.length >= 2 ? (
            <TvChart points={equity} mode={money} height={260} valueKind="usd" />
          ) : (
            <ChartEmpty
              title="No track equity yet"
              hint="The aggregate curve renders once strategies clear the Gate and open standalone tracks. Nothing is fabricated."
              height={260}
            />
          )}
        </CardContent>
      </Card>

      {/* Costs strip + the global live toggle. */}
      <div className="grid gap-3 lg:grid-cols-[1.3fr_1fr]">
        <CostsCard costs={overview.costs} />
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-1.5">
              <Activity className="size-4 text-iris-soft" /> Live trading
            </CardTitle>
          </CardHeader>
          <CardContent>
            <GlobalLiveToggle initialEnabled={Boolean(overview.live_enabled)} connected={connected} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Header({ live, connected }: { live: boolean; connected: boolean }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">dashboard</div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">Fund read-out</h1>
      </div>
      {connected ? <MoneyState mode={moneyMode({ live })} /> : null}
    </div>
  );
}

const CONSENSUS: Record<string, { label: string; variant: "up" | "down" | "muted" }> = {
  bullish: { label: "Bullish", variant: "up" },
  bearish: { label: "Bearish", variant: "down" },
  neutral: { label: "Neutral", variant: "muted" }
};

// Health banner — the two things that tell you whether to trust today's read: is the machine fed (data
// freshness), and what does the committee believe (Mind consensus + conviction). Honest: stale is flagged.
function ReadBanner({ mind, sources }: { mind: MindResponse; sources: DataSource[] }) {
  const reporting = sources.filter((s) => s.points > 0);
  const freshest = reporting
    .map((s) => s.last_at)
    .filter((t): t is string => Boolean(t))
    .sort()
    .at(-1);
  const consensus = CONSENSUS[mind.consensus] ?? CONSENSUS.neutral;

  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-3 rounded-lg border border-border/70 bg-surface-2/30 px-4 py-3">
      <Link href="/mind" className="group flex items-center gap-2">
        <Brain className="size-4 text-iris-soft" />
        <span className="text-[12px] text-quiet">Mind consensus</span>
        <Badge variant={consensus.variant}>{consensus.label}</Badge>
        <span className="text-[12px] text-muted">{Math.round(mind.conviction * 100)}% conviction</span>
        {mind.contested ? <Badge variant="warn">contested</Badge> : null}
        <ArrowRight className="size-3.5 text-quiet transition-transform group-hover:translate-x-0.5" />
      </Link>
      <div className="flex items-center gap-2">
        <Database className="size-4 text-iris-soft" />
        <span className="text-[12px] text-quiet">Data</span>
        <span className="text-[12px] text-muted">
          {reporting.length}/{sources.length} sources reporting
        </span>
        {freshest ? <span className="text-[11.5px] text-quiet">· freshest {timeAgo(freshest)}</span> : null}
      </div>
    </div>
  );
}

// Opex-vs-alpha gauge — is R&D spend justified by yield? `ratio` is opex as a fraction of trailing alpha:
// < 1 means alpha covers opex; ≥ 1 means opex is eating the edge. Colour grades it honestly.
function OpexAlphaGauge({ ratio }: { ratio: number }) {
  const pct = Math.max(0, Math.min(100, Math.round(ratio * 100)));
  const tone = ratio <= 0.5 ? "up" : ratio < 1 ? "warn" : "down";
  const barColor = tone === "up" ? "bg-up" : tone === "warn" ? "bg-warn" : "bg-down";
  const label = ratio <= 0 ? "no opex yet" : ratio < 1 ? "alpha covers opex" : "opex exceeds alpha";
  return (
    <Card className="relative overflow-hidden p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] font-medium uppercase tracking-[0.07em] text-quiet">Opex vs alpha</span>
        <Scale className="size-4 text-muted" />
      </div>
      <div className="mt-2 flex items-baseline gap-1.5">
        <span className={cn("text-2xl font-semibold tabular", tone === "up" ? "text-up" : tone === "warn" ? "text-warn" : "text-down")}>
          {ratio <= 0 ? "—" : `${pct}%`}
        </span>
        <span className="text-[12px] text-muted">{label}</span>
      </div>
      <div className="mt-2.5 h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
        <div className={cn("h-full rounded-full transition-all", barColor)} style={{ width: `${Math.max(pct, 2)}%` }} />
      </div>
    </Card>
  );
}

function CostsCard({ costs }: { costs: CostSlice[] }) {
  const total = costs.reduce((sum, c) => sum + c.amount, 0);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <DollarSign className="size-4 text-iris-soft" /> Costs
        </CardTitle>
        <Link href="/costs" className="inline-flex items-center gap-1 text-[12.5px] font-medium text-iris-soft hover:underline">
          Breakdown <ArrowRight className="size-3.5" />
        </Link>
      </CardHeader>
      <CardContent>
        {costs.length === 0 ? (
          <p className="py-4 text-center text-[12px] text-quiet">No costs recorded yet — nothing fabricated.</p>
        ) : (
          <div className="space-y-2">
            <div className="flex items-baseline justify-between">
              <span className="text-[12px] text-muted">Trailing opex</span>
              <span className="tabular text-[15px] font-semibold text-foreground">{formatUsd(total)}</span>
            </div>
            <ul className="space-y-1.5">
              {costs.map((c) => (
                <li key={c.category} className="flex items-center justify-between text-[12px]">
                  <span className="capitalize text-quiet">{c.category}</span>
                  <span className="tabular text-muted">{formatUsd(c.amount)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
