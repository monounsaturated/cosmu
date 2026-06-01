// module: CostBars — compact opex breakdown for the Overview/portfolio (Deliverable #5).
// A single stacked horizontal bar of opex by category (llm / data / sandbox / infra ...),
// with the opex-vs-alpha ratio called out as a small gauge bar underneath. Skips gracefully
// (renders nothing) when there is no cost data. Themed to the OKLch tokens. Client component.
"use client";

import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { CostSlice } from "@cosmu/contracts-ts";
import { categoryPalette, TooltipRow, TooltipShell, useReducedMotion } from "./chart-kit";
import { formatUsd } from "@/lib/utils";

export function CostBars({ costs, opexVsAlpha }: { costs: CostSlice[]; opexVsAlpha: number }) {
  const reduced = useReducedMotion();
  if (!costs || costs.length === 0) return null;

  const total = costs.reduce((sum, c) => sum + c.amount, 0);
  // One stacked row: each category as its own dataKey so the bar segments side by side.
  const row: Record<string, number | string> = { name: "opex" };
  costs.forEach((c) => {
    row[c.category] = c.amount;
  });

  const ratioPct = Math.round(opexVsAlpha * 100);
  const ratioColor = ratioPct <= 25 ? "var(--color-up)" : ratioPct <= 50 ? "var(--color-warn)" : "var(--color-down)";

  return (
    <div className="space-y-3">
      <ResponsiveContainer width="100%" height={64} minWidth={0} debounce={50}>
          <BarChart data={[row]} layout="vertical" margin={{ top: 6, right: 6, bottom: 0, left: 6 }} barCategoryGap={0}>
            <XAxis type="number" hide />
            <YAxis type="category" dataKey="name" hide />
            <Tooltip cursor={{ fill: "var(--color-surface-2)", fillOpacity: 0.3 }} content={<CostTooltip total={total} />} />
            {costs.map((c, i) => (
              <Bar
                key={c.category}
                dataKey={c.category}
                stackId="opex"
                isAnimationActive={!reduced}
                radius={i === 0 ? [6, 0, 0, 6] : i === costs.length - 1 ? [0, 6, 6, 0] : 0}
              >
                <Cell fill={categoryPalette[i % categoryPalette.length]} />
              </Bar>
            ))}
          </BarChart>
        </ResponsiveContainer>

      {/* Category legend */}
      <ul className="flex flex-wrap gap-x-4 gap-y-1.5 text-[11.5px]">
        {costs.map((c, i) => (
          <li key={c.category} className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-[3px]" style={{ background: categoryPalette[i % categoryPalette.length] }} />
            <span className="capitalize text-muted">{c.category}</span>
            <span className="tabular text-foreground">{formatUsd(c.amount, 0)}</span>
          </li>
        ))}
      </ul>

      {/* Opex-vs-alpha gauge */}
      <div className="space-y-1">
        <div className="flex items-center justify-between text-[11.5px]">
          <span className="text-quiet">opex as share of trailing edge</span>
          <span className="tabular font-medium" style={{ color: ratioColor }}>
            {ratioPct}%
          </span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
          <div className="h-full rounded-full" style={{ width: `${Math.min(Math.max(ratioPct, 2), 100)}%`, background: ratioColor }} />
        </div>
      </div>
    </div>
  );
}

function CostTooltip({ active, payload, total }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; total: number }) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <TooltipShell>
      <div className="mb-1 text-[11.5px] font-medium text-foreground">Daily opex · {formatUsd(total, 0)}</div>
      <div className="space-y-0.5">
        {payload.map((p) => (
          <TooltipRow key={p.name} label={<span className="capitalize">{p.name}</span>} value={formatUsd(p.value, 0)} color={p.color} />
        ))}
      </div>
    </TooltipShell>
  );
}
