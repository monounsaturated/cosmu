# intent: test whether EQUITY short-term (1-week) cross-sectional reversal carries an exploitable edge after
# REALISTIC equity costs. Rank the universe by trailing 1-week return, LONG recent losers / SHORT recent winners,
# dollar-neutral, weekly hold. Route the reversal book + its disconfirmers (a momentum control = opposite sign, and
# a random-rank placebo) through the EXISTING deterministic scorer + cohort.promote_cohort BH-FDR (q=0.10), so the
# multiple-testing correction applies across the family. inputs: the OFFLINE equities daily JSON cache; outputs: a
# verdict. invariants: ZERO LLM calls; the scorer thresholds + promote_cohort q=0.10 are NOT changed (only routed);
# split-adjusted close-to-close returns (Yahoo v8 adjusts close for splits — verified); NO synthetic/zero fills (a
# week with a missing bar for a name simply drops that name that week); every grid variant recorded as a trial so
# deflation/FDR see the true count; fresh tempfile cohort store; REALISTIC equity fees stated below.
#
# EQUITY FEE MODEL (the point of the pivot — NOT crypto's 5bps-taker/50bps-impact): liquid US large-caps + ETFs at
# a commission-free retail broker. Per side: ~2 bps slippage (half-spread) + ~10 bps impact + ~1 bps commission
# = ~13 bps per side for single stocks; ETFs tighter (~6 bps/side). Cost applied to WEEKLY TURNOVER (a dollar-
# neutral weekly-rebalanced reversal book turns over ~fully each week on BOTH the long and short legs).

from __future__ import annotations

import json
import statistics
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.cohort import Candidate, promote_cohort
from cosmu.master.scorer import BacktestMetrics, cscv_pbo, score
from cosmu.master.trials import register_trial, trial_stats
from cosmu.master.verdict_log import durable_persist
from cosmu.research.equity_holdout import metrics_with_holdout, purged_embargoed_split

CACHE = Path("/Users/device/cosmu/.cosmu/market_data/equities")

# Per-SIDE cost in basis points (fraction): single stocks vs ETFs. 1 bp = 0.0001.
COST_STOCK_PER_SIDE = 0.0013   # 2 bps slip + 10 bps impact + 1 bp commission
COST_ETF_PER_SIDE = 0.0006     # tighter spreads/impact for liquid ETFs

# Broad-market + sector ETFs in the cache — excluded from the single-stock cross-section (heterogeneous instruments),
# but used to label cost tier and to run an ETF-universe robustness variant.
ETFS = {"SPY", "QQQ", "DIA", "IWM", "GLD", "TLT",
        "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"}


@dataclass
class Series:
    symbol: str
    ts: list[int]                # ms, ascending
    close: list[float]


def load_universe() -> dict[str, Series]:
    out: dict[str, Series] = {}
    for f in sorted(CACHE.glob("*_1d.json")):
        sym = f.name.replace("_1d.json", "")
        rows = json.loads(f.read_text())
        ts = [int(r["ts"]) for r in rows]
        close = [float(r["close"]) for r in rows]
        out[sym] = Series(sym, ts, close)
    return out


def _week_key(ms: int) -> tuple[int, int]:
    d = datetime.fromtimestamp(ms / 1000, UTC).date()
    iso = d.isocalendar()
    return (iso.year, iso.week)


def weekly_closes(s: Series) -> dict[tuple[int, int], float]:
    """Last close in each ISO week (the week's 'Friday' close). PIT: only past bars are used."""
    by_week: dict[tuple[int, int], tuple[int, float]] = {}
    for t, c in zip(s.ts, s.close, strict=True):
        wk = _week_key(t)
        if wk not in by_week or t >= by_week[wk][0]:
            by_week[wk] = (t, c)
    return {wk: v[1] for wk, v in by_week.items()}


@dataclass
class Panel:
    weeks: list[tuple[int, int]]                 # sorted week keys present for >= min_names names
    ret: dict[tuple[int, int], dict[str, float]] # week -> {symbol: that-week return}
    symbols: list[str]


