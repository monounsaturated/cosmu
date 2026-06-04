"use client";

// module: the cockpit's data-rich widgets — the new, tool-aligned blocks the operator can mix into the
// Overview. The headline KPIs deliberately drop $-denominated vanity numbers (there is no real money by
// default) in favour of metrics aligned to what the machine actually does: GATE pass-rate + funnel, EDGE
// quality (net-of-fee % + deflated Sharpe), and DATA freshness. Every block renders from real engine
// state and falls back to an honest empty — never a fabricated figure.

import type { ReactNode } from "react";
import Link from "next/link";
import {
  Activity,
  Database,
  FlaskConical,
  Gauge,
  Layers,
  LineChart,
  ListChecks,
  Radio,
  ShieldCheck,
  TrendingUp
} from "lucide-react";
import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";
import { CommandHint } from "@/components/ui/command-hint";
import { MoneyState, moneyMode } from "@/components/ui/money-state";
import { EmptyState } from "@/components/ui/honest-state";
import { WidgetCard } from "./widget-card";
import { BarList, Funnel, Spark } from "@/components/charts/dash";
import { TvChart } from "@/components/charts/tv-chart";
import type { CockpitData } from "./cockpit-data";
import { TRACK_VS_AGGREGATE } from "@/lib/shared-content";
import { formatPct, formatUsd } from "@/lib/utils";
import { cn } from "@/lib/utils";

function median(xs: number[]): number | null {
  const v = xs.filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return null;
  const mid = Math.floor(v.length / 2);
  return v.length % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2;
}

const aliveRows = (rows: LeaderboardRow[]) => rows.filter((r) => r.status !== "killed");

// ── KPI rail ─────────────────────────────────────────────────────────────────────────────────────
// A Tremor-style metric tile: label, big value, a one-line sub, and an optional sparkline / command hint.
function MetricTile({
  label,
  value,
  sub,
  accent = "iris",
  icon,
  spark,
  command,
  badge
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  accent?: "iris" | "up" | "down" | "warn" | "info";
  icon?: ReactNode;
  spark?: number[];
  command?: string;
  badge?: ReactNode;
}) {
  const bar = {
    iris: "before:bg-iris",
    up: "before:bg-up",
    down: "before:bg-down",
    warn: "before:bg-warn",
    info: "before:bg-info"
  }[accent];
  return (
    // No overflow-hidden: the CommandHint popover must be free to escape the tile bounds.
    <Card className={cn("relative p-4 before:absolute before:left-0 before:top-4 before:bottom-4 before:w-0.5 before:rounded-full", bar)}>
      <div className="flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.07em] text-quiet">
          {icon}
          {label}
        </span>
        {command ? <CommandHint cmd={command} /> : badge}
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-tight tabular text-foreground">{value}</div>
      {sub ? <div className="mt-1 text-[11.5px] text-muted">{sub}</div> : null}
      {spark && spark.length >= 2 ? <Spark values={spark} tone={accent === "down" ? "down" : "iris"} className="mt-2" /> : null}
    </Card>
  );
}

