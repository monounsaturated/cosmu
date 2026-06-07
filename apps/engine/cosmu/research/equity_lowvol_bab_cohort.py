# intent: test the documented LOW-VOLATILITY / BETTING-AGAINST-BETA (BAB) anomaly on REAL split-adjusted equity
# daily data — rank the universe by trailing realized volatility (and beta to SPY), LONG the lowest-vol/low-beta
# tranche, optionally a MARKET-NEUTRAL long-low / short-high book — at MONTHLY rebalance (very low turnover, so
# realistic costs barely matter). Route the books + disconfirmers (random-rank placebo; a high-vol/anti control)
# through the EXISTING deterministic scorer + cohort.promote_cohort BH-FDR (q=0.10). inputs: the OFFLINE equities
# daily JSON cache; outputs: a printed cohort verdict. invariants: ZERO LLM calls; the scorer thresholds +
# promote_cohort q=0.10 are NOT changed (only routed); split-adjusted close-to-close returns (Yahoo v8 adjusts
# close for splits — verified); NO synthetic/zero fills (a month with insufficient history for a name simply drops
# that name that month); every grid/param variant recorded as a trial so deflation/FDR see the true count; fresh
# tempfile cohort store; REALISTIC equity fees stated below; NO look-ahead (vol/beta computed strictly from bars
# PRIOR to the held month).
#
# EQUITY FEE MODEL (commission-free retail broker; NOT crypto costs): per side ~2 bps slippage + ~10 bps impact
# + ~1 bp commission = ~13 bps/side for single stocks; ETFs tighter (~6 bps/side). Cost is applied to the
# MONTHLY two-sided turnover. Because the low-vol ranking is sticky month-to-month, turnover is low → cost is
# a small haircut; we report turnover so the reader can see it.
#
# SURVIVORSHIP CAVEAT (stated, not hidden): the single-name universe is TODAY's survivors, so LONG-ONLY absolute
# returns are upward-biased / uninvestable. The HONEST constructions here are (a) MARKET-NEUTRAL long-low/short-high
# (the spread; survivorship hits both legs and largely cancels) and (b) the LONG tranche measured RELATIVE TO the
# equal-weight basket (the alpha vs an equally-survivorship-biased benchmark). The long-only absolute book is shown
# only flagged as biased.

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
from cosmu.research.equity_holdout import metrics_with_holdout, purged_embargoed_split

CACHE = Path("/Users/device/cosmu/.cosmu/market_data/equities")

# Per-SIDE cost (fraction). 1 bp = 0.0001.
COST_STOCK_PER_SIDE = 0.0013   # 2 bps slip + 10 bps impact + 1 bp commission
COST_ETF_PER_SIDE = 0.0006     # tighter spreads/impact for liquid ETFs

ETFS = {"SPY", "QQQ", "DIA", "IWM", "GLD", "TLT",
        "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"}

# Trailing window (trading days) over which realized vol / beta are estimated, strictly before the held month.
LOOKBACK_DAYS = 120
# Minimum daily bars required in the lookback for a name to be ranked that month (NO synthetic fill).
MIN_LOOKBACK_OBS = 90


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


def _month_key(ms: int) -> tuple[int, int]:
    d = datetime.fromtimestamp(ms / 1000, UTC).date()
    return (d.year, d.month)


@dataclass
class DailyPanel:
    """Aligned daily close-to-close returns on the common trading-day grid. ret[day][sym] = that-day return.
    days are sorted ascending. month_of[day] = (year, month). month_ret[month][sym] = compounded monthly
    NET-of-nothing return of that name over the month (precomputed once — no repeated O(days) scans)."""
    days: list[int]                              # sorted unique trading-day timestamps (ms)
    ret: dict[int, dict[str, float]]             # day -> {sym: daily return}
    month_of: dict[int, tuple[int, int]]
    months: list[tuple[int, int]]                # sorted unique months present
    symbols: list[str]
    month_ret: dict[tuple[int, int], dict[str, float]]  # month -> {sym: compounded monthly return}