def build_panel(universe: dict[str, Series], symbols: list[str], min_names: int = 10) -> Panel:
    """Weekly close-to-close returns per name. A name's return for week w needs both week w-1 and week w
    closes (consecutive ISO weeks). Missing → name dropped that week (NO synthetic fill)."""
    wclose = {sym: weekly_closes(universe[sym]) for sym in symbols}
    all_weeks = sorted({wk for sym in symbols for wk in wclose[sym]})
    idx = {wk: i for i, wk in enumerate(all_weeks)}
    ret: dict[tuple[int, int], dict[str, float]] = {wk: {} for wk in all_weeks}
    for sym in symbols:
        wc = wclose[sym]
        for wk, c in wc.items():
            i = idx[wk]
            if i == 0:
                continue
            prev_wk = all_weeks[i - 1]
            if prev_wk in wc and wc[prev_wk] > 0:
                ret[wk][sym] = c / wc[prev_wk] - 1.0
    weeks = [wk for wk in all_weeks if len(ret[wk]) >= min_names]
    return Panel(weeks, ret, symbols)


def _per_side_cost(sym: str) -> float:
    return COST_ETF_PER_SIDE if sym in ETFS else COST_STOCK_PER_SIDE


@dataclass
class StratResult:
    net: list[float]      # weekly NET portfolio returns
    gross: list[float]    # weekly GROSS portfolio returns
    turnover: list[float] # weekly two-sided turnover fraction
    weeks: list[tuple[int, int]]


def run_reversal(panel: Panel, *, sign: int, frac: float = 1 / 3, rng_seed: int | None = None) -> StratResult:
    """Dollar-neutral weekly cross-sectional strategy on trailing 1-week return.

    sign=+1  -> REVERSAL: LONG losers (bottom frac), SHORT winners (top frac).
    sign=-1  -> MOMENTUM control (the disconfirmer): LONG winners, SHORT losers.
    rng_seed set -> RANDOM-RANK placebo: rank by a deterministic pseudo-random key instead of past return.

    Signal at week w uses week w's return (already realized at w's close); the book is held over week w+1 and
    earns week w+1's return. No look-ahead: the ranking input is strictly prior to the return it harvests.
    Cost = per-name two-sided turnover * per-side cost (names enter/exit between consecutive weekly books)."""
    weeks = panel.weeks
    prev_weights: dict[str, float] = {}
    net: list[float] = []
    gross: list[float] = []
    turnover_series: list[float] = []
    used_weeks: list[tuple[int, int]] = []

    for i in range(len(weeks) - 1):
        w = weeks[i]
        w_next = weeks[i + 1]
        signal = panel.ret[w]                 # ranking input: each name's week-w return
        fwd = panel.ret[w_next]               # realized next-week return (the harvest)
        # only names present in BOTH the signal week and the forward week can be traded
        names = [s for s in signal if s in fwd]
        n = len(names)
        if n < 6:
            prev_weights = {}
            continue
        k = max(1, int(round(n * frac)))

        if rng_seed is not None:
            # deterministic placebo key per (week, symbol) — independent of price
            def key(sym: str) -> float:
                h = hash((rng_seed, w, sym))
                return (h % 1_000_003) / 1_000_003.0
            ranked = sorted(names, key=key)
        else:
            ranked = sorted(names, key=lambda s: signal[s])  # ascending: losers first

        losers = ranked[:k]
        winners = ranked[-k:]
        # reversal (sign=+1): long losers, short winners. momentum (sign=-1): the opposite.
        long_names = losers if sign == +1 else winners
        short_names = winners if sign == +1 else losers

        weights: dict[str, float] = {}
        for s in long_names:
            weights[s] = weights.get(s, 0.0) + 0.5 / len(long_names)
        for s in short_names:
            weights[s] = weights.get(s, 0.0) - 0.5 / len(short_names)

        gross_ret = sum(weights[s] * fwd[s] for s in weights)

        all_names = set(weights) | set(prev_weights)
        turnover = sum(abs(weights.get(s, 0.0) - prev_weights.get(s, 0.0)) for s in all_names)
        cost = sum(
            abs(weights.get(s, 0.0) - prev_weights.get(s, 0.0)) * _per_side_cost(s)
            for s in all_names
        )
        net_ret = gross_ret - cost

        gross.append(gross_ret)
        net.append(net_ret)
        turnover_series.append(turnover)
        used_weeks.append(w_next)
        prev_weights = weights

    return StratResult(net, gross, turnover_series, used_weeks)