export function EdgeKpis({ data }: { data: CockpitData }) {
  const alive = aliveRows(data.leaderboard);
  const proving = data.population.forward_test;
  const eff = data.intelligence.gate_efficiency;
  const dsharpe = median(alive.map((r) => r.deflated_sharpe));
  const netEdge = median(alive.filter((r) => r.status === "forward_test").map((r) => r.net_pct));
  const sources = data.intelligence.data_freshness;
  const fresh = sources.filter((s) => s.points > 0).length;
  const mode = moneyMode({ live: data.overview.live_enabled });

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <MetricTile
        label="Edge · dSharpe"
        icon={<TrendingUp className="size-3.5" />}
        accent={dsharpe !== null && dsharpe > 0 ? "up" : "warn"}
        value={dsharpe !== null ? dsharpe.toFixed(2) : "—"}
        sub={alive.length ? `median across ${alive.length} survivor${alive.length > 1 ? "s" : ""}` : "no survivors yet"}
      />
      <MetricTile
        label="Gate pass-rate"
        icon={<Gauge className="size-3.5" />}
        accent={eff.improving ? "up" : "iris"}
        value={eff.trend.length ? `${Math.round(eff.current * 100)}%` : "—"}
        sub={eff.trend.length ? (eff.improving ? "improving" : "stable") : "no cohorts gated yet"}
        spark={eff.trend}
        command="/run-gate"
      />
      <MetricTile
        label="Net edge · SIM"
        icon={<LineChart className="size-3.5" />}
        accent={netEdge !== null ? (netEdge >= 0 ? "up" : "down") : "iris"}
        value={netEdge !== null ? <span className={netEdge >= 0 ? "text-up" : "text-down"}>{formatPct(netEdge)}</span> : "—"}
        sub={proving ? `median of ${proving} proving track${proving > 1 ? "s" : ""} · net of fees` : "nothing proving yet"}
        badge={<MoneyState mode={mode} withInfo={false} />}
      />
      <MetricTile
        label="Data freshness"
        icon={<Database className="size-3.5" />}
        accent={fresh > 0 ? "up" : "warn"}
        value={sources.length ? `${fresh}/${sources.length}` : "—"}
        sub={sources.length ? "sources reporting points" : "no sources reporting"}
        command="/manage-data"
      />
    </div>
  );
}

// ── Gate funnel ──────────────────────────────────────────────────────────────────────────────────
export function GateFunnelWidget({ data }: { data: CockpitData }) {
  const f = data.intelligence.funnel;
  const empty = f.authored === 0;
  return (
    <WidgetCard title="Gate funnel" icon={<FlaskConical className="size-4" />} command="/run-gate" href="/lab" hrefLabel="Lab">
      {empty ? (
        <EmptyState
          title="No candidates gated yet."
          hint="Authored strategies flow Authored → Gate passed → Funded → Live. The deterministic Gate decides what survives — never an LLM."
          icon={<FlaskConical className="size-5" />}
        />
      ) : (
        <>
          <Funnel
            stages={[
              { label: "Authored", value: f.authored, tone: "muted" },
              { label: "Screened", value: f.screened, tone: "info" },
              { label: "Gate passed", value: f.gate_passed, tone: "iris" },
              { label: "Funded", value: f.funded, tone: "gold" },
              { label: "Live", value: f.live, tone: "up" }
            ]}
          />
          {f.killed > 0 ? (
            <div className="mt-3 text-[11px] text-quiet">
              <span className="text-down">{f.killed}</span> killed by the Gate — the graveyard is kept (no survivor bias).
            </div>
          ) : null}
        </>
      )}
    </WidgetCard>
  );
}

// ── Edge quality (survivors ranked by net-of-fee %) ───────────────────────────────────────────────
export function EdgeQualityWidget({ data }: { data: CockpitData }) {
  const ranked = aliveRows(data.leaderboard)
    .slice()
    .sort((a, b) => b.net_pct - a.net_pct)
    .slice(0, 6);
  return (
    <WidgetCard
      title="Edge quality"
      icon={<TrendingUp className="size-4" />}
      href="/strategies"
      hrefLabel="All"
      aside={<Tooltip content={TRACK_VS_AGGREGATE} />}
    >
      {ranked.length === 0 ? (
        <EmptyState
          title="No surviving edges yet."
          hint="Strategies that clear the Gate rank here by net-of-fee %, with their deflated Sharpe and overfit (PBO)."
          icon={<TrendingUp className="size-5" />}
        />
      ) : (
        <BarList
          data={ranked.map((r) => ({
            name: r.name,
            value: r.net_pct,
            tone: r.net_pct >= 0 ? "up" : "down",
            display: <span className={r.net_pct >= 0 ? "text-up" : "text-down"}>{formatPct(r.net_pct)}</span>,
            sub: `dSharpe ${r.deflated_sharpe.toFixed(2)} · PBO ${Math.round(r.pbo * 100)}%`,
            href: `/strategy/${r.version_id}`
          }))}
        />
      )}
    </WidgetCard>
  );
}

