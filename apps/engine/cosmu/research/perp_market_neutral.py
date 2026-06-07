# intent: a runnable CROSS-SECTIONAL LONG/SHORT MARKET-NEUTRAL harness on PERPETUAL futures — the un-exhausted
# direction the carry verdict pointed at (the realest signal was L/S-neutral, killed only by SPOT costs; perps
# settle in the same instrument so the long & short legs both trade at the lower perp taker fee AND the short leg
# earns/pays funding instead of being un-shortable on spot). It mirrors the structure + honesty of
# equity_sector_cohort.py: rank the perp universe cross-sectionally each rebalance, go LONG the top quantile /
# SHORT the bottom, DOLLAR-NEUTRAL (Σw = 0, Σ|w| = 1), and backtest NET of REAL perp fees + REAL funding, then
# route the cohort through the EXISTING deterministic scorer + cohort.promote_cohort BH-FDR (q=0.10) + the REAL
# purged+embargoed holdout (research.equity_holdout.metrics_with_holdout). Propose-only; NEVER moves money.
#
# DOCTRINE (unchanged from the rest of research/):
#   * ZERO LLM on the gate path; deterministic for a fixed cache.
#   * The scorer thresholds + promote_cohort q=0.10 are NOT changed (only routed). Every grid/param/placebo
#     variant is registered as a trial so deflation/FDR see the true count. Fresh tempfile cohort store.
#   * NO synthetic / zero fill — a rebalance missing a name simply drops that name that period; a symbol with no
#     bars in the cache is never seen (degrade gracefully, never fabricate a price or a funding print).
#   * NO look-ahead — the ranking signal at rebalance t uses only bars realized through t's close; the book earns
#     period t→t+1's return; funding is accrued from the REAL settlements that land inside that held interval.
#   * REAL costs only: we do NOT reimplement fees — the per-side perp taker fee comes from the venue catalog
#     (default_catalog().venue('binance').taker_fee_bps), charged on realized two-sided turnover; the per-bar
#     funding cash flow comes from data.backtest.sum_funding_per_bar (the SUMMED-per-bar accrual, the funding-
#     correct join), applied with the SAME sign convention as data.backtest._accrue_funding (a LONG perp pays
#     positive funding, a SHORT receives it -> cash flow = -w * rate per held period).
#
# WHY a portfolio-return STREAM (not a per-symbol backtest): the cross-section is collapsed to ONE realized
# dollar-neutral NET return per rebalance period, exactly like equity_sector_cohort's single-name neutral book.
# The honest holdout is therefore a chronological purged+embargoed split of that realized series (equity_holdout),
# the same construction the crypto backtest applies to bar_returns.

from __future__ import annotations

import hashlib
import statistics
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataProvider, CachedFundingRateProvider
from cosmu.data.backtest import sum_funding_per_bar
from cosmu.data.market import Bar, BinanceSpotOHLCVProvider
from cosmu.data.universe import PERP_UNIVERSE
from cosmu.knowledge.store import Store
from cosmu.master.cohort import Candidate, promote_cohort
from cosmu.master.scorer import BacktestMetrics, cscv_pbo, score
from cosmu.master.trials import register_trial, trial_stats
from cosmu.master.verdict_log import durable_persist
from cosmu.research.equity_holdout import metrics_with_holdout, purged_embargoed_split

# Default perp bar cache (the local M2 store); the spot/perp providers share the Bar shape, so the perp cache is
# read through the same BinanceSpotOHLCVProvider seam with the perp cache_dir.
PERP_CACHE = "/Users/device/cosmu/.cosmu/market_data/binanceperp"
FUNDING_CACHE = "/Users/device/cosmu/.cosmu/market_data/binance_funding"

# Per-SIDE perp taker fee (fraction), read from the REAL venue catalog — NOT a magic number. Charged on the
# realized two-sided turnover of the book each rebalance (Σ|w_t - w_{t-1}| * per_side), so a low-turnover monthly
# book is charged honestly little and a churny one honestly more.
from cosmu.spine.venue import default_catalog  # noqa: E402  (placed here so the constant reads from the catalog)