def _max_drawdown(returns: list[float]) -> float:
    peak = 1.0
    equity = 1.0
    mdd = 0.0
    for r in returns:
        equity *= (1.0 + r)
        peak = max(peak, equity)
        if peak > 0:
            mdd = max(mdd, (peak - equity) / peak)
    return mdd


def metrics_from_returns(returns: list[float], *, trials_counted: int) -> BacktestMetrics:
    """WEEKLY NET return stream -> BacktestMetrics with a REAL purged+embargoed out-of-sample holdout.

    Gate-facing stats are computed on the IN-SAMPLE slice; `holdout_deflated_sharpe` is the genuine DSR of the
    held-out tail. Replaces the prior stub (holdout pinned to 0.0001, every stat on the full sample). require_beat
    _buy_and_hold stays OFF (a dollar-neutral book's benchmark is cash). embargo=4: a 1-week-formation reversal
    book carries no multi-week formation window, so a 4-week embargo comfortably clears the train/holdout boundary."""
    metrics, _split = metrics_with_holdout(
        returns, trials_counted=trials_counted, periods_per_year=52,
        holdout_frac=0.2, embargo=4, long_only=False)
    return metrics


def _folds_positive_pct(returns: list[float], k: int = 5) -> float:
    if len(returns) < k:
        return 0.0
    size = len(returns) // k
    pos = 0
    for f in range(k):
        seg = returns[f * size:(f + 1) * size] if f < k - 1 else returns[f * size:]
        if seg and statistics.fmean(seg) > 0:
            pos += 1
    return pos / k


@dataclass
class Verdict:
    universe: str
    n_weeks: int
    window: str
    candidates: list[dict] = field(default_factory=list)
    verdict: str = ""
    headline: str = ""
    notes: list[str] = field(default_factory=list)