def build_daily_panel(universe: dict[str, Series], symbols: list[str], market: str = "SPY") -> DailyPanel:
    """Daily close-to-close returns per name on the UNION trading-day grid. A name's return on day d needs a
    close on day d and on the immediately-preceding day on which THAT name traded (consecutive own-bars).
    Missing → name dropped that day (NO synthetic fill). The market symbol is included so beta can be computed."""
    syms = list(dict.fromkeys(symbols + ([market] if market not in symbols else [])))
    # per-name day->close
    closes: dict[str, dict[int, float]] = {}
    for sym in syms:
        if sym not in universe:
            continue
        s = universe[sym]
        closes[sym] = dict(zip(s.ts, s.close, strict=True))
    all_days = sorted({d for sym in closes for d in closes[sym]})
    # per-name consecutive-own-bar returns keyed by the LATER day
    ret: dict[int, dict[str, float]] = {d: {} for d in all_days}
    for sym, cmap in closes.items():
        own_days = sorted(cmap)
        for i in range(1, len(own_days)):
            d_prev, d = own_days[i - 1], own_days[i]
            c_prev, c = cmap[d_prev], cmap[d]
            if c_prev > 0:
                ret[d][sym] = c / c_prev - 1.0
    month_of = {d: _month_key(d) for d in all_days}
    months = sorted({month_of[d] for d in all_days})
    # precompute compounded monthly returns per name (single pass over days)
    month_ret: dict[tuple[int, int], dict[str, float]] = {m: {} for m in months}
    factor: dict[tuple[int, int], dict[str, float]] = {m: {} for m in months}
    for d in all_days:
        m = month_of[d]
        fm = factor[m]
        for sym, r in ret[d].items():
            fm[sym] = fm.get(sym, 1.0) * (1.0 + r)
    for m in months:
        month_ret[m] = {sym: f - 1.0 for sym, f in factor[m].items()}
    return DailyPanel(all_days, ret, month_of, months, [s for s in symbols if s in closes], month_ret)


@dataclass
class StratResult:
    net: list[float]        # monthly NET portfolio returns
    gross: list[float]      # monthly GROSS portfolio returns
    turnover: list[float]   # monthly two-sided turnover fraction
    months: list[tuple[int, int]]
    bench: list[float]      # equal-weight benchmark return, same months (for relative alpha)


def _per_side_cost(sym: str) -> float:
    return COST_ETF_PER_SIDE if sym in ETFS else COST_STOCK_PER_SIDE


def _trailing_stats(
    panel: DailyPanel, day_idx: int, sym: str, market: str
) -> tuple[float, float, int]:
    """Realized vol (std of daily returns) and beta-to-market over the LOOKBACK_DAYS trading days strictly
    BEFORE day_idx, using only this name's available daily returns in that window. Returns (vol, beta, n_obs).
    PIT: window is days[day_idx-LOOKBACK_DAYS : day_idx] — all strictly prior to the rebalance day."""
    lo = max(0, day_idx - LOOKBACK_DAYS)
    name_r: list[float] = []
    mkt_r: list[float] = []
    name_only: list[float] = []
    for j in range(lo, day_idx):
        d = panel.days[j]
        r = panel.ret[d].get(sym)
        if r is None:
            continue
        name_only.append(r)
        m = panel.ret[d].get(market)
        if m is not None:
            name_r.append(r)
            mkt_r.append(m)
    n = len(name_only)
    if n < MIN_LOOKBACK_OBS:
        return float("nan"), float("nan"), n
    vol = statistics.pstdev(name_only)
    # beta = cov(name, mkt) / var(mkt) over the paired observations
    beta = float("nan")
    if len(mkt_r) >= MIN_LOOKBACK_OBS:
        mvar = statistics.pvariance(mkt_r)
        if mvar > 0:
            mbar = statistics.fmean(mkt_r)
            nbar = statistics.fmean(name_r)
            cov = statistics.fmean([(a - nbar) * (b - mbar) for a, b in zip(name_r, mkt_r, strict=True)])
            beta = cov / mvar
    return vol, beta, n


def _month_return(panel: DailyPanel, sym: str, month: tuple[int, int]) -> float | None:
    """Compounded daily return of `sym` over the trading days whose month == `month` (precomputed). None if
    the name had no bars that month."""
    return panel.month_ret.get(month, {}).get(sym)