PERP_FEE_PER_SIDE: float = float(default_catalog().venue("binance").taker_fee_bps) / 10000.0

# A rebalance needs at least this many ranked names to form a non-degenerate top/bottom quantile L/S book.
MIN_NAMES = 6

# Formation lookbacks (in rebalance-periods) swept per signal — e.g. on a weekly grid these are ~1m and ~3m
# momentum/carry windows. Also sizes the holdout embargo (>= the deepest lookback, so no formation window
# straddles the split boundary).
_LOOKBACKS = (4, 12)


def _placebo_key(seed: int, period: int, sym: str) -> float:
    """Deterministic pseudo-random rank key in [0,1) for the random-rank disconfirmer. blake2b (NOT Python's
    salted builtin hash) so the placebo is byte-reproducible across processes — a placebo that wanders run-to-run
    is a weak disconfirmer."""
    h = hashlib.blake2b(f"{seed}|{period}|{sym}".encode(), digest_size=8).digest()
    return (int.from_bytes(h, "big") % 1_000_003) / 1_000_003.0


# ----------------------------------------------------------------------------------------------------------------
# data loading (perp bars + funding from the store/cache; degrade gracefully, never synthetic-fill)
# ----------------------------------------------------------------------------------------------------------------
def load_perp_market(
    symbols: tuple[str, ...] = PERP_UNIVERSE,
    *,
    timeframe: str = "1d",
    cache_dir: str = PERP_CACHE,
    limit: int = 2000,
) -> dict[str, list[Bar]]:
    """Read cached REAL perp bars for each universe symbol. A symbol with no cache file (or that errors) is simply
    absent from the returned dict — NEVER synthetic-filled. Deterministic for a fixed cache."""
    provider = BinanceSpotOHLCVProvider(cache_dir=cache_dir)
    out: dict[str, list[Bar]] = {}
    for sym in symbols:
        try:
            bars = provider.fetch_bars(sym, timeframe, limit=limit)
        except Exception:  # noqa: BLE001 — offline / missing file: honest skip, never fabricate
            continue
        if bars:
            out[sym] = bars
    return out


@dataclass
class Panel:
    """Rebalance-grid panel over the cross-section. The grid is the UNION of bar timestamps across symbols at the
    chosen `rebalance` cadence; a symbol simply absent at a grid time is not fillable (NO synthetic).
      level[t][sym]  = the symbol's close at grid time t.
      ret[t][sym]    = the symbol's price return realized from the PREVIOUS grid time to t (PIT — known by t).
      funding[t][sym]= the SUMMED funding cash-flow-per-unit-notional that settled in (prev_t, t] for sym (real
                       per-bar accrual via sum_funding_per_bar). Long pays positive, short receives (sign applied
                       at book construction). Missing -> 0.0 (no settlement that interval -> accrues nothing)."""

    times: list[datetime]
    level: dict[datetime, dict[str, float]]
    ret: dict[datetime, dict[str, float]]
    funding: dict[datetime, dict[str, float]]
    symbols: list[str]


def _resample(bars: list[Bar], rebalance: int) -> list[Bar]:
    """Take every `rebalance`-th bar (the rebalance-grid close). rebalance=1 keeps the native cadence. The first
    bar is always kept so the very first interval is well-defined; NO interpolation."""
    if rebalance <= 1:
        return bars
    return bars[::rebalance]


