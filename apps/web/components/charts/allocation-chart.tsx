// module: AllocationChart — donut of pooled-wallet weight per strategy sleeve. Deliverable #2.
// Tooltip shows weight % + capital; an on-theme legend lists each sleeve; honest empty state
// when nothing is funded. Themed to the OKLch tokens (categoryPalette). Client component.
"use client";

import { PieChart as PieIcon } from "lucide-react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import type { Allocation } from "@cosmu/contracts-ts";
import { categoryPalette, ChartEmpty, TooltipRow, TooltipShell, useReducedMotion } from "./chart-kit";
import { formatUsd } from "@/lib/utils";

type Slice = Allocation & { color: string };

export function AllocationChart({ allocation, height = 240 }: { allocation: Allocation[]; height?: number }) {
  const reduced = useReducedMotion();

  if (!allocation || allocation.length === 0) {
    return (
      <ChartEmpty
        icon={<PieIcon className="size-5" />}
        title="No funded sleeves yet"
        hint="Allocation appears once a strategy clears the gates and receives a capital sleeve."
        height={height}
      />
    );
  }

  const slices: Slice[] = allocation.map((a, i) => ({ ...a, color: categoryPalette[i % categoryPalette.length] }));

  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-center">
      <div className="w-full max-w-[240px]">
        <ResponsiveContainer width="100%" height={height} minWidth={0} debounce={50}>
          <PieChart>
            <Pie
              data={slices}
              dataKey="weight"
              nameKey="name"
              innerRadius="58%"
              outerRadius="92%"
              paddingAngle={2}
              stroke="var(--color-surface)"
              strokeWidth={2}
              isAnimationActive={!reduced}
            >
              {slices.map((s) => (
                <Cell key={s.strategy_id} fill={s.color} />
              ))}
            </Pie>
            <Tooltip content={<AllocationTooltip />} />
          </PieChart>
        </ResponsiveContainer>
      </div>

      <ul className="w-full flex-1 space-y-1.5">
        {slices.map((s) => (
          <li key={s.strategy_id} className="flex items-center justify-between gap-3 text-[12.5px]">
            <span className="flex min-w-0 items-center gap-2">
              <span className="size-2.5 shrink-0 rounded-[3px]" style={{ background: s.color }} />
              <span className="min-w-0 truncate text-foreground">{s.name}</span>
            </span>
            <span className="flex shrink-0 items-center gap-3">
              <span className="tabular text-muted">{formatUsd(s.capital, 0)}</span>
              <span className="tabular font-medium text-foreground">{(s.weight * 100).toFixed(0)}%</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

type AllocTooltipItem = { payload: Slice };
function AllocationTooltip({ active, payload }: { active?: boolean; payload?: AllocTooltipItem[] }) {
  if (!active || !payload || payload.length === 0) return null;
  const s = payload[0].payload;
  return (
    <TooltipShell>
      <div className="mb-1 max-w-[180px] truncate text-[11.5px] font-medium text-foreground">{s.name}</div>
      <div className="space-y-0.5">
        <TooltipRow label="Weight" value={`${(s.weight * 100).toFixed(1)}%`} color={s.color} />
        <TooltipRow label="Capital" value={formatUsd(s.capital, 0)} />
        {s.venue ? <TooltipRow label="Venue" value={s.venue} /> : null}
      </div>
    </TooltipShell>
  );
}
