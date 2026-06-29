// module: StrategySheet — the SHARED per-Version detail body, rendered identically inside the screener's
// right `SidePanel` and on the standalone `/strategy/[id]` bento page. It reproduces the v18 reference
// sheet (cosmu-final-v18.html `fundingCarryPanel`/`templatePanel`) as the SECTION STRUCTURE only — every
// number is bound to a REAL field off StrategyDetailResponse, never the mockup's synthetic arrays.
//
// HONESTY: every number is bound to a REAL field off StrategyDetailResponse. So:
//   • money-band → Value/Invested/P&L/Fees are the engine's MARKED forward money (latest scope='track'
//     snapshot − starting_capital, gated on a real paper fill) — the SAME source the leaderboard serves, so the
//     two surfaces agree. All render "—" until the track is marked; NEVER a fabricated loss from buy notionals.
//   • equity     → the engine's marked scope='track' equity trajectory (strategy.forward_equity); honest empty
//     when < 2 marked points. NEVER the cumulative-cash-flow-of-buys curve (which sloped to −100%).
//   • AI summary → summary_md only; honest "no summary yet" when null.
//   • gate chips + phase-comparison → the strongest backtest's measured DSR/PBO/Max-DD/OOS/trades; every cell
//     with no real source (Sharpe-in-paper, the whole Live column, …) is an explicit "—".
//   • building blocks → derived from the real spec (SpecBlocks); "—" where a block is absent.
//   • trades → the real Execution blotter (no fabricated per-fill P&L — an opening buy has $0 realized);
//     activity → real fills only, with the venue marked "(sim)" while paper.

import type { Backtest, Execution, LabSymbolRow, StrategyDetailResponse } from "@cosmu/contracts-ts";
import { MoneyBand, type MoneyBandData } from "./money-band";
import { AiSummary } from "./ai-summary";
import { CostBasisSelector } from "./cost-basis-selector";
import { EquityPanel } from "./equity-panel";
import { SpecBlocks } from "./spec-view";
import { RegistryBlocks } from "./registry-blocks";
import { StageControl, type Stage } from "./stage-control";
import { KpisBox } from "./kpis-box";
import { LifecycleTrace } from "./lifecycle-trace";
import { laneOf, provenanceOf, strategyKindOf } from "@/lib/provenance";
import { type Kind, KIND_LABEL, KIND_BADGE_CLASS } from "@/lib/lifecycle";
import { cn, fmtTz, formatUsd, formatVenue } from "@/lib/utils";

// ── Honest derivations off the real detail response ──

// Total fees across the blotter — the ONE money aggregate honestly derivable from raw executions. Realized P&L
// is NOT (it needs FIFO matching of buys against closing sells); it comes off the contract (strategy.realized_pnl,
// computed by the engine from positions), never from the fills here. null when there are no fills → "—".
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

// The OOS window in DAYS (the operator wants the day count, not just "OOS") with a human span appended for long
// windows: "870d (~2.4yr)" / "240d (~8mo)" / "45d". null when the engine has no recorded window length.
function formatOosWindow(days: number | null | undefined): string | null {
  if (!days || days <= 0) return null;
  const d = Math.round(days);
  if (d >= 360) return `${d}d (~${(d / 365).toFixed(1)}yr)`;
  if (d >= 60) return `${d}d (~${Math.round(d / 30)}mo)`;
  return `${d}d`;
}

// Gate reference (mirrors gate-chips): PBO must be under 0.50 to pass.
const PBO_CEILING = 0.5;

// Every named feature a spec references (entry conditions + signal-exits + the funding leg) — the SAME evidence
// the engine's taxonomy derives provenance from. Used so the sheet can flag an Astro (non-causal) strategy off
// the spec alone, without the leaderboard's `origin`. Tolerant of a partial/double-encoded spec.
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