def build_panel(
    market: dict[str, list[Bar]],
    funding: AltDataProvider,
    *,
    rebalance: int = 1,
) -> Panel:
    """Build the rebalance-grid panel. Price returns are realized close-to-close on the grid; the funding leg sums
    EVERY real settlement that landed in each grid interval (sum_funding_per_bar) so the carry accrued per held
    period is the true total regardless of how the bar cadence relates to the 8h funding settlement. PIT + no
    synthetic fill throughout."""
    grids: dict[str, list[Bar]] = {sym: _resample(bars, rebalance) for sym, bars in market.items() if bars}
    # Per-symbol funding summed onto the SAME grid bars (sum_funding_per_bar reads the real settlements; a symbol
    # with no funding cache yields {} -> the symbol simply earns no carry, an honest 'no data' not a 0-fab).
    fund_by_sym: dict[str, dict[str, float]] = {}
    for sym, gbars in grids.items():
        pts = funding.fetch_series(sym, "funding_rate", limit=len(gbars) * 3 + 1100)
        fund_by_sym[sym] = sum_funding_per_bar(pts, gbars) if pts else {}

    all_times = sorted({b.ts for gbars in grids.values() for b in gbars})
    idx = {t: i for i, t in enumerate(all_times)}
    level: dict[datetime, dict[str, float]] = {t: {} for t in all_times}
    ret: dict[datetime, dict[str, float]] = {t: {} for t in all_times}
    fund: dict[datetime, dict[str, float]] = {t: {} for t in all_times}
    for sym, gbars in grids.items():
        by_ts = {b.ts: float(b.close) for b in gbars}
        f_series = fund_by_sym.get(sym, {})
        for b in gbars:
            t = b.ts
            level[t][sym] = float(b.close)
            iso = t.isoformat()
            if iso in f_series:
                fund[t][sym] = f_series[iso]
            i = idx[t]
            if i == 0:
                continue
            prev = all_times[i - 1]
            pc = by_ts.get(prev)
            if pc and pc > 0:
                ret[t][sym] = float(b.close) / pc - 1.0
    return Panel(all_times, level, ret, fund, list(grids.keys()))


# ----------------------------------------------------------------------------------------------------------------
# the cross-sectional signals (ranked across the universe at each rebalance, PIT)
# ----------------------------------------------------------------------------------------------------------------
def momentum_signal(panel: Panel, t_idx: int, sym: str, lookback: int, skip: int) -> float | None:
    """Trailing (lookback - skip)-period return: level[t-skip]/level[t-lookback] - 1 (skip the most recent period
    to avoid 1-period reversal contamination). Both endpoints are <= grid time t's close, the harvested return is
    t→t+1 — NO look-ahead. None when either endpoint is missing (the name is then unranked that period)."""
    times = panel.times
    if t_idx - lookback < 0 or t_idx - skip < 0:
        return None
    lr = panel.level[times[t_idx - skip]].get(sym)
    lo = panel.level[times[t_idx - lookback]].get(sym)
    if lr is None or lo is None or lo <= 0:
        return None
    return lr / lo - 1.0


def carry_signal(panel: Panel, t_idx: int, sym: str, lookback: int, skip: int) -> float | None:
    """Funding-CARRY rank key: the trailing mean of the (signed) per-period funding the symbol settled over the
    formation window. A HIGH value = a richly-positive-funding perp (crowded longs paying up) -> the carry trade
    SHORTS it (sign=-1 inverts the rank so the short leg captures the funding the longs pay). PIT: only
    settlements realized through grid time t enter the mean; the carry is harvested in t→t+1. None when the
    formation window has no funding for the name (unranked that period — never fabricate a 0 carry)."""
    times = panel.times
    lo = t_idx - lookback
    if lo < 0:
        return None
    vals = [panel.funding[times[j]].get(sym) for j in range(lo, t_idx - skip + 1)]
    seen = [v for v in vals if v is not None]
    if not seen:
        return None
    return statistics.fmean(seen)


_SIGNALS = {"momentum": momentum_signal, "carry": carry_signal}


@dataclass
class StratResult:
    net: list[float]      # per-rebalance NET return (price + funding - fees)
    gross: list[float]    # per-rebalance GROSS return (price + funding, ZERO fees) — for cost_ratio
    turnover: list[float]
    times: list[datetime]