def build_rank_table(
    panel: DailyPanel, market: str = "SPY"
) -> dict[tuple[int, int], dict[str, tuple[float, float]]]:
    """Precompute trailing (vol, beta) for every (rebalance-month, name) ONCE — the same trailing stats are
    reused by every book/frac/control variant, so computing them once removes the dominant cost. The value is
    keyed by the month whose FIRST trading day is the rebalance point; vol/beta use only days strictly before."""
    first_day_idx: dict[tuple[int, int], int] = {}
    for i, d in enumerate(panel.days):
        m = panel.month_of[d]
        if m not in first_day_idx:
            first_day_idx[m] = i
    table: dict[tuple[int, int], dict[str, tuple[float, float]]] = {}
    for m in panel.months:
        di = first_day_idx[m]
        if di < LOOKBACK_DAYS:
            continue
        row: dict[str, tuple[float, float]] = {}
        for sym in panel.symbols:
            vol, beta, _ = _trailing_stats(panel, di, sym, market)
            row[sym] = (vol, beta)
        table[m] = row
    return table


def run_lowvol(
    panel: DailyPanel,
    rank_table: dict[tuple[int, int], dict[str, tuple[float, float]]],
    *,
    rank_by: str,            # "vol" | "beta"
    construction: str,       # "long_only" | "market_neutral"
    sign: int,               # +1 = standard (long LOW vol/beta); -1 = ANTI control (long HIGH)
    frac: float = 1 / 3,
    market: str = "SPY",
    rng_seed: int | None = None,
) -> StratResult:
    """Monthly-rebalanced low-vol/BAB book.

    At the first trading day of each month, rank names by trailing realized vol or beta (computed strictly from
    prior bars). LONG the lowest-`frac` tranche (sign=+1). market_neutral additionally SHORTs the highest-`frac`.
    The book is held over the whole month and earns each name's compounded monthly return. NO look-ahead: ranking
    uses only days BEFORE the month start. rng_seed → RANDOM-RANK placebo (rank by a deterministic pseudo-random
    key, independent of price)."""
    months = panel.months
    prev_weights: dict[str, float] = {}
    net: list[float] = []
    gross: list[float] = []
    turnover_series: list[float] = []
    used_months: list[tuple[int, int]] = []
    bench_series: list[float] = []

    for m in months:
        row = rank_table.get(m)
        if row is None:  # not enough lookback history before this month
            continue
        mret_all = panel.month_ret.get(m, {})
        # rank-eligible names: enough lookback history AND a realized monthly return this month
        scored: list[tuple[str, float]] = []
        eligible_names: list[str] = []
        for sym in panel.symbols:
            vol, beta = row[sym]
            metric = vol if rank_by == "vol" else beta
            if metric != metric:  # NaN
                continue
            if sym not in mret_all:
                continue
            scored.append((sym, metric))
            eligible_names.append(sym)
        n = len(scored)
        if n < 6:
            prev_weights = {}
            continue
        k = max(1, int(round(n * frac)))

        if rng_seed is not None:
            def key(item: tuple[str, float]) -> float:
                h = hash((rng_seed, m, item[0]))
                return (h % 1_000_003) / 1_000_003.0
            ranked = sorted(scored, key=key)
        else:
            ranked = sorted(scored, key=lambda it: it[1])  # ascending: lowest vol/beta first

        low_names = [s for s, _ in ranked[:k]]
        high_names = [s for s, _ in ranked[-k:]]

        # sign=+1 → long the LOW tranche; sign=-1 → long the HIGH tranche (anti control)
        long_names = low_names if sign == +1 else high_names
        short_names = high_names if sign == +1 else low_names

        weights: dict[str, float] = {}
        if construction == "long_only":
            for s in long_names:
                weights[s] = weights.get(s, 0.0) + 1.0 / len(long_names)
        else:  # market_neutral: dollar-neutral long/short, 0.5 gross per leg
            for s in long_names:
                weights[s] = weights.get(s, 0.0) + 0.5 / len(long_names)
            for s in short_names:
                weights[s] = weights.get(s, 0.0) - 0.5 / len(short_names)

        # realized monthly returns for held names (all eligible names have one by construction)
        gross_ret = sum(w * mret_all[s] for s, w in weights.items())

        # equal-weight benchmark over ALL eligible names this month (survivorship-matched reference)
        bench_ret = statistics.fmean([mret_all[s] for s in eligible_names])

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
        used_months.append(m)
        bench_series.append(bench_ret)
        prev_weights = weights

    return StratResult(net, gross, turnover_series, used_months, bench_series)


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
    """MONTHLY NET return stream -> BacktestMetrics with a REAL purged+embargoed out-of-sample holdout.

    Gate-facing stats are computed on the IN-SAMPLE slice; `holdout_deflated_sharpe` is the genuine DSR of the
    held-out tail. Replaces the prior stub (holdout pinned to 0.0001, every stat on the full sample). require_beat
    _buy_and_hold stays OFF for this run. embargo=6: the low-vol/beta rank uses a ~120-trading-day (~6-month)
    formation window, so a 6-month embargo keeps the formation window off the train/holdout boundary."""
    metrics, _split = metrics_with_holdout(
        returns, trials_counted=trials_counted, periods_per_year=12,
        holdout_frac=0.2, embargo=6, long_only=False)
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
    n_months: int
    window: str
    candidates: list[dict] = field(default_factory=list)
    verdict: str = ""
    headline: str = ""
    notes: list[str] = field(default_factory=list)