// ── Holdout (out-of-sample) verdict off the contract's `holdout` bundle ({passed, deflated_sharpe}). The
// untouched, one-shot OOS check is the single most honest "did the edge hold up" signal — and today it is
// served but rendered NOWHERE on the sheet (the audit's "surface the computed-but-dropped evidence"). Read
// defensively: holdout is a free-form Record on the contract, so coerce and fall back to nulls (→ "—"). ──
export function holdoutVerdict(holdout: Record<string, unknown> | null | undefined): { passed: boolean | null; deflatedSharpe: number | null } {
  if (!holdout || typeof holdout !== "object") return { passed: null, deflatedSharpe: null };
  const passed = typeof holdout.passed === "boolean" ? holdout.passed : null;
  const ds = typeof holdout.deflated_sharpe === "number" && Number.isFinite(holdout.deflated_sharpe) ? holdout.deflated_sharpe : null;
  return { passed, deflatedSharpe: ds };
}

// ── Bar interval (timeframe) off the real spec — the cadence the backtest ran on. Tolerant of the few shapes a
// StrategySpec carries it in (horizon.bar_size · top-level timeframe/bar_size · universe.timeframe); null → "—".
function barIntervalOf(spec: Record<string, unknown> | null | undefined): string | null {
  if (!spec || typeof spec !== "object") return null;
  const horizon = spec.horizon;
  const fromHorizon = horizon && typeof horizon === "object" ? (horizon as Record<string, unknown>).bar_size : undefined;
  const universe = spec.universe;
  const fromUniverse = universe && typeof universe === "object" ? (universe as Record<string, unknown>).timeframe : undefined;
  const cand = [fromHorizon, spec.timeframe, spec.bar_size, fromUniverse].find((v) => typeof v === "string" && v);
  return typeof cand === "string" ? cand : null;
}

// ── Data provenance — the honest "what data did this run on", consolidated from REAL served fields so a result
// is never a black box: the instrument (symbol · venue) off the focused cell, the bar interval off the spec, the
// OOS window length, and the named data sources/features the spec keys off. Reads ONLY what the contract already
// carries; the per-cell fee schedule, exact date range, and bar provider are NOT yet on the contract (they land
// with the engine-side provenance item) — so they are honestly omitted rather than faked. ──
function DataProvenance({
  spec,
  cell,
  headlineBt
}: {
  spec: Record<string, unknown>;
  cell?: LabSymbolRow | null;
  headlineBt: Backtest | null;
}) {
  const features = referencedFeatures(spec);
  const interval = barIntervalOf(spec);
  const symbol = cell?.symbol ?? null;
  const venue = cell?.venue_id ?? null;
  const windowDays = cell?.oos_window_days ?? headlineBt?.oos_window_days ?? null;
  const instrument = symbol ? `${symbol}${venue ? ` · ${formatVenue(venue)}` : ""}` : null;

  return (
    <div className="psec">
      <div className="psec-title" data-tip="Exactly what data this backtest ran on — surfaced so a result is never a black box.">
        Data provenance
      </div>
      <div className="blocks">
        <div className="block-row">
          <span className="block-key">Instrument</span>
          <span className="block-val">{instrument ?? <span className="quiet">— focus a cell to pin the symbol · venue</span>}</span>
        </div>
        <div className="block-row">
          <span className="block-key">Bar interval</span>
          <span className="block-val">{interval ?? <span className="quiet">—</span>}</span>
        </div>
        <div className="block-row">
          <span className="block-key">OOS window</span>
          <span className="block-val">{formatOosWindow(windowDays) ?? <span className="quiet">—</span>}</span>
        </div>
        <div className="block-row">
          <span className="block-key" data-tip="The named point-in-time data sources / features this spec keys off — the inputs behind every signal.">Data sources</span>
          <span className="block-val">
            {features.length ? (
              <span style={{ display: "inline-flex", gap: 4, flexWrap: "wrap" }}>
                {features.map((f) => (
                  <span key={f} className="badge badge-iris" style={{ textTransform: "none" }}>{f}</span>
                ))}
              </span>
            ) : (
              <span className="quiet">price/TA only — no named alt-data feature</span>
            )}
          </span>
        </div>
      </div>
    </div>
  );
}