def run_neutral_book(
    panel: Panel,
    *,
    signal: str,
    sign: int,
    lookback: int,
    skip: int,
    frac: float = 1 / 3,
    fee_per_side: float = PERP_FEE_PER_SIDE,
    rng_seed: int | None = None,
) -> StratResult:
    """The cross-sectional dollar-neutral L/S perp book.

    Each rebalance: rank every present-and-rankable name by `signal` (or by a deterministic pseudo-random key when
    `rng_seed` is set — the random-rank placebo). Take the top `frac` and bottom `frac`:
        sign=+1  -> LONG the top of the ranking, SHORT the bottom (momentum: long winners / short losers).
        sign=-1  -> the opposite sibling (the disconfirmer; for the carry signal this is the natural carry trade:
                    SHORT the richest-funding names / LONG the cheapest).
    Weights: equal within each leg, scaled so Σw = 0 (dollar-neutral) AND Σ|w| = 1 (unit gross exposure). The
    book earns next period's price return on each leg PLUS the real funding cash flow on each leg (long pays
    +rate, short receives -> per-name carry = -w * funding), MINUS the perp taker fee on realized two-sided
    turnover. NO synthetic fill — a name without a forward return that period is dropped from the book that
    period (so it never silently contributes a fabricated 0)."""
    fn = _SIGNALS[signal]
    times = panel.times
    prev: dict[str, float] = {}
    net: list[float] = []
    gross: list[float] = []
    turn: list[float] = []
    used: list[datetime] = []

    for i in range(len(times) - 1):
        t = times[i]
        t_next = times[i + 1]
        fwd = panel.ret[t_next]
        carry_next = panel.funding[t_next]

        ranked: list[tuple[str, float]] = []
        for sym in panel.symbols:
            if sym not in panel.level[t] or sym not in fwd:
                continue  # need a current level to rank AND a realized forward return to earn (no synthetic)
            sv = _placebo_key(rng_seed, i, sym) if rng_seed is not None else fn(panel, i, sym, lookback, skip)
            if sv is not None:
                ranked.append((sym, sv))

        n = len(ranked)
        k = int(round(n * frac))
        if n < MIN_NAMES or k < 1:
            prev = {}
            continue
        ranked.sort(key=lambda x: x[1])  # ascending: lowest signal .. highest signal
        low_names = [s for s, _ in ranked[:k]]
        high_names = [s for s, _ in ranked[-k:]]
        long_names = high_names if sign == +1 else low_names
        short_names = low_names if sign == +1 else high_names

        # dollar-neutral, unit-gross weights: each leg carries 0.5 gross, equal within the leg.
        w: dict[str, float] = {}
        for s in long_names:
            w[s] = w.get(s, 0.0) + 0.5 / len(long_names)
        for s in short_names:
            w[s] = w.get(s, 0.0) - 0.5 / len(short_names)

        # price + funding P&L this period. Funding cash flow per name = -w * realized funding (long pays positive
        # funding, short receives) — SAME sign convention as data.backtest._accrue_funding. A name with no
        # settlement this interval has carry 0 (honest: no print, no accrual).
        gross_ret = 0.0
        for s, wt in w.items():
            gross_ret += wt * fwd[s]                       # price leg
            gross_ret += -wt * carry_next.get(s, 0.0)      # funding leg (real per-bar accrual)

        # REAL perp fee on realized two-sided turnover (NOT reimplemented — the per-side rate is the venue's).
        names = set(w) | set(prev)
        tov = sum(abs(w.get(s, 0.0) - prev.get(s, 0.0)) for s in names)
        cost = tov * fee_per_side
        net.append(gross_ret - cost)
        gross.append(gross_ret)
        turn.append(tov)
        used.append(t_next)
        prev = w

    return StratResult(net, gross, turn, used)


# ----------------------------------------------------------------------------------------------------------------
# metrics + gate plumbing (mirrors equity_sector_cohort exactly: REAL purged+embargoed holdout, NEVER a stub)
# ----------------------------------------------------------------------------------------------------------------
def metrics_from_returns(
    returns: list[float], *, trials_counted: int, periods_per_year: int, embargo: int
) -> BacktestMetrics:
    """Per-rebalance NET return stream -> BacktestMetrics with a REAL purged+embargoed out-of-sample holdout. All
    gate-facing stats are computed on the IN-SAMPLE slice; holdout_deflated_sharpe is the genuine DSR of the
    held-out tail. `embargo` covers the formation lookback so no formation window straddles the split boundary.
    The neutral book is market-neutral, so long_only=False (no buy-and-hold hurdle — the hurdle is cash=0)."""
    metrics, _ = metrics_with_holdout(
        returns, trials_counted=trials_counted, periods_per_year=periods_per_year,
        holdout_frac=0.2, embargo=embargo, long_only=False,
    )
    return metrics