def run(universe_name: str, symbols: list[str], fracs: list[float], *, persist: bool = False) -> Verdict:
    """`persist=True` records the cohort verdict to durable experiment-memory (gate_verdicts) via the REAL
    configured store (separate from the tempfile trial-ledger below) — main() sets it on real runs; tests leave
    it False so they never touch the durable store."""
    universe = load_universe()
    symbols = [s for s in symbols if s in universe]
    panel = build_panel(universe, symbols)
    if len(panel.weeks) < 60:
        return Verdict(universe_name, len(panel.weeks), "n/a", verdict="INSUFFICIENT-DATA",
                       headline="too few weeks")

    store = Store(Settings(database_url=f"sqlite:///{tempfile.mkdtemp(prefix='cosmu-eqrev-')}/g.sqlite3",
                           openrouter_api_key=None))
    gates = store.settings.gates
    # dollar-neutral: benchmark is cash, not a long basket — disable the beat-buy-and-hold hurdle for this run.
    gates = gates.model_copy(update={"require_beat_buy_and_hold": False})

    # ---- TRIAL LEDGER: register EVERY grid/param variant we evaluate, so deflation/FDR see the true count. ----
    # The grid: {reversal, momentum-control, random-placebo} x {each frac}. We pick the gate-best reversal frac as
    # the reversal representative, but every frac variant of every arm is one more registered trial.
    reversal_variants: list[tuple[float, StratResult, BacktestMetrics]] = []
    momentum_variants: list[tuple[float, StratResult, BacktestMetrics]] = []
    placebo_variants: list[tuple[float, StratResult, BacktestMetrics]] = []

    def eval_arm(sign: int, frac: float, seed: int | None, source: str, label: str):
        res = run_reversal(panel, sign=sign, frac=frac, rng_seed=seed)
        m = metrics_from_returns(res.net, trials_counted=1)
        register_trial(store, float(m.sharpe_per_obs), source=source, label=label)
        return res, m

    for frac in fracs:
        r, m = eval_arm(+1, frac, None, "equity_reversal", f"reversal:frac={frac:.2f}")
        reversal_variants.append((frac, r, m))
        r, m = eval_arm(-1, frac, None, "equity_reversal", f"momentum:frac={frac:.2f}")
        momentum_variants.append((frac, r, m))
        # several placebo seeds at the canonical frac to characterize the random-rank null
        if abs(frac - 1 / 3) < 1e-9:
            for seed in range(1, 6):
                r, m = eval_arm(+1, frac, seed, "equity_reversal", f"placebo:seed={seed}")
                placebo_variants.append((frac, r, m))

    trials = trial_stats(store)

    def gate_best(variants):
        best = None
        best_key = (-1, -1.0)
        for frac, res, m in variants:
            v = score(m, gates, trials=trials)
            key = (1 if v.passed else 0, float(v.deflated_sharpe_prob))
            if key > best_key or best is None:
                best_key = key
                best = (frac, res, m)
        return best

    rev_best = gate_best(reversal_variants)
    mom_best = gate_best(momentum_variants)
    plc_best = gate_best(placebo_variants) if placebo_variants else None

    # Real CSCV-PBO across the reversal arm's own frac-variant net streams (a legitimate config population).
    # Computed on the IN-SAMPLE slice ONLY (exclude the held-out tail) so the holdout stays untouched.
    rev_streams = [purged_embargoed_split(res.net, embargo=4).in_sample
                   for _, res, _ in reversal_variants if len(res.net) >= 20]
    rev_pbo = cscv_pbo(rev_streams) if len(rev_streams) >= 2 else 1.0

    # ---- Build the cohort of DISTINCT candidates and route through promote_cohort (BH-FDR q=0.10). ----
    candidates: list[Candidate] = []
    rows: list[dict] = []

    def make_candidate(name: str, best, pbo: float | None = None):
        frac, res, m = best
        # m already carries the in-sample folds_positive_pct AND the REAL purged+embargoed holdout DSR (from
        # metrics_from_returns -> metrics_with_holdout). The ONLY metric attached here is the real CSCV-PBO.
        if pbo is not None:
            m = m.model_copy(update={"pbo": Decimal(str(round(pbo, 6)))})
        var = statistics.pvariance(res.net) if len(res.net) > 1 else 1.0
        candidates.append(Candidate(id=name, metrics=m, net_profit=float(m.oos_return),
                                    source="equity_reversal", label=name, return_variance=var or 1.0))
        return frac, res, m

    rf, rres, rm = make_candidate("reversal", rev_best, pbo=rev_pbo)
    mf, mres, mm = make_candidate("momentum_control", mom_best)
    if plc_best:
        pf, pres, pm = make_candidate("random_placebo", plc_best)

    persist_spec = durable_persist(
        run_id=f"equity-reversal-{universe_name}",
        hypothesis=f"equity 1-week cross-sectional reversal carries a gate-clearing edge after realistic fees on {universe_name}",
        source="research/equity_reversal", data_source="equities-offline", universe=universe_name,
    ) if persist else None
    promotions = promote_cohort(store, candidates, gates, fdr_q=0.10, register=False, trials=trials, persist=persist_spec)
    by_id = {p.candidate_id: p for p in promotions}

    for c in candidates:
        # recover the matching result for reporting
        frac = {"reversal": rf, "momentum_control": mf,
                "random_placebo": (pf if plc_best else None)}.get(c.id)
        res = {"reversal": rres, "momentum_control": mres,
               "random_placebo": (pres if plc_best else None)}.get(c.id)
        m = c.metrics
        p = by_id[c.id]
        ann_turn = statistics.fmean(res.turnover) if res and res.turnover else 0.0
        gross_total = 1.0
        for g in (res.gross if res else []):
            gross_total *= (1.0 + g)
        gross_total -= 1.0
        cost_ratio = (float(m.oos_return) / gross_total) if gross_total else float("nan")
        rows.append({
            "name": c.id, "frac": frac, "net_total_return": round(float(m.oos_return), 5),
            "gross_total_return": round(gross_total, 5), "cost_ratio": round(cost_ratio, 3),
            "ann_sharpe": float(m.sharpe), "sharpe_per_obs": float(m.sharpe_per_obs),
            "deflated_sharpe_prob": round(float(p.deflated_sharpe_prob), 6),
            "pbo": float(m.pbo), "folds_positive": float(m.folds_positive_pct),
            "holdout_dsr": round(float(m.holdout_deflated_sharpe), 6),
            "n_weeks": m.num_trades, "max_dd": float(m.max_drawdown),
            "mean_weekly_turnover": round(ann_turn, 3),
            "win_rate": float(m.win_rate),
            "promoted": p.promoted, "survived_fdr": p.survived_fdr, "reasons": p.reasons,
        })

    w0 = panel.weeks[0]; w1 = panel.weeks[-1]
    window = f"{w0[0]}-W{w0[1]:02d} .. {w1[0]}-W{w1[1]:02d}"
    rev_promoted = by_id["reversal"].promoted
    if rev_promoted:
        verdict = "PASS"
        headline = f"equity 1-week reversal SURVIVED the cohort gate + BH-FDR (q=0.10) on {universe_name}"
    else:
        verdict = "FAIL"
        headline = (f"equity 1-week reversal did NOT survive the gate on {universe_name}; "
                    f"reversal DSR={by_id['reversal'].deflated_sharpe_prob:.3f}, "
                    f"reasons={by_id['reversal'].reasons}")
    return Verdict(universe_name, len(panel.weeks), window, candidates=rows,
                   verdict=verdict, headline=headline)