# The grid of book variants. Each is (name, rank_by, construction, sign, is_disconfirmer, is_primary).
# Primary = the documented low-vol/BAB edge we are TESTING. Disconfirmers = anti control + placebo.
def _grid() -> list[tuple[str, str, str, int]]:
    # (name, rank_by, construction, sign)
    return [
        ("lowvol_long_only", "vol", "long_only", +1),
        ("lowbeta_long_only", "beta", "long_only", +1),
        ("bab_vol_neutral", "vol", "market_neutral", +1),     # long low-vol / short high-vol
        ("bab_beta_neutral", "beta", "market_neutral", +1),   # long low-beta / short high-beta
    ]


def run(universe_name: str, symbols: list[str], fracs: list[float], market: str = "SPY") -> Verdict:
    universe = load_universe()
    symbols = [s for s in symbols if s in universe]
    panel = build_daily_panel(universe, symbols, market=market)
    if len(panel.months) < 36:
        return Verdict(universe_name, len(panel.months), "n/a", verdict="INSUFFICIENT-DATA",
                       headline="too few months")

    store = Store(Settings(database_url=f"sqlite:///{tempfile.mkdtemp(prefix='cosmu-lowvol-')}/g.sqlite3",
                           openrouter_api_key=None))
    gates = store.settings.gates
    # market-neutral / dollar-neutral benchmark is cash; the long-only book is judged on absolute net but we
    # ALSO report the relative-to-EW alpha. Disable the long-basket hurdle so the run is internally consistent.
    gates = gates.model_copy(update={"require_beat_buy_and_hold": False})

    # ---- TRIAL LEDGER: register EVERY grid/param variant, so deflation/FDR see the true count. ----
    # grid = {4 book types} x {each frac}  + {placebo seeds at canonical frac} + {anti-controls at canonical frac}
    variants: dict[str, list[tuple[float, StratResult, BacktestMetrics]]] = {}

    rank_table = build_rank_table(panel, market=market)

    def eval_arm(name: str, rank_by: str, construction: str, sign: int, frac: float,
                 seed: int | None, source: str, label: str) -> tuple[StratResult, BacktestMetrics]:
        res = run_lowvol(panel, rank_table, rank_by=rank_by, construction=construction, sign=sign,
                         frac=frac, market=market, rng_seed=seed)
        m = metrics_from_returns(res.net, trials_counted=1)
        register_trial(store, float(m.sharpe_per_obs), source=source, label=label)
        return res, m

    for name, rank_by, construction, sign in _grid():
        variants[name] = []
        for frac in fracs:
            res, m = eval_arm(name, rank_by, construction, sign, frac, None,
                              "equity_lowvol_bab", f"{name}:frac={frac:.2f}")
            variants[name].append((frac, res, m))

    # ANTI controls (disconfirmer #1): long HIGH vol/beta instead of LOW — the documented edge says these LOSE.
    anti_variants: dict[str, list[tuple[float, StratResult, BacktestMetrics]]] = {}
    for name, rank_by, construction, _sign in _grid():
        aname = f"anti_{name}"
        anti_variants[aname] = []
        res, m = eval_arm(aname, rank_by, construction, -1, 1 / 3, None,
                          "equity_lowvol_bab", f"{aname}:frac=0.33")
        anti_variants[aname].append((1 / 3, res, m))

    # RANDOM-RANK placebo (disconfirmer #2): several seeds at canonical frac, market-neutral construction.
    placebo_variants: list[tuple[float, StratResult, BacktestMetrics]] = []
    for seed in range(1, 6):
        res, m = eval_arm("placebo", "vol", "market_neutral", +1, 1 / 3, seed,
                          "equity_lowvol_bab", f"placebo:seed={seed}")
        placebo_variants.append((1 / 3, res, m))

    trials = trial_stats(store)

    def gate_best(vs):
        best = None
        best_key = (-1, -1.0)
        for frac, res, m in vs:
            v = score(m, gates, trials=trials)
            key = (1 if v.passed else 0, float(v.deflated_sharpe_prob))
            if best is None or key > best_key:
                best_key = key
                best = (frac, res, m)
        return best

    # Real CSCV-PBO across each primary book's own frac-variant net streams (a legitimate config population).
    # Computed on the IN-SAMPLE slice ONLY (exclude the held-out tail) so the holdout stays untouched.
    def book_pbo(name: str) -> float:
        streams = [purged_embargoed_split(res.net, embargo=6).in_sample
                   for _, res, _ in variants[name] if len(res.net) >= 20]
        return cscv_pbo(streams) if len(streams) >= 2 else 1.0

    # ---- Build cohort of DISTINCT candidates: the 4 primary books + anti-controls + placebo. ----
    candidates: list[Candidate] = []
    chosen: dict[str, tuple[float, StratResult, BacktestMetrics]] = {}
    pbo_of: dict[str, float] = {}

    def add_candidate(name: str, best, pbo: float | None) -> None:
        frac, res, m = best
        # m already carries the in-sample folds_positive_pct AND the REAL purged+embargoed holdout DSR
        # (from metrics_from_returns -> metrics_with_holdout). The ONLY metric attached here is the real CSCV-PBO.
        upd: dict = {}
        if pbo is not None:
            upd["pbo"] = Decimal(str(round(pbo, 6)))
        m = m.model_copy(update=upd) if upd else m
        var = statistics.pvariance(res.net) if len(res.net) > 1 else 1.0
        candidates.append(Candidate(id=name, metrics=m, net_profit=float(m.oos_return),
                                    source="equity_lowvol_bab", label=name, return_variance=var or 1.0))
        chosen[name] = (frac, res, m)
        if pbo is not None:
            pbo_of[name] = pbo

    for name, *_ in _grid():
        add_candidate(name, gate_best(variants[name]), book_pbo(name))
    for aname, vs in anti_variants.items():
        add_candidate(aname, gate_best(vs), None)
    add_candidate("random_placebo", gate_best(placebo_variants), None)

    promotions = promote_cohort(store, candidates, gates, fdr_q=0.10, register=False, trials=trials)
    by_id = {p.candidate_id: p for p in promotions}

    rows: list[dict] = []
    for c in candidates:
        frac, res, m = chosen[c.id]
        p = by_id[c.id]
        mean_turn = statistics.fmean(res.turnover) if res.turnover else 0.0
        gross_total = 1.0
        for g in res.gross:
            gross_total *= (1.0 + g)
        gross_total -= 1.0
        # relative-to-EW alpha (survivorship-matched): geometric net minus geometric benchmark
        bench_total = 1.0
        for b in res.bench:
            bench_total *= (1.0 + b)
        bench_total -= 1.0
        alpha_vs_ew = float(m.oos_return) - bench_total
        cost_ratio = (float(m.oos_return) / gross_total) if gross_total else float("nan")
        rows.append({
            "name": c.id, "frac": round(frac, 3),
            "net_total_return": round(float(m.oos_return), 5),
            "gross_total_return": round(gross_total, 5),
            "bench_ew_return": round(bench_total, 5),
            "alpha_vs_ew": round(alpha_vs_ew, 5),
            "cost_ratio": round(cost_ratio, 3) if cost_ratio == cost_ratio else None,
            "ann_sharpe": float(m.sharpe), "sharpe_per_obs": float(m.sharpe_per_obs),
            "deflated_sharpe_prob": round(float(p.deflated_sharpe_prob), 6),
            "pbo": float(m.pbo), "folds_positive": float(m.folds_positive_pct),
            "holdout_dsr": round(float(m.holdout_deflated_sharpe), 6),
            "n_months": m.num_trades, "max_dd": float(m.max_drawdown),
            "mean_monthly_turnover": round(mean_turn, 3),
            "win_rate": float(m.win_rate),
            "promoted": p.promoted, "survived_fdr": p.survived_fdr, "reasons": p.reasons,
        })

    m0 = panel.months[0]; m1 = panel.months[-1]
    window = f"{m0[0]}-{m0[1]:02d} .. {m1[0]}-{m1[1]:02d}"

    # The verdict: did ANY primary low-vol/BAB book survive the cohort gate + BH-FDR?
    primary_names = [n for n, *_ in _grid()]
    promoted_primaries = [n for n in primary_names if by_id[n].promoted]
    if promoted_primaries:
        verdict = "PASS"
        headline = (f"low-vol/BAB SURVIVED the cohort gate + BH-FDR (q=0.10) on {universe_name}: "
                    f"{', '.join(promoted_primaries)}")
    else:
        verdict = "FAIL"
        best_primary = max(primary_names, key=lambda n: by_id[n].deflated_sharpe_prob)
        headline = (f"low-vol/BAB did NOT survive the gate on {universe_name}; "
                    f"best={best_primary} DSR={by_id[best_primary].deflated_sharpe_prob:.3f} "
                    f"reasons={by_id[best_primary].reasons}")
    return Verdict(universe_name, len(panel.months), window, candidates=rows,
                   verdict=verdict, headline=headline)