@dataclass
class Verdict:
    n_periods: int
    n_symbols: int
    window: str
    candidates: list[dict] = field(default_factory=list)
    verdict: str = ""
    headline: str = ""
    notes: list[str] = field(default_factory=list)


def _annualization(timeframe: str, rebalance: int) -> int:
    """Periods-per-year for the rebalance grid, used to annualize the display Sharpe + size the embargo."""
    per_year = {"1d": 365, "4h": 365 * 6, "1h": 365 * 24}.get(timeframe, 365)
    return max(1, round(per_year / max(1, rebalance)))


def run(
    market: dict[str, list[Bar]],
    funding: AltDataProvider,
    *,
    timeframe: str = "1d",
    rebalance: int = 7,
    persist: bool = False,
) -> Verdict:
    """Build the perp panel, run the cross-sectional L/S neutral cohort (momentum + carry, each with its opposite-
    sign sibling AND a random-rank placebo), and route the WHOLE family through promote_cohort BH-FDR (q=0.10) +
    the real holdout. `persist=True` records the cohort verdict to durable experiment-memory (gate_verdicts) via
    the REAL configured store; tests leave it False so they never touch the durable store. Propose-only."""
    panel = build_panel(market, funding, rebalance=rebalance)
    n_sym = len(panel.symbols)
    if not panel.times:
        return Verdict(0, n_sym, "n/a", verdict="INSUFFICIENT-DATA", headline="no perp bars in cache")
    t0, t1 = panel.times[0], panel.times[-1]
    window = f"{t0.date()}..{t1.date()}"
    # honest depth abstention: too few rebalances or too thin a cross-section can never form a real L/S book.
    if len(panel.times) < 60 or n_sym < MIN_NAMES:
        return Verdict(
            len(panel.times), n_sym, window, verdict="INSUFFICIENT-DATA",
            headline=f"too thin for a cross-sectional book: {len(panel.times)} periods x {n_sym} symbols",
            notes=[f"need >=60 rebalance periods and >={MIN_NAMES} symbols with cached perp bars"],
        )

    ppy = _annualization(timeframe, rebalance)
    # embargo >= the deepest formation lookback so no formation window straddles the holdout boundary.
    embargo = max(4, max(_LOOKBACKS))

    store = Store(Settings(database_url=f"sqlite:///{tempfile.mkdtemp(prefix='cosmu-perpmn-')}/g.sqlite3",
                           openrouter_api_key=None))
    base_gates = store.settings.gates
    # market-neutral: no buy-and-hold hurdle (the hurdle is cash = 0; a neutral book has no beta to beat).
    gates = base_gates.model_copy(update={"require_beat_buy_and_hold": False})

    # --------------------------------------------------------------------------------------------------------
    # GRID. Every variant is registered as a trial (true multiple-testing count). For EACH signal:
    #   real arms: sign in {+1, -1} x frac in {0.25, 1/3} x lookback in _LOOKBACKS
    #   placebos:  random-rank, sign=+1, frac=1/3, deepest lookback, seeds 1..5
    # The cohort spans BOTH signals + both signs + the placebos, so the family-wise BH-FDR is honest.
    # --------------------------------------------------------------------------------------------------------
    real_variants: dict[str, list[tuple[str, StratResult, BacktestMetrics]]] = {"momentum": [], "carry": []}
    placebo_variants: dict[str, list[tuple[str, StratResult, BacktestMetrics]]] = {"momentum": [], "carry": []}

    for signame in ("momentum", "carry"):
        for sign in (+1, -1):
            for frac in (0.25, 1 / 3):
                for lb in _LOOKBACKS:
                    res = run_neutral_book(panel, signal=signame, sign=sign, lookback=lb, skip=1, frac=frac)
                    m = metrics_from_returns(res.net, trials_counted=1, periods_per_year=ppy, embargo=embargo)
                    register_trial(store, float(m.sharpe_per_obs), source="perp_market_neutral",
                                   label=f"{signame}:sign={sign},frac={frac:.2f},lb={lb}")
                    real_variants[signame].append((f"sign={sign},frac={frac:.2f},lb={lb}", res, m))
        for seed in range(1, 6):
            res = run_neutral_book(panel, signal=signame, sign=+1, lookback=max(_LOOKBACKS), skip=1,
                                   frac=1 / 3, rng_seed=seed)
            m = metrics_from_returns(res.net, trials_counted=1, periods_per_year=ppy, embargo=embargo)
            register_trial(store, float(m.sharpe_per_obs), source="perp_market_neutral",
                           label=f"{signame}_placebo:seed={seed}")
            placebo_variants[signame].append((f"seed={seed}", res, m))

    trials = trial_stats(store)

    def gate_best(variants: list[tuple[str, StratResult, BacktestMetrics]]):  # noqa: ANN202
        best = None
        best_key = (-1, -1.0)
        for tag, res, m in variants:
            v = score(m, gates, trials=trials)
            key = (1 if v.passed else 0, float(v.deflated_sharpe_prob))
            if best is None or key > best_key:
                best_key, best = key, (tag, res, m)
        return best

    # Real CSCV-PBO within each signal's own config population (legitimate — same construction, varied params),
    # computed on the IN-SAMPLE slice ONLY so the holdout stays untouched.
    def pbo_of(variants: list[tuple[str, StratResult, BacktestMetrics]]) -> float:
        streams = [purged_embargoed_split(res.net, embargo=embargo).in_sample
                   for _, res, _ in variants if len(res.net) >= 20]
        return cscv_pbo(streams) if len(streams) >= 2 else 1.0

    candidates: list[Candidate] = []
    meta: dict[str, tuple[StratResult, BacktestMetrics]] = {}

    def add(name: str, best, pbo: float | None) -> None:
        if best is None:
            return
        tag, res, m = best
        if pbo is not None:
            m = m.model_copy(update={"pbo": Decimal(str(round(pbo, 6)))})
        var = statistics.pvariance(res.net) if len(res.net) > 1 else 1.0
        candidates.append(Candidate(id=name, metrics=m, net_profit=float(m.oos_return),
                                    source="perp_market_neutral", label=f"{name}:{tag}",
                                    return_variance=var or 1.0))
        meta[name] = (res, m)

    add("perp_momentum_neutral", gate_best(real_variants["momentum"]), pbo_of(real_variants["momentum"]))
    add("perp_carry_neutral", gate_best(real_variants["carry"]), pbo_of(real_variants["carry"]))
    add("momentum_placebo", gate_best(placebo_variants["momentum"]), None)
    add("carry_placebo", gate_best(placebo_variants["carry"]), None)

    persist_spec = durable_persist(
        run_id="perp-market-neutral",
        hypothesis="a cross-sectional dollar-neutral L/S perp book (momentum or funding-carry) clears the honest "
                   "gate after REAL perp fees + funding",
        source="research/perp_market_neutral", data_source="perp-cached",
    ) if persist else None
    promotions = promote_cohort(store, candidates, gates, fdr_q=0.10, register=False, trials=trials,
                                persist=persist_spec)
    by_id = {p.candidate_id: p for p in promotions}

    rows: list[dict] = []
    for c in candidates:
        res, m = meta[c.id]
        p = by_id[c.id]
        gross_total = 1.0
        for g in res.gross:
            gross_total *= (1.0 + g)
        gross_total -= 1.0
        cost_ratio = (float(m.oos_return) / gross_total) if gross_total else None
        rows.append({
            "name": c.id,
            "net_total_return": round(float(m.oos_return), 5),
            "gross_total_return": round(gross_total, 5),
            "cost_ratio": round(cost_ratio, 3) if cost_ratio is not None else None,
            "ann_sharpe": float(m.sharpe), "sharpe_per_obs": float(m.sharpe_per_obs),
            "deflated_sharpe_prob": round(float(p.deflated_sharpe_prob), 6),
            "pbo": float(m.pbo), "folds_positive": float(m.folds_positive_pct),
            "holdout_dsr": round(float(m.holdout_deflated_sharpe), 6),
            "n_periods": m.num_trades, "max_dd": float(m.max_drawdown),
            "mean_turnover": round(statistics.fmean(res.turnover), 3) if res.turnover else 0.0,
            "win_rate": float(m.win_rate),
            "promoted": p.promoted, "survived_fdr": p.survived_fdr, "reasons": p.reasons,
        })

    mom_p = by_id["perp_momentum_neutral"]
    car_p = by_id["perp_carry_neutral"]
    any_real = mom_p.promoted or car_p.promoted
    placebo_promoted = by_id["momentum_placebo"].promoted or by_id["carry_placebo"].promoted
    if any_real and not placebo_promoted:
        which = []
        if mom_p.promoted:
            which.append("cross-sectional momentum")
        if car_p.promoted:
            which.append("funding-carry")
        verdict = "PASS"
        headline = f"{' + '.join(which)} perp L/S-neutral SURVIVED the cohort gate + BH-FDR (q=0.10), placebos rejected"
    else:
        verdict = "FAIL"
        headline = (f"NO perp-neutral construction survived: momentum promoted={mom_p.promoted} "
                    f"(DSR={mom_p.deflated_sharpe_prob:.3f}, {mom_p.reasons}); "
                    f"carry promoted={car_p.promoted} (DSR={car_p.deflated_sharpe_prob:.3f}, {car_p.reasons})")
        if placebo_promoted:
            headline += " | WARNING: a PLACEBO promoted -> machinery suspect"
    return Verdict(len(panel.times), n_sym, window, candidates=rows, verdict=verdict, headline=headline)


