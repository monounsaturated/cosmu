"use client";

import { Brain, Database, FlaskConical, Layers, Skull, TrendingUp, Zap } from "lucide-react";
import type {
  IntelligenceResponse,
  FunnelStats,
  GateEfficiency,
  MemoryDepth,
  RegimeCell,
  DataSource,
  TickStats,
} from "@/app/data";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export function SystemIntelligence({
  intelligence,
  connected,
}: {
  intelligence: IntelligenceResponse;
  connected: boolean;
}) {
  if (!connected) return null;
  const { funnel, gate_efficiency, memory, regime_coverage, data_freshness, ticks } = intelligence;
  const isEmpty = funnel.authored === 0 && ticks.total === 0;

  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <Brain className="size-4 text-iris-soft" />
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">
          System intelligence
        </h2>
        {gate_efficiency.improving && (
          <Badge variant="up">
            <TrendingUp className="mr-0.5 size-3" /> learning
          </Badge>
        )}
      </div>

      {isEmpty ? (
        <Card>
          <CardContent className="py-8 text-center text-[13px] text-quiet">
            No intelligence yet. Numbers appear once the machine runs its first autonomous tick.
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3 lg:grid-cols-3">
          <StrategyFunnel funnel={funnel} />
          <BrainState memory={memory} efficiency={gate_efficiency} ticks={ticks} />
          <RegimeMap cells={regime_coverage.grid} covered={regime_coverage.covered} total={regime_coverage.total} />
        </div>
      )}

      {data_freshness.length > 0 && <DataSources sources={data_freshness} />}
    </section>
  );
}

function StrategyFunnel({ funnel }: { funnel: FunnelStats }) {
  const stages = [
    { label: "Authored", value: funnel.authored, color: "bg-muted" },
    { label: "Gate passed", value: funnel.gate_passed, color: "bg-info" },
    { label: "Funded", value: funnel.funded, color: "bg-iris" },
    { label: "Live", value: funnel.live, color: "bg-up" },
  ];
  const max = Math.max(funnel.authored, 1);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-1.5">
          <FlaskConical className="size-3.5 text-iris-soft" />
          <CardTitle>Strategy funnel</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {stages.map((stage) => {
          const pct = Math.max(4, (stage.value / max) * 100);
          return (
            <div key={stage.label}>
              <div className="mb-1 flex items-center justify-between">
                <span className="text-[11px] font-medium text-quiet">{stage.label}</span>
                <span className="tabular text-[13px] font-semibold text-foreground">{stage.value}</span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
                <div
                  className={cn("h-full rounded-full transition-all duration-500", stage.color)}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
        {funnel.killed > 0 && (
          <div className="flex items-center gap-1.5 text-[11px] text-quiet">
            <Skull className="size-3 text-down" />
            {funnel.killed} killed by the gate
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function BrainState({
  memory,
  efficiency,
  ticks,
}: {
  memory: MemoryDepth;
  efficiency: GateEfficiency;
  ticks: TickStats;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-1.5">
          <Brain className="size-3.5 text-iris-soft" />
          <CardTitle>Brain state</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <MiniStat label="Memories" value={memory.total} detail={`${memory.dead_ends} dead ends, ${memory.winners} winners`} />
          <MiniStat label="Skills" value={memory.skills} detail="distilled recipes" />
          <MiniStat
            label="Gate rate"
            value={`${Math.round(efficiency.current * 100)}%`}
            detail={efficiency.improving ? "improving" : efficiency.trend.length > 0 ? "stable" : "no data"}
            accent={efficiency.improving ? "up" : undefined}
          />
          <MiniStat label="Ticks" value={ticks.total} detail={`${ticks.avg_survivors_per_tick} avg survivors`} />
        </div>

        {efficiency.trend.length >= 2 && (
          <div className="space-y-1">
            <span className="text-[10px] font-medium uppercase tracking-wide text-quiet">Gate efficiency trend</span>
            <SparkLine values={efficiency.trend} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function MiniStat({
  label,
  value,
  detail,
  accent,
}: {
  label: string;
  value: string | number;
  detail: string;
  accent?: "up" | "down";
}) {
  return (
    <div>
      <div className="text-[10px] font-medium uppercase tracking-wide text-quiet">{label}</div>
      <div className={cn("mt-0.5 text-lg font-semibold tabular text-foreground", accent === "up" && "text-up", accent === "down" && "text-down")}>
        {value}
      </div>
      <div className="text-[10px] text-muted">{detail}</div>
    </div>
  );
}

function SparkLine({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const max = Math.max(...values, 0.01);
  const min = Math.min(...values, 0);
  const range = max - min || 1;
  const w = 100;
  const h = 24;
  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * w;
      const y = h - ((v - min) / range) * h;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-6 w-full" preserveAspectRatio="none">
      <polyline points={points} fill="none" stroke="var(--color-iris)" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

function RegimeMap({
  cells,
  covered,
  total,
}: {
  cells: RegimeCell[];
  covered: number;
  total: number;
}) {
  const trends = ["bull", "bear", "chop"];
  const vols = ["low", "mid", "high"];
  const lookup = new Map(cells.map((c) => [`${c.trend}/${c.vol}`, c.strategies]));

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-1.5">
          <Layers className="size-3.5 text-iris-soft" />
          <CardTitle>Regime coverage</CardTitle>
        </div>
        <span className="text-[11px] text-quiet">
          {covered}/{total} regimes
        </span>
      </CardHeader>
      <CardContent>
        <div className="space-y-1">
          {/* Header row */}
          <div className="grid grid-cols-4 gap-1">
            <div />
            {vols.map((v) => (
              <div key={v} className="text-center text-[9px] font-medium uppercase tracking-wide text-quiet">
                {v} vol
              </div>
            ))}
          </div>
          {/* Data rows */}
          {trends.map((trend) => (
            <div key={trend} className="grid grid-cols-4 gap-1">
              <div className="flex items-center text-[10px] font-medium text-quiet capitalize">{trend}</div>
              {vols.map((vol) => {
                const count = lookup.get(`${trend}/${vol}`) ?? 0;
                const filled = count > 0;
                return (
                  <div
                    key={`${trend}/${vol}`}
                    className={cn(
                      "flex aspect-square items-center justify-center rounded-md text-[11px] font-semibold tabular transition-colors",
                      filled
                        ? "bg-iris/20 text-iris"
                        : "bg-surface-2/40 text-quiet/50"
                    )}
                  >
                    {count || "—"}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
        {covered === 0 && (
          <p className="mt-3 text-[11px] text-quiet">
            No regime coverage yet. Strategies need to prove edge in specific market conditions.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function DataSources({ sources }: { sources: DataSource[] }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-1.5">
          <Database className="size-3.5 text-iris-soft" />
          <CardTitle>Data sources</CardTitle>
        </div>
        <span className="text-[11px] text-quiet">{sources.length} providers</span>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap gap-2">
          {sources.map((s) => (
            <div
              key={s.source}
              className="flex items-center gap-1.5 rounded-md border border-border/50 bg-surface-2/30 px-2.5 py-1.5"
            >
              <Zap className="size-3 text-iris-soft" />
              <span className="text-[11px] font-medium text-foreground">{s.source}</span>
              <span className="tabular text-[10px] text-muted">{s.points.toLocaleString()} pts</span>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