def _print(v: Verdict) -> None:
    print(f"\n=== EQUITY LOW-VOL / BAB — {v.universe} — {v.verdict} ===")
    print(f"  months={v.n_months}  window={v.window}  lookback={LOOKBACK_DAYS}d  market=SPY")
    print(f"  fee model: stocks {COST_STOCK_PER_SIDE*1e4:.0f} bps/side, ETFs {COST_ETF_PER_SIDE*1e4:.0f} bps/side, "
          f"applied to MONTHLY turnover")
    for r in v.candidates:
        flag = "PROMOTED" if r["promoted"] else ("fdr-only" if r["survived_fdr"] else "stop")
        print(f"  [{flag:>9}] {r['name']:<20} frac={r['frac']} net={r['net_total_return']:+.4f} "
              f"gross={r['gross_total_return']:+.4f} ewBench={r['bench_ew_return']:+.4f} "
              f"alphaVsEW={r['alpha_vs_ew']:+.4f} crat={r['cost_ratio']} "
              f"annSR={r['ann_sharpe']:+.2f} SRobs={r['sharpe_per_obs']:+.4f} DSR={r['deflated_sharpe_prob']:.3f} "
              f"holdoutDSR={r['holdout_dsr']:+.4f} "
              f"pbo={r['pbo']:.2f} folds+={r['folds_positive']:.2f} maxDD={r['max_dd']:.3f} "
              f"turn={r['mean_monthly_turnover']:.3f} win={r['win_rate']:.2f} fdr={'Y' if r['survived_fdr'] else 'N'}")
        if r["reasons"]:
            print(f"                 reasons: {', '.join(r['reasons'])}")
    print(f"  HEADLINE: {v.headline}")


def main() -> int:
    universe = load_universe()
    all_syms = sorted(universe)
    stocks = [s for s in all_syms if s not in ETFS]
    etfs = [s for s in all_syms if s in ETFS]
    fracs = [0.2, 0.25, 1 / 3, 0.5]

    for name, syms in [("SINGLE-STOCKS (survivors-biased)", stocks),
                       ("SECTOR+BROAD ETFs", etfs),
                       ("ALL NAMES", all_syms)]:
        v = run(name, syms, fracs)
        _print(v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