// ── Type & lane — the authoritative spec discriminators (strategy_kind / lane) + the provenance bucket + the
// strategy MODEL kind, as a compact badge row. strategy_kind + lane come straight off the real spec; provenance
// prefers the `origin` the row carries (passed from the screener) and otherwise self-derives Astro from the spec's
// referenced features; `modelKind` is the strategy_versions.kind discriminator (quant|llm) off the real contract. ──
function TypeLaneBadges({ spec, origin, modelKind }: { spec: Record<string, unknown>; origin?: string | null; modelKind?: Kind | null }) {
  const kind = strategyKindOf(spec);
  const lane = laneOf(spec);
  const prov = provenanceOf(origin, referencedFeatures(spec));
  // The MODEL kind is ORTHOGONAL to the spec's strategy_kind (indicator/event/regime) — it's how the strategy is
  // modelled (typed-spec quant vs agentic LLM). Subtle by design (every strategy is 'quant' today).
  const mk: Kind = modelKind === "llm" ? "llm" : "quant";
  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", margin: "2px 0 2px" }}>
      <span className={prov.badgeClass} data-tip={prov.tip}>{prov.label}</span>
      <span
        className={KIND_BADGE_CLASS[mk]}
        data-tip={mk === "llm" ? "Agentic / natural-language strategy (AgentSpec)." : "Typed StrategySpec routed through the deterministic Gate."}
      >
        {KIND_LABEL[mk]}
      </span>
      <span className={kind.badgeClass} data-tip={kind.tip}>{kind.label}</span>
      <span className={lane.badgeClass} data-tip={lane.tip}>{lane.label} lane</span>
    </div>
  );
}

// ── Focused-cell header — the clicked (asset × venue) the rest of the sheet's backtest column reads, plus this
// cell's BRUT gate verdict. Only rendered when a cell is focused (the sheet is per-cell). The brut verdict off
// backtest_symbols.verdict is one of: 'pass' (cleared this cell's OWN gate), 'watch' (gate-failed near-miss,
// routed to a zero-capital paper test), or a comma-joined kill-reason string. We map pass/watch to a clean
// label + tone and COLLAPSE every kill-reason to a plain "Fail" badge, with the full reason in the tooltip —
// never a wall of reason-codes in the header. null verdict (pre-migration / track-only) renders no badge. ──
function brutVerdict(verdict: string | null | undefined): { label: string; tone: "pass" | "watch" | "fail"; tip: string } | null {
  if (!verdict) return null;
  if (verdict === "pass") return { label: "Pass", tone: "pass", tip: "Cleared THIS cell's own gate (its own DSR/PBO + trade floor) — a brut, per-combo verdict, never pooled or sibling-compared." };
  if (verdict === "watch") return { label: "Watch", tone: "watch", tip: "A gate-failed near-miss — routed to a zero-real-capital paper test instead of being killed, so the forward record separates real edge from luck. NOT a gate pass." };
  return { label: "Fail", tone: "fail", tip: `Did not clear this cell's gate — ${verdict}.` };
}

// Brut-verdict tone → the shared badge tone classes in globals.css (the SAME .up/.dn/.gold palette the rest of
// the sheet uses): pass=green, watch=gold, fail=red. Each carries its own border, so no inline styling needed.
const VERDICT_BADGE_CLASS: Record<"pass" | "watch" | "fail", string> = {
  pass: "badge badge-up",
  watch: "badge badge-gold",
  fail: "badge badge-dn"
};

function CellHeader({ cell }: { cell: LabSymbolRow }) {
  const v = brutVerdict(cell.verdict);
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", margin: "2px 0 2px" }}>
      <span className="badge badge-muted" data-tip="One (asset × venue) cell — the granular truth the backtest column below reads, never a pooled mean.">
        {cell.symbol}
        {cell.venue_id ? <span className="quiet"> · {cell.venue_id}</span> : null}
      </span>
      {v ? (
        <span className={VERDICT_BADGE_CLASS[v.tone]} data-tip={v.tip}>
          {v.label}
        </span>
      ) : null}
    </div>
  );
}