def _print(v: Verdict) -> None:
    print(f"\n=== PERP MARKET-NEUTRAL COHORT — {v.verdict} ===")
    print(f"  periods={v.n_periods}  symbols={v.n_symbols}  window={v.window}")
    print(f"  fees: perp taker {PERP_FEE_PER_SIDE*1e4:.0f} bps/side on realized turnover; funding accrued per bar (real)")
    print("  construction: dollar-neutral (Sum w = 0, Sum |w| = 1) long top / short bottom; hurdle = cash (0)")
    for r in v.candidates:
        flag = "PROMOTED" if r["promoted"] else ("fdr-only" if r["survived_fdr"] else "stop")
        print(f"  [{flag:>9}] {r['name']:<22} net={r['net_total_return']:+.4f} "
              f"gross={r['gross_total_return']:+.4f} cost_ratio={r['cost_ratio']} "
              f"annSR={r['ann_sharpe']:+.2f} DSR={r['deflated_sharpe_prob']:.3f} holdoutDSR={r['holdout_dsr']:+.4f} "
              f"pbo={r['pbo']:.2f} folds+={r['folds_positive']:.2f} maxDD={r['max_dd']:.3f} "
              f"turn={r['mean_turnover']:.2f} win={r['win_rate']:.2f} fdr={'Y' if r['survived_fdr'] else 'N'} "
              f"n={r['n_periods']}")
        if r["reasons"]:
            print(f"               reasons: {', '.join(r['reasons'])}")
    if v.notes:
        for n in v.notes:
            print(f"  note: {n}")
    print(f"  HEADLINE: {v.headline}")


def main() -> int:
    """Offline run: cached REAL perp bars + cached REAL funding, the existing scorer/FDR, propose-only. Degrades
    to INSUFFICIENT-DATA when the cache is too thin (never a fabricated pass)."""
    market = load_perp_market()
    funding = CachedFundingRateProvider(cache_dir=FUNDING_CACHE)
    _print(run(market, funding, persist=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