def _print(v: Verdict) -> None:
    print(f"\n=== EQUITY SHORT-TERM REVERSAL — {v.universe} — {v.verdict} ===")
    print(f"  weeks={v.n_weeks}  window={v.window}")
    print(f"  fee model: stocks {COST_STOCK_PER_SIDE*1e4:.0f} bps/side, ETFs {COST_ETF_PER_SIDE*1e4:.0f} bps/side, "
          f"applied to weekly turnover")
    for r in v.candidates:
        flag = "PROMOTED" if r["promoted"] else ("fdr-only" if r["survived_fdr"] else "stop")
        print(f"  [{flag:>9}] {r['name']:<17} frac={r['frac']} net={r['net_total_return']:+.4f} "
              f"gross={r['gross_total_return']:+.4f} cost_ratio={r['cost_ratio']} "
              f"annSR={r['ann_sharpe']:+.2f} SRobs={r['sharpe_per_obs']:+.4f} DSR={r['deflated_sharpe_prob']:.3f} "
              f"holdoutDSR={r['holdout_dsr']:+.4f} "
              f"pbo={r['pbo']:.2f} folds+={r['folds_positive']:.2f} maxDD={r['max_dd']:.3f} "
              f"turn={r['mean_weekly_turnover']:.2f} win={r['win_rate']:.2f} fdr={'Y' if r['survived_fdr'] else 'N'}")
        if r["reasons"]:
            print(f"               reasons: {', '.join(r['reasons'])}")
    print(f"  HEADLINE: {v.headline}")


def main() -> int:
    universe = load_universe()
    all_syms = sorted(universe)
    stocks = [s for s in all_syms if s not in ETFS]
    etfs = [s for s in all_syms if s in ETFS]
    fracs = [0.2, 0.25, 1 / 3, 0.5]

    for name, syms in [(f"SINGLE-STOCKS ({len(stocks)} names)", stocks),
                       (f"SECTOR+BROAD ETFs ({len(etfs)})", etfs),
                       (f"ALL NAMES ({len(all_syms)})", all_syms)]:
        v = run(name, syms, fracs, persist=True)
        _print(v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