// ── Phase comparison: Backtest OOS / Paper / Live side by side. Live is not on this contract → all "—".
// This table is now the SINGLE home for the gate metrics too (DSR / PBO / Max DD / OOS) — the separate
// "Gate metrics" chip row was removed, so every measured number lives in one place with its phase columns.
//
// PER-CELL TRUTH: when the sheet is focused on ONE (algo × asset × venue) cell (`cell` present, off the clicked
// triplet), the per-cell, STANDALONE numbers are preferred for Return / Max DD / Trades — these come from
// backtest_symbols (max_drawdown caps at a real ~22%), NEVER the pooled `backtests` aggregate (which for a
// brut-converted combo carries garbage, e.g. max_dd 5.05 → "505%"). DSR / PBO have no per-cell value on the
// contract, so they stay the algo's pooled gate verdict (a legitimate gate result, clearly the algo-level
// number — not a per-cell metric we could fake). ──
function PhaseComparison({
  headlineBt,
  paperPnl,
  trades,
  ageDays,
  bestOos,
  bestOosAnn,
  cell,
  holdout
}: {
  headlineBt: Backtest | null;
  paperPnl: number | null;
  trades: Execution[];
  ageDays: number | null;
  bestOos: number | null;
  bestOosAnn: number | null;
  cell?: LabSymbolRow | null;
  holdout: { passed: boolean | null; deflatedSharpe: number | null };
}) {
  // Prefer the per-cell standalone numbers when a cell is focused. return_pct / max_drawdown are FRACTIONS.
  const cellReturnPct = cell ? cell.return_pct * 100 : null;
  const cellAnnPct = cell && typeof cell.return_pct_annualized === "number" ? cell.return_pct_annualized * 100 : null;
  const cellMaxDdPct = cell ? cell.max_drawdown * 100 : null;
  const cellTrades = cell ? cell.trades : null;
  // The GATED deflated-Sharpe value is the PROBABILITY (deflated_sharpe_prob, the 0–1 number the 0.95 bar checks),
  // NOT the deflated-Sharpe ratio — comparing the ratio (which can exceed 1.0) to the 0.95 probability bar read as
  // a contradiction ("0.98 below 0.95"). Fall back to the binary verdict (≥/< 0.95) off passed_gates when the engine
  // could not recompute the probability (pre-migration / arm rows). DSR has no per-cell value (the algo's pooled
  // gate verdict), so this stays algo-level even when a cell is focused — mirroring PBO.
  const dsrProb = headlineBt?.deflated_sharpe_prob ?? null;
  const dsrPass = dsrProb !== null ? dsrProb >= 0.95 : !!headlineBt?.passed_gates;
  const dsrProbStr = dsrProb !== null ? dsrProb.toFixed(2) : headlineBt ? (headlineBt.passed_gates ? "≥0.95" : "<0.95") : "—";
  // Holdout = the untouched, ONE-SHOT out-of-sample check: did the edge survive data it never saw or fit to.
  // Served on the contract but rendered nowhere until now (the audit's "surface the dropped evidence"). The
  // ALGO's pooled verdict (no per-cell value), so it stays algo-level even when a cell is focused — like DSR/PBO.
  const holdoutStr = holdout.passed === null ? "—" : holdout.passed ? "Held" : "Failed";
  const holdoutTip = `The untouched, one-shot out-of-sample holdout — did the edge survive data it was never fit to (the most honest "is it real" check).${holdout.deflatedSharpe !== null ? ` Deflated-Sharpe ratio on the gated backtest: ${holdout.deflatedSharpe.toFixed(2)}.` : ""} The ALGO's pooled gate verdict, not a per-cell number.`;
  // `tip` defines each metric ONCE, in plain words (hover) — so a non-expert can read the table without a
  // glossary elsewhere. These replace the removed gate-metric chips' tooltips.
  const rows: { metric: string; tip?: string; bt: string; btTone?: string; paper: string; paperTone?: string; live: string }[] = [
    {
      metric: "Return",
      tip: cell
        ? "Standalone net-of-fee return on THIS asset at THIS venue — the granular truth, never a pooled mean."
        : "Total profit over the out-of-sample test window, after costs. Green = profitable.",
      bt:
        cellReturnPct !== null
          ? `${cellReturnPct >= 0 ? "+" : ""}${cellReturnPct.toFixed(1)}%`
          : bestOos !== null
            ? `${bestOos >= 0 ? "+" : ""}${bestOos.toFixed(1)}%`
            : "—",
      btTone:
        cellReturnPct !== null
          ? cellReturnPct >= 0 ? "up" : "dn"
          : bestOos !== null
            ? bestOos >= 0 ? "up" : "dn"
            : undefined,
      // Paper = the engine's marked $ P&L (realized + unrealized), neutral at exact $0 — never a cash-flow sum.
      paper:
        paperPnl === null
          ? "—"
          : paperPnl === 0
            ? formatUsd(0, 0)
            : `${paperPnl > 0 ? "+" : "-"}${formatUsd(Math.abs(paperPnl), 0)}`,
      paperTone: paperPnl === null || paperPnl === 0 ? undefined : paperPnl > 0 ? "up" : "dn",
      live: "—"
    },
    {
      metric: "Return (annualized)",
      tip: "CAGR — the Return compounded to a yearly rate, so edges measured over DIFFERENT window lengths are comparable (a +6% over 3 months and a +6% over 2 years are not the same edge). Short windows amplify — read it alongside Trades and the test window.",
      bt:
        cellAnnPct !== null
          ? `${cellAnnPct >= 0 ? "+" : ""}${cellAnnPct.toFixed(1)}%/yr`
          : bestOosAnn !== null
            ? `${bestOosAnn >= 0 ? "+" : ""}${bestOosAnn.toFixed(1)}%/yr`
            : "—",
      btTone:
        cellAnnPct !== null
          ? cellAnnPct >= 0 ? "up" : "dn"
          : bestOosAnn !== null
            ? bestOosAnn >= 0 ? "up" : "dn"
            : undefined,
      paper: "—",
      live: "—"
    },
    {
      metric: "DSR confidence",
      tip: `Deflated-Sharpe PROBABILITY — the 0-to-1 confidence the edge is real after discounting for how many variants were tried (so luck can't fake an edge). THIS is the number the Gate's 0.95 bar checks${headlineBt ? `; the raw deflated-Sharpe ratio (a separate ranking number, can exceed 1.0) is ${headlineBt.deflated_sharpe.toFixed(2)}` : ""}. The ALGO's pooled gate verdict, not a per-cell number.`,
      bt: dsrProbStr,
      btTone: headlineBt && dsrPass ? "up" : undefined,
      paper: "—",
      live: "—"
    },
    {
      metric: "Holdout (OOS)",
      tip: holdoutTip,
      bt: holdoutStr,
      btTone: holdout.passed === null ? undefined : holdout.passed ? "up" : "dn",
      paper: "—",
      live: "—"
    },
    {
      metric: "PBO",
      tip: "Probability of Backtest Overfitting — the chance the result is curve-fit noise, not a real edge. Lower is better; the Gate wants < 0.50. The ALGO's pooled gate verdict, not a per-cell number.",
      bt: headlineBt ? headlineBt.pbo.toFixed(2) : "—",
      btTone: headlineBt ? (headlineBt.pbo < PBO_CEILING ? "up" : "dn") : undefined,
      paper: "—",
      live: "—"
    },
    {
      metric: "Max DD",
      tip: cell
        ? "Maximum Drawdown on THIS cell — the worst peak-to-trough drop in equity, off this combo's own backtest. Smaller = less painful to hold."
        : "Maximum Drawdown — the worst peak-to-trough drop in equity over the test. Smaller = less painful to hold.",
      bt: cellMaxDdPct !== null ? `${cellMaxDdPct.toFixed(1)}%` : headlineBt ? `${(headlineBt.max_dd * 100).toFixed(1)}%` : "—",
      paper: "—",
      live: "—"
    },
    {
      metric: "Trades",
      tip: "How many round-trip trades the test took — too few and the result isn't statistically meaningful.",
      bt: cellTrades !== null ? String(cellTrades) : headlineBt ? String(headlineBt.num_trades) : "—",
      paper: trades.length ? String(trades.length) : "—",
      live: "—"
    },
    {
      metric: "Validation window",
      tip: cell
        ? "How many DAYS of validation data THIS cell was scored on — the held-out period tested AFTER the data the strategy was fitted on, measured on this asset's OWN history (never a sibling's longer window). It's the denominator behind the annualized return. — = window not yet recorded."
        : "How many DAYS of validation data the backtest was scored on — the held-out period tested AFTER the data the strategy was fitted on. Longer = more trustworthy, and it's the denominator behind the annualized return. — = window not yet recorded.",
      // Per-cell truth when a cell is focused: THIS cell's own validation window (off backtest_symbols.oos_window_days),
      // never the parent backtest's shared (longest-cell) window. Falls back to the headline backtest's window.
      bt: formatOosWindow(cell?.oos_window_days ?? headlineBt?.oos_window_days) ?? "—",
      paper: ageDays !== null ? `${ageDays}d` : "—",
      live: "—"
    }
  ];
  return (
    <div className="psec">
      <div className="psec-title">Phase comparison</div>
      <div className="tbl-scroll">
        <table className="phase-tbl">
          <thead>
            <tr>
              <th>Metric</th>
              <th>Backtest OOS</th>
              <th className="col-paper">Paper</th>
              <th className="col-live">Live</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.metric}>
                <td data-tip={r.tip}>{r.metric}</td>
                <td className={r.btTone ?? ""}>{r.bt}</td>
                <td className={cn("col-paper", r.paperTone)}>{r.paper}</td>
                <td className="col-live">{r.live}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// "Jun 09 14:22" parts, split so the time reads quiet. Rendered in the operator's timezone (fmtTz) so a
// server-rendered blotter shows wall-clock Paris time, not the Vercel server's UTC.
function dateTimeParts(ts: string): { date: string; time: string } | null {
  if (Number.isNaN(new Date(ts).getTime())) return null;
  return {
    date: fmtTz(ts, { month: "short", day: "2-digit" }),
    time: fmtTz(ts, { hour: "2-digit", minute: "2-digit", hour12: false })
  };
}

// ── Recent trades — the real Execution blotter (newest first), in the bento `.mini-tbl`. No per-fill P&L
// column: an opening BUY has $0 realized P&L by definition, and realized P&L for a close needs FIFO matching
// the raw blotter can't do — so we show the real Date/Side/Price/Qty/Fee and never a fabricated per-fill number. ──
function RecentTrades({ trades }: { trades: Execution[] }) {
  if (trades.length === 0) {
    return (
      <div className="psec" id="sheet-trades">
        <div className="psec-title">Recent trades</div>
        <p className="quiet" style={{ fontSize: 11 }}>No fills yet — trades appear here as this track trades on live data. Nothing is fabricated.</p>
      </div>
    );
  }
  const ordered = [...trades].sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts));
  return (
    <div className="psec" id="sheet-trades">
      <div className="psec-title">Recent trades · {trades.length}</div>
      <div className="tbl-scroll">
        <table className="mini-tbl">
          <thead>
            <tr>
              <th>Date · time</th>
              <th>Side</th>
              <th className="r">Price</th>
              <th className="r">Qty</th>
              <th className="r">Fee</th>
            </tr>
          </thead>
          <tbody>
            {ordered.map((t) => {
              const dt = dateTimeParts(t.ts);
              return (
                <tr key={t.id}>
                  <td>
                    {dt ? (
                      <>
                        {dt.date} <span className="quiet">{dt.time}</span>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className={t.side === "buy" ? "side-buy" : "side-sell"}>{t.side === "buy" ? "Buy" : "Sell"}</td>
                  <td className="r tab">{formatUsd(t.price, 2)}</td>
                  <td className="r tab">{t.qty}</td>
                  <td className="r tab muted">{formatUsd(t.fee, 2)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Activity — derived from real fills only (entered/closed events), newest first. Honest empty otherwise.
// No per-fill P&L (an opening buy realizes nothing). While paper, the venue is marked "(sim)": the fill is
// SIMULATED against that venue's real prices/fees — no real order was placed. ──
function Activity({ trades, stage }: { trades: Execution[]; stage: Stage }) {
  const ordered = [...trades].sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts)).slice(0, 8);
  const sim = stage === "paper";
  return (
    <div className="psec" id="sheet-activity">
      <div className="psec-title">Activity</div>
      {sim && ordered.length > 0 ? (
        <p className="quiet" style={{ fontSize: 11, marginBottom: 6 }}>
          Simulated paper fills — priced against the venue&apos;s real fees, but no real order is placed.
        </p>
      ) : null}
      <div className="act-list">
        {ordered.length === 0 ? (
          <div className="act-row">
            <span className="act-time">—</span>
            <span className="act-text quiet">No activity yet — events appear here as this track fills.</span>
          </div>
        ) : (
          ordered.map((t, i) => {
            const dt = dateTimeParts(t.ts);
            return (
              <div key={t.id} className={i === 0 ? "act-row cur-ev" : "act-row"}>
                <span className="act-time">{dt ? `${dt.date}, ${dt.time}` : "—"}</span>
                <span className="act-text">
                  <strong>{t.side === "buy" ? "Bought" : "Sold"}</strong> {t.qty} @ {formatUsd(t.price, 2)}
                  {t.venue ? (
                    <span className="quiet">
                      {" "}
                      · {t.venue}
                      {sim ? " (sim)" : ""}
                    </span>
                  ) : null}
                </span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

// ── The full sheet body — used by the SidePanel and the standalone page. ──
// `cell` (optional): the clicked (algo × asset × venue) backtest_symbols cell. When present, the BACKTEST-phase
// headline numbers (Return / Max DD / Trades + the equity box) read this cell's STANDALONE truth instead of the
// pooled `backtests` aggregate — the fix for brut-converted combos whose pooled record carries garbage (505% DD,
// empty equity_curve). The forward money band stays per-track marked money (already honest, not pooled).
export function StrategySheet({ strategy, stageOverride, origin, cell }: { strategy: StrategyDetailResponse; stageOverride?: Stage; origin?: string | null; cell?: LabSymbolRow | null }) {
  // The contract declares trades/backtests as non-null, but the engine can omit them (null) — normalize to
  // empty arrays HERE so every downstream `.length`/spread/`.some` is safe and a partial response can't
  // white-screen the sheet (the error boundary is the net, this is the guard).
  const trades = strategy.trades ?? [];
  const backtests = strategy.backtests ?? [];
  const totalFee = feeTotalFromTrades(trades);
  // Prefer the engine's canonical stage (passed from the screener row) so the sheet badge never disagrees
  // with the table; fall back to the contract-shape heuristic for the standalone /strategy/[id] page.
  const stage = stageOverride ?? deriveStage(trades, backtests);
  const ageDays = trackAgeDays(trades);
  const headlineBt = headlineBacktest(backtests);
  const bestOos = bestOosPct(backtests);
  const bestOosAnn = bestOosAnnualizedPct(backtests);
  // The one-shot out-of-sample holdout verdict + its DSR ratio, off the contract's `holdout` bundle — surfaced
  // as a Phase-comparison row (was served-but-unrendered evidence).
  const holdout = holdoutVerdict(strategy.holdout);
  // Forward P&L = the engine's MARKED total (realized + unrealized = value − starting_capital), off the
  // scope='track' snapshot — NEVER the cash-flow sum of opening buys. null until the track is marked.
  const paperPnl = strategy.pnl_usd ?? null;
  // The strategy's own plain-language rationale off the real spec — the honest "what this does" fallback when
  // no operator summary is written yet (documented strategies carry a rich rationale describing the mechanism).
  const specRationale =
    strategy.spec && typeof (strategy.spec as Record<string, unknown>).rationale === "string"
      ? ((strategy.spec as Record<string, string>).rationale)
      : null;

  // The money band binds to the engine's REAL marked money (same source as the leaderboard), never the fills'
  // cash flow. P&L = realized + unrealized (= value − starting_capital), so a flat fully-invested track reads
  // $0.00 — not −100%. pnlPct is % of starting capital (matches the leaderboard's pnl_pct denominator).
  const money: MoneyBandData = {
    valueUsd: strategy.value_usd ?? null,
    investedUsd: strategy.invested_usd ?? null,
    pnlUsd: strategy.pnl_usd ?? null,
    pnlPct:
      strategy.pnl_usd != null && strategy.starting_capital
        ? (strategy.pnl_usd / strategy.starting_capital) * 100
        : null,
    feesUsd: totalFee,
    // When un-marked the P&L cell is "—"; its sub-line then matches the Value/Invested cells ("not marked yet")
    // rather than implying a realized+unrealized figure exists.
    pnlSub:
      strategy.pnl_usd == null
        ? "not marked yet"
        : ageDays !== null
          ? `${ageDays}d · realized + unrealized`
          : "realized + unrealized",
    feesSub: stage === "paper" ? "off simulated fills" : "off real fills"
  };

  return (
    <>
      <StageControl
        stage={stage}
        ageDays={ageDays}
        strategyName={strategy.name}
        versionId={strategy.version_id}
        goLiveEligible={stage === "paper" || Boolean(headlineBt?.passed_gates)}
      />

      <TypeLaneBadges spec={(strategy.spec ?? {}) as Record<string, unknown>} origin={origin} modelKind={strategy.kind} />

      {/* Per-TYPE KPIs box — so the human reads what disposed this strategy without opening code. Quant → the Gate
          KPIs (DSR / PBO / holdout / OOS); LLM/Conviction → the guardrails + thesis + disconfirmer + max-loss the
          human signs off (human-armed only). Defaults to the Gate box (every strategy is quant today). */}
      <KpisBox kind={strategy.kind} spec={(strategy.spec ?? {}) as Record<string, unknown>} backtest={headlineBt} holdout={holdout} />

      {/* When the sheet is focused on ONE (asset × venue) cell, surface that cell's symbol/venue + brut gate
          verdict up top — so the reader knows WHICH combo the backtest column below is reporting. */}
      {cell ? <CellHeader cell={cell} /> : null}

      <MoneyBand data={money} />

      {/* ONE equity box with a phase toggle (v18 "Equity — Live" design): Backtest = the gross/net
          curve from GET /explorer/{id}; Paper/Live = the engine's MARKED scope='track' trajectory
          (forward_equity), shown only when ≥ 2 real snapshots exist. Defaults to the most-advanced
          phase with data, so the operator sees the live read first and can toggle back to the edge. */}
      <EquityPanel versionId={strategy.version_id ?? null} forwardCurve={strategy.forward_equity ?? []} stage={stage} cell={cell ?? null} />

      <AiSummary
        summaryMd={strategy.summary_md}
        stale={strategy.summary_stale}
        updatedAt={strategy.summary_updated_at}
        specRationale={specRationale}
        stage={stage}
        gate={
          headlineBt
            ? {
                passedGates: headlineBt.passed_gates,
                deflatedSharpe: headlineBt.deflated_sharpe,
                deflatedSharpeProb: headlineBt.deflated_sharpe_prob ?? null,
                pbo: headlineBt.pbo,
                // Return + Max DD read the PER-CELL standalone truth when a cell is focused — the SAME source the
                // Phase-comparison table uses — so the "why" prose and the table never disagree on the drawdown /
                // return. DSR-prob + PBO have no per-cell value, so they stay the algo's pooled gate verdict.
                oosReturn: cell ? cell.return_pct : headlineBt.oos_return,
                oosWindowDays: cell?.oos_window_days ?? headlineBt.oos_window_days,
                maxDd: cell ? cell.max_drawdown : headlineBt.max_dd
              }
            : null
        }
      />

      <PhaseComparison headlineBt={headlineBt} paperPnl={paperPnl} trades={trades} ageDays={ageDays} bestOos={bestOos} bestOosAnn={bestOosAnn} cell={cell} holdout={holdout} />

      {/* Data provenance — the honest "what data did this run on" (instrument · interval · OOS window · sources),
          off real served fields so a result is never a black box. */}
      <DataProvenance spec={(strategy.spec ?? {}) as Record<string, unknown>} cell={cell ?? null} headlineBt={headlineBt} />

      {/* Composed lifecycle verdict (backtest → paper → forward-ready → live-ready) + the audit trace, off the
          engine's GET /readiness/{version_id}. Advisory — it never arms money. */}
      {strategy.version_id ? <LifecycleTrace versionId={strategy.version_id} /> : null}

      <CostBasisSelector versionId={strategy.version_id} />

      <div className="psec">
        <div className="psec-title">Building blocks</div>
        <SpecBlocks spec={strategy.spec} />
        <RegistryBlocks versionId={strategy.version_id} />
      </div>

      <RecentTrades trades={trades} />

      <Activity trades={trades} stage={stage} />
    </>
  );
}
