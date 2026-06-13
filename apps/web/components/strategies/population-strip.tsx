// module: PopulationStrip — the lead-with-the-answer summary for the Strategies surface, as an Iris Bento
// `.kpi-grid` of `.kpi-box` cells. Before the ranked table, the operator sees the SHAPE of the population
// in one glance: how many Versions exist, how many cleared the Gate, and where the cohort sits across the
// lifecycle (Backtest → Paper → Live), plus how many were killed. Every number is COUNTED off the real
// leaderboard rows handed in — nothing fabricated. When there are no rows the page shows its honest empty
// state instead, so this strip only renders for a non-empty cohort.

import type { LeaderboardRow } from "@cosmu/contracts-ts";

type LifeStatus = "lab" | "screened" | "paper" | "live" | "killed";
function lifeStatusOf(status: string | null | undefined): LifeStatus {
  const s = (status ?? "").toLowerCase();
  if (s === "killed" || s === "dead" || s === "graveyard") return "killed";
  if (s === "live") return "live";
  if (s === "paper" || s === "forward_test" || s === "forward") return "paper";
  if (s === "screening" || s === "screened" || s === "validating" || s === "optimizing") return "screened";
  return "lab";
}

// A glanceable "cleared the bar" read — positive deflated Sharpe AND a contained PBO. Never the Gate's full
// deterministic verdict (that lives on the detail view); never overstates the count.
function clearedGate(r: LeaderboardRow): boolean {
  return r.deflated_sharpe > 0 && Number.isFinite(r.pbo) && r.pbo < 0.5;
}

function Box({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div className="kpi-box">
      <div className="kpi-label">{label}</div>
      <div className="kpi-val" style={color ? { color } : undefined}>{value}</div>
      {sub ? <div className="kpi-sub">{sub}</div> : null}
    </div>
  );
}

export function PopulationStrip({ rows }: { rows: LeaderboardRow[] }) {
  const total = rows.length;
  const counts: Record<LifeStatus, number> = { lab: 0, screened: 0, paper: 0, live: 0, killed: 0 };
  let cleared = 0;
  for (const r of rows) {
    counts[lifeStatusOf(r.status)] += 1;
    if (clearedGate(r)) cleared += 1;
  }
  const alive = total - counts.killed;
  const clearedPct = total > 0 ? Math.round((cleared / total) * 100) : 0;

  return (
    <div className="kpi-grid" style={{ gridTemplateColumns: "repeat(6,1fr)" }}>
      <Box label="Versions" value={String(total)} sub={`${alive} alive`} />
      <Box label="Cleared Gate" value={String(cleared)} sub={`${clearedPct}% of cohort`} color={cleared > 0 ? "var(--up)" : undefined} />
      <Box label="Backtest" value={String(counts.screened + counts.lab)} sub="historical" color="var(--iris-s)" />
      <Box label="Paper" value={String(counts.paper)} sub="live data" color="var(--info)" />
      <Box label="Live" value={String(counts.live)} sub="real capital" color={counts.live > 0 ? "var(--up)" : undefined} />
      <Box label="Killed" value={String(counts.killed)} sub="graveyard" color={counts.killed > 0 ? "var(--down)" : undefined} />
    </div>
  );
}