// ── Equity (TradingView lightweight-charts) ───────────────────────────────────────────────────────
export function EquityWidget({ data }: { data: CockpitData }) {
  const mode = moneyMode({ live: data.overview.live_enabled });
  return (
    <WidgetCard
      title="Net across forward-tests"
      icon={<LineChart className="size-4" />}
      href="/forward-test"
      hrefLabel="Forward-test"
      aside={<Tooltip content={TRACK_VS_AGGREGATE} />}
    >
      <TvChart points={data.overview.equity_curve} mode={mode} height={260} valueKind="usd" />
    </WidgetCard>
  );
}

// ── Working versions (survivors proving on their own tracks) ──────────────────────────────────────
const statusVariant: Record<string, "up" | "warn" | "down" | "info"> = {
  forward_test: "up",
  live: "info",
  screening: "warn",
  killed: "down"
};

export function WorkingVersionsWidget({ data }: { data: CockpitData }) {
  const working = aliveRows(data.leaderboard)
    .slice()
    .sort((a, b) => b.net_pct - a.net_pct)
    .slice(0, 6);
  return (
    <WidgetCard
      title="Working versions"
      icon={<ListChecks className="size-4" />}
      command="/create-strategy"
      href="/strategies"
      hrefLabel="All"
    >
      {working.length === 0 ? (
        <EmptyState
          title="No surviving versions yet."
          hint="Gate-passed strategies start a forward-test track and appear here. Author one from the Lab or via Claude Code, or wait for the next autonomous cycle."
        />
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          {working.map((row) => (
            <Link
              key={row.version_id}
              href={`/strategy/${row.version_id}`}
              className="flex items-center justify-between gap-3 rounded-md border border-border/50 bg-surface-2/30 px-3 py-2.5 transition-colors hover:border-border hover:bg-surface-2/55"
            >
              <div className="min-w-0">
                <div className="truncate text-[12.5px] font-medium text-foreground">{row.name}</div>
                <div className="text-[11px] text-quiet">net of fees</div>
              </div>
              <div className="flex shrink-0 items-center gap-2.5">
                <span className={cn("tabular text-[13px] font-medium", row.net_pct >= 0 ? "text-up" : "text-down")}>
                  {formatPct(row.net_pct)}
                </span>
                <Badge variant={statusVariant[row.status] ?? "muted"}>{row.status}</Badge>
              </div>
            </Link>
          ))}
        </div>
      )}
    </WidgetCard>
  );
}

// ── Mind consensus ────────────────────────────────────────────────────────────────────────────────
const consensusMeta: Record<string, { label: string; cls: string }> = {
  bullish: { label: "Bullish", cls: "text-up" },
  bearish: { label: "Bearish", cls: "text-down" },
  neutral: { label: "Neutral", cls: "text-muted" },
  abstain: { label: "Abstain", cls: "text-quiet" }
};

export function MindWidget({ data }: { data: CockpitData }) {
  const mind = data.mind;
  const con = consensusMeta[mind.consensus] ?? consensusMeta.neutral;
  const conviction = Math.round((mind.conviction ?? 0) * 100);
  const agreement = Math.round((mind.agreement ?? 0) * 100);
  const stances = (mind.stances ?? []).slice(0, 4);
  return (
    <WidgetCard title="The Mind" icon={<Activity className="size-4" />} command="/scan-signals" href="/mind" hrefLabel="Mind">
      {stances.length === 0 ? (
        <EmptyState
          title="No signal yet — abstaining."
          hint="The analyst panel debates a consensus only from real point-in-time signals. With no data it abstains; it never fabricates a view. The Mind reasons — it never moves money."
        />
      ) : (
        <div className="space-y-3">
          <div className="flex items-end justify-between gap-3">
            <div>
              <div className={cn("text-2xl font-semibold tracking-tight", con.cls)}>
                {con.label}
                {mind.contested ? <span className="ml-1.5 align-middle text-[10px] font-medium uppercase text-warn">contested</span> : null}
              </div>
              <div className="mt-0.5 text-[11.5px] text-quiet">
                {conviction}% conviction · {agreement}% agreement · {stances.length} analysts
              </div>
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {stances.map((s) => (
              <span key={s.perspective} className="rounded-md border border-border/50 bg-surface-2/30 px-2 py-1 text-[11px] text-muted">
                {s.perspective}: <span className={consensusMeta[s.lean]?.cls ?? "text-muted"}>{s.lean}</span>
              </span>
            ))}
          </div>
          <p className="border-t border-border/50 pt-2 text-[11px] leading-relaxed text-quiet">
            <ShieldCheck className="mr-1 inline size-3 text-up align-[-1px]" />
            {mind.railguard}
          </p>
        </div>
      )}
    </WidgetCard>
  );
}

