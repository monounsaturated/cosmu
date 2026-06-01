// module: research-brain charts — Deliverable #3. Two visuals reading the existing getBrain() data:
//   - GateFunnel: horizontal bars Generated -> Passed / Killed, with the kill-rate called out.
//   - SurvivalDistribution: bar chart of surviving candidates' survival_score (0..1), the model's
//     estimate each edge persists OOS. Both themed to the OKLch tokens. Client components.
// These ADD to the existing brain panel; they don't replace it.
"use client";

import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import type { BrainResponse } from "@cosmu/contracts-ts";
import { axisProps, chartColors, ChartEmpty, TooltipRow, TooltipShell, useReducedMotion } from "./chart-kit";
import { formatPct } from "@/lib/utils";

type Gated = BrainResponse["gated"];
type Survivor = BrainResponse["survivors"][number];

export function GateFunnel({ gated }: { gated: Gated }) {
  const reduced = useReducedMotion();
  const data = [
    { stage: "Generated", count: gated.generated, fill: chartColors.iris },
    { stage: "Passed", count: gated.passed, fill: chartColors.up },
    { stage: "Killed", count: gated.killed, fill: chartColors.down }
  ];
  if (gated.generated === 0) {
    return <ChartEmpty title="No candidates generated yet" height={160} />;
  }
  return (
    <div className="space-y-2">
      <ResponsiveContainer width="100%" height={160} minWidth={0} debounce={50}>
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 40, bottom: 0, left: 0 }}>
            <XAxis type="number" {...axisProps} hide />
            <YAxis type="category" dataKey="stage" {...axisProps} width={78} />
            <Tooltip cursor={{ fill: "var(--color-surface-2)", fillOpacity: 0.4 }} content={<FunnelTooltip total={gated.generated} />} />
            <Bar dataKey="count" radius={[0, 6, 6, 0]} isAnimationActive={!reduced} barSize={22}>
              {data.map((d) => (
                <Cell key={d.stage} fill={d.fill} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-[11.5px]">
        <span className="flex items-center gap-3">
          <span className="text-iris-soft tabular">{gated.generated} generated</span>
          <span className="text-up tabular">{gated.passed} passed</span>
          <span className="text-down tabular">{gated.killed} killed</span>
        </span>
        <span className="text-warn">kill rate {formatPct(gated.kill_rate * 100, 1)}</span>
      </div>
    </div>
  );
}

type FunnelDatum = { stage: string; count: number };
function FunnelTooltip({ active, payload, total }: { active?: boolean; payload?: { payload: FunnelDatum }[]; total: number }) {
  if (!active || !payload || payload.length === 0) return null;
  const d = payload[0].payload;
  const pct = total ? (d.count / total) * 100 : 0;
  return (
    <TooltipShell>
      <div className="mb-1 text-[11.5px] font-medium text-foreground">{d.stage}</div>
      <TooltipRow label="Count" value={d.count} />
      <TooltipRow label="Of generated" value={`${pct.toFixed(1)}%`} />
    </TooltipShell>
  );
}

export function SurvivalDistribution({ survivors }: { survivors: Survivor[] }) {
  const reduced = useReducedMotion();
  if (!survivors || survivors.length === 0) {
    return <ChartEmpty title="No survivors yet" hint="Survival scores appear once a candidate clears the gate." height={180} />;
  }
  // Color by score: stronger persistence estimate -> iris, weaker -> warn.
  const data = survivors.map((s) => ({
    name: s.name,
    score: s.survival_score,
    net_pct: s.net_pct,
    fill: s.survival_score >= 0.6 ? chartColors.iris : chartColors.warn
  }));
  return (
    <ResponsiveContainer width="100%" height={Math.max(180, data.length * 34 + 24)} minWidth={0} debounce={50}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 44, bottom: 0, left: 0 }}>
          <XAxis type="number" domain={[0, 1]} {...axisProps} tickFormatter={(v: number) => v.toFixed(1)} />
          <YAxis type="category" dataKey="name" {...axisProps} width={140} tick={{ fill: "var(--color-muted)", fontSize: 11 }} />
          <Tooltip cursor={{ fill: "var(--color-surface-2)", fillOpacity: 0.4 }} content={<ScoreTooltip />} />
          <Bar dataKey="score" radius={[0, 6, 6, 0]} isAnimationActive={!reduced} barSize={18}>
            {data.map((d, i) => (
              <Cell key={i} fill={d.fill} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
  );
}

type ScoreDatum = { name: string; score: number; net_pct: number };
function ScoreTooltip({ active, payload }: { active?: boolean; payload?: { payload: ScoreDatum }[] }) {
  if (!active || !payload || payload.length === 0) return null;
  const d = payload[0].payload;
  return (
    <TooltipShell>
      <div className="mb-1 max-w-[200px] truncate text-[11.5px] font-medium text-foreground">{d.name}</div>
      <TooltipRow label="Survival score" value={d.score.toFixed(2)} />
      <TooltipRow label="Net %" value={<span className={d.net_pct >= 0 ? "text-up" : "text-down"}>{formatPct(d.net_pct)}</span>} />
    </TooltipShell>
  );
}
