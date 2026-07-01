// module: pure, SERVER-SAFE derivations for the strategy sheet. Split out of strategy-sheet.tsx because that
// module is now a Client Component ("use client", for the tab-bar useState) — and a Client module's exports can't
// be CALLED from a Server Component. The standalone /strategy/[id] server page calls bestOosPct() directly, so the
// cross-boundary pure helpers live here (no "use client"), and both the sheet and the page import them from here.
//
// HONESTY: every helper reads only REAL fields off the contract and returns null/"" (→ "—") when a value is absent.

import type { Backtest, Execution } from "@cosmu/contracts-ts";
import type { Stage } from "@/lib/lifecycle";

// Total fees across the blotter — the ONE money aggregate honestly derivable from raw executions. Realized P&L
// is NOT (it needs FIFO matching of buys against closing sells). null when there are no fills → "—".
export function feeTotalFromTrades(trades: Execution[]): number | null {
  if (trades.length === 0) return null;
  return trades.reduce((acc, t) => acc + t.fee, 0);
}

// Stage derived honestly from the contract shape: fills → paper; backtests only → backtest; none → queued.
// We never claim "live"/"killed" — neither is recoverable here, so we never invent them.
export function deriveStage(trades: Execution[], backtests: Backtest[]): Stage {
  if (trades.length > 0) return "paper";
  if (backtests.length > 0) return "backtest";
  return "queued";
}

export function trackAgeDays(trades: Execution[]): number | null {
  if (trades.length < 2) return null;
  const ts = trades.map((t) => Date.parse(t.ts)).filter((n) => !Number.isNaN(n));
  if (ts.length < 2) return null;
  const days = Math.round((Math.max(...ts) - Math.min(...ts)) / 86_400_000);
  return days > 0 ? days : null;
}

// The representative backtest for the headline chips: prefer a passed one, else strongest by DSR.
export function headlineBacktest(backtests: Backtest[]): Backtest | null {
  return (
    backtests.find((bt) => bt.passed_gates) ??
    [...backtests].sort((a, b) => b.deflated_sharpe - a.deflated_sharpe)[0] ??
    null
  );
}

export function bestOosPct(backtests: Backtest[]): number | null {
  const passed = backtests.filter((b) => b.passed_gates);
  const pool = passed.length ? passed : backtests;
  if (!pool.length) return null;
  const v = Math.max(...pool.map((b) => b.oos_return)) * 100;
  return Number.isFinite(v) ? v : null;
}

// CAGR of the best OOS return — the cross-window comparable (a +6% over 3mo and +6% over 2yr are NOT the same
// edge). Reads the engine-computed oos_return_annualized; null when no backtest carries a window length.
export function bestOosAnnualizedPct(backtests: Backtest[]): number | null {
  const passed = backtests.filter((b) => b.passed_gates);
  const pool = passed.length ? passed : backtests;
  const anns = pool.map((b) => b.oos_return_annualized).filter((v): v is number => typeof v === "number");
  if (!anns.length) return null;
  const v = Math.max(...anns) * 100;
  return Number.isFinite(v) ? v : null;
}

// The OOS window in DAYS with a human span appended for long windows: "870d (~2.4yr)" / "240d (~8mo)" / "45d".
// null when the engine has no recorded window length.
export function formatOosWindow(days: number | null | undefined): string | null {
  if (!days || days <= 0) return null;
  const d = Math.round(days);
  if (d >= 360) return `${d}d (~${(d / 365).toFixed(1)}yr)`;
  if (d >= 60) return `${d}d (~${Math.round(d / 30)}mo)`;
  return `${d}d`;
}

// Every named feature a spec references (entry conditions + signal-exits + the funding leg) — the SAME evidence
// the engine's taxonomy derives provenance from. Tolerant of a partial/double-encoded spec.
export function referencedFeatures(spec: Record<string, unknown> | null | undefined): string[] {
  const names: string[] = [];
  const push = (n: unknown) => {
    if (typeof n === "string" && n && !names.includes(n)) names.push(n);
  };
  const featName = (cond: unknown) => {
    if (cond && typeof cond === "object") {
      const feature = (cond as Record<string, unknown>).feature;
      if (feature && typeof feature === "object") push((feature as Record<string, unknown>).name);
    }
  };
  if (!spec || typeof spec !== "object") return names;
  const entry = (spec as Record<string, unknown>).entry;
  if (Array.isArray(entry)) entry.forEach(featName);
  const exit = (spec as Record<string, unknown>).exit;
  if (exit && typeof exit === "object") {
    const sigExits = (exit as Record<string, unknown>).signal_exits;
    if (Array.isArray(sigExits)) sigExits.forEach(featName);
  }
  push((spec as Record<string, unknown>).funding_feature);
  return names;
}

// Holdout (out-of-sample) verdict off the contract's `holdout` bundle ({passed, deflated_sharpe}). Read defensively:
// holdout is a free-form Record on the contract, so coerce and fall back to nulls (→ "—").
export function holdoutVerdict(holdout: Record<string, unknown> | null | undefined): { passed: boolean | null; deflatedSharpe: number | null } {
  if (!holdout || typeof holdout !== "object") return { passed: null, deflatedSharpe: null };
  const passed = typeof holdout.passed === "boolean" ? holdout.passed : null;
  const ds = typeof holdout.deflated_sharpe === "number" && Number.isFinite(holdout.deflated_sharpe) ? holdout.deflated_sharpe : null;
  return { passed, deflatedSharpe: ds };
}