// ── Regime coverage ──────────────────────────────────────────────────────────────────────────────
export function RegimeWidget({ data }: { data: CockpitData }) {
  const cov = data.intelligence.regime_coverage;
  const trends = ["bull", "bear", "chop"];
  const vols = ["low", "mid", "high"];
  const lookup = new Map(cov.grid.map((c) => [`${c.trend}/${c.vol}`, c.strategies]));
  return (
    <WidgetCard
      title="Regime coverage"
      icon={<Layers className="size-4" />}
      href="/mind"
      hrefLabel="Mind"
      aside={<span className="text-[11px] text-quiet">{cov.covered}/{cov.total}</span>}
    >
      <div className="space-y-1">
        <div className="grid grid-cols-4 gap-1">
          <div />
          {vols.map((v) => (
            <div key={v} className="text-center text-[9px] font-medium uppercase tracking-wide text-quiet">{v} vol</div>
          ))}
        </div>
        {trends.map((trend) => (
          <div key={trend} className="grid grid-cols-4 gap-1">
            <div className="flex items-center text-[10px] font-medium capitalize text-quiet">{trend}</div>
            {vols.map((vol) => {
              const count = lookup.get(`${trend}/${vol}`) ?? 0;
              return (
                <div
                  key={`${trend}/${vol}`}
                  className={cn(
                    "flex aspect-square items-center justify-center rounded-md text-[11px] font-semibold tabular",
                    count > 0 ? "bg-iris/20 text-iris" : "bg-surface-2/40 text-quiet/50"
                  )}
                >
                  {count || "—"}
                </div>
              );
            })}
          </div>
        ))}
      </div>
      {cov.covered === 0 ? (
        <p className="mt-3 text-[11px] text-quiet">No regime coverage yet — strategies prove edge in specific market conditions.</p>
      ) : null}
    </WidgetCard>
  );
}

// ── Live (research + live coexist) ────────────────────────────────────────────────────────────────
export function LiveWidget({ data }: { data: CockpitData }) {
  const pos = data.positions;
  const armed = pos.armed;
  const totalUnrealized = pos.positions.reduce((s, p) => s + (p.unrealized_pnl ?? 0), 0);
  return (
    <WidgetCard
      title="Live execution"
      icon={<Radio className="size-4" />}
      href="/live"
      hrefLabel="Live"
      aside={armed ? <Badge variant="info"><Activity className="size-3" /> Armed</Badge> : <Badge variant="muted"><ShieldCheck className="size-3" /> Sim only</Badge>}
    >
      {!armed ? (
        <div className="space-y-2">
          <p className="text-[12.5px] leading-relaxed text-muted">
            Live trading is <span className="font-medium text-foreground">off</span>. Real orders need all five interlocks —
            toggle on + execution keys + Gate passed + caps available + no kill-switch. Until then everything is simulated.
          </p>
          <div className="flex flex-wrap gap-1.5 pt-1">
            {["Toggle on", "Exec keys", "Gate passed", "Caps", "Kill-switch clear"].map((x) => (
              <span key={x} className="rounded-md border border-border/50 bg-surface-2/30 px-2 py-1 text-[10.5px] text-quiet">{x}</span>
            ))}
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-2 text-center">
          <LiveStat label="Mode" value={pos.mode} />
          <LiveStat label="Positions" value={String(pos.positions.length)} />
          <LiveStat
            label="Unrealized"
            value={<span className={totalUnrealized >= 0 ? "text-up" : "text-down"}>{formatUsd(totalUnrealized)}</span>}
          />
        </div>
      )}
    </WidgetCard>
  );
}

function LiveStat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-md border border-border/50 bg-surface-2/30 px-2 py-2">
      <div className="tabular text-[14px] font-semibold text-foreground">{value}</div>
      <div className="mt-0.5 text-[10px] uppercase tracking-wide text-quiet">{label}</div>
    </div>
  );
}
