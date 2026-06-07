// module: PopulationStrip — the lead-with-the-answer summary for the Strategies surface. Before the
// ranked table, the operator should see the SHAPE of the population in one glance: how many Versions
// exist, how many cleared the Gate, and where the cohort sits across the lifecycle (Backtest →
// Simulation → Live), plus how many were killed. Every number is COUNTED off the real leaderboard rows
// handed in — nothing fabricated. When there are no rows the page shows its honest empty state instead,
// so this strip only renders for a non-empty cohort.

import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { cn } from "@/lib/utils";

// Map a raw engine status onto the lifecycle bucket — kept in lockstep with strategies-table.tsx so the
// strip and the per-row Status badge always agree on what "Live" / "Killed" mean.
type LifeStatus = "lab" | "screened" | "forward" | "live" | "killed";
function lifeStatusOf(status: string | null | undefined): LifeStatus {
  const s = (status ?? "").toLowerCase();
  if (s === "killed" || s === "dead" || s === "graveyard") return "killed";
  if (s === "live") return "live";
  if (s === "forward_test" || s === "forward" || s === "paper") return "forward";
  if (s === "screening" || s === "screened" || s === "validating" || s === "optimizing") return "screened";
  return "lab";
}

// A passed-Gate Version is one with a positive deflated Sharpe AND a contained PBO — the two scalars the
// ranked table already exposes. This is a glanceable read of "how many cleared the bar", not the Gate's
// full deterministic verdict (that lives on the detail view); it never overstates the count.
function clearedGate(r: LeaderboardRow): boolean {
  return r.deflated_sharpe > 0 && Number.isFinite(r.pbo) && r.pbo < 0.5;
}

type Tone = "iris" | "up" | "info" | "down" | "muted";

function Cell({
  label,
  value,
  sub,
  tone = "muted",
  emphasis
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: Tone;
  emphasis?: boolean;
}) {
  const valueColor: Record<Tone, string> = {
    iris: "text-foreground",
    up: "text-up",
    info: "text-info",
    down: "text-down",
    muted: "text-foreground"
  };
  const bar: Record<Tone, string> = {
    iris: "bg-iris",
    up: "bg-up",
    info: "bg-info",
    down: "bg-down",
    muted: "bg-border-strong"
  };
  return (
    <div className="relative flex flex-col gap-1.5 pl-3.5">
      <span className={cn("absolute left-0 top-0.5 bottom-0.5 w-0.5 rounded-full", bar[tone])} aria-hidden />
      <span className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-quiet">{label}</span>
      <span className={cn("text-[22px] font-semibold leading-none tabular tracking-tight", valueColor[tone], emphasis && "text-[26px]")}>
        {value}
      </span>
      {sub ? <span className="text-[11px] leading-none text-quiet">{sub}</span> : null}
    </div>
  );
}

export function PopulationStrip({ rows }: { rows: LeaderboardRow[] }) {
  const total = rows.length;
  const counts: Record<LifeStatus, number> = { lab: 0, screened: 0, forward: 0, live: 0, killed: 0 };
  let cleared = 0;
  for (const r of rows) {
    counts[lifeStatusOf(r.status)] += 1;
    if (clearedGate(r)) cleared += 1;
  }
  const alive = total - counts.killed;
  const clearedPct = total > 0 ? Math.round((cleared / total) * 100) : 0;

  return (
    <div className="card-grad grid grid-cols-2 gap-x-5 gap-y-5 rounded-lg border border-border/70 p-5 shadow-card sm:grid-cols-3 lg:grid-cols-6">
      <Cell label="Versions" value={String(total)} sub={`${alive} alive`} emphasis />
      <Cell label="Cleared Gate" value={String(cleared)} sub={`${clearedPct}% of cohort`} tone={cleared > 0 ? "up" : "muted"} />
      <Cell label="Backtest" value={String(counts.screened + counts.lab)} sub="historical" tone="iris" />
      <Cell label="Simulation" value={String(counts.forward)} sub="live data" tone="info" />
      <Cell label="Live" value={String(counts.live)} sub="real capital" tone={counts.live > 0 ? "up" : "muted"} />
      <Cell label="Killed" value={String(counts.killed)} sub="graveyard" tone={counts.killed > 0 ? "down" : "muted"} />
    </div>
  );
}
