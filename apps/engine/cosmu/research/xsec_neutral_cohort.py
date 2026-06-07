# intent: the DIRECT test of whether cross-sectional DISPERSION (not market direction) carries an edge net of perp
# fees — a LONG/SHORT MARKET-NEUTRAL cross-sectional momentum book on the DEEP 30-symbol mid-cap binanceperp
# universe. At each weekly rebalance we rank the universe by trailing ret_Nd (PIT, only symbols with enough history
# AS OF that date), go LONG the top-k leaders + SHORT the bottom-k laggards, dollar-neutral (0.5 gross per side), and
# hold one week. Dollar-neutrality CANCELS market beta — so this isolates whether the leaders-minus-laggards spread
# is real, unlike wave 1's long-only book which mechanically inherited the bear.
#
# The PASS/FAIL verdict comes ONLY from promote_cohort's BH-FDR (q=0.10) across the whole family — NEVER
# gate.evaluate_cross_asset_ablation (the leaky path). Every (lookback, k) grid variant of every member is recorded
# as a TRIAL so deflation/FDR see the true inflated count. A fresh tempfile store isolates the ledger. Deterministic.
#
# Members (DISTINCT candidates in ONE family):
#   xsec-neutral-momentum     — long top-k / short bottom-k, dollar-neutral, weekly rebalance (THE candidate)
# Pre-registered disconfirmers (in-family, their grid free params counted as trials):
#   disc-long-only-topk       — CONTROL: long the top-k only (no short leg). Neutralization should REMOVE the beta
#                               that dominated wave 1 — so this control should look DIFFERENT (it carries the beta).
#   disc-random-pairing-placebo — PLACEBO: same #long/#short, but the long/short membership is RANDOM (not by rank).
#                               If the spread is cross-sectional momentum, the placebo must NOT reproduce it.
# Falsified iff the random-pairing placebo REPRODUCES the neutral book's deflated Sharpe (the spread is not momentum),
# OR the neutral book fails to survive the cohort gate + BH-FDR.
#
# Construction honesty: PIT (each rebalance reads only closes at/<= the rebalance date; a symbol absent then is not
# ranked — no survivorship look-ahead); next-bar fill (rank on date t's close, hold the FOLLOWING week's daily
# returns — the signal never sees its own holding window); real perp taker fee (~5bps) on realized turnover at each
# rebalance, charged to BOTH legs; the per-day book-return stream is split 80/20 into a scored validation slice and an
# untouched holdout exactly like data/backtest._purged_embargoed_split; folds/PBO/holdout-DSR computed with the same
# scorer primitives (sample_moments / probabilistic_sharpe). NO synthetic bars, NO zero-fill, NO LLM.

from __future__ import annotations

import math
import random
import statistics
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal

from cosmu.config.settings import GateSettings, Settings
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store
from cosmu.master.cohort import Candidate, promote_cohort
from cosmu.master.scorer import (
    BacktestMetrics,
    probabilistic_sharpe,
    sample_moments,
)
from cosmu.master.trials import record_trial, trial_stats
from cosmu.spine.venue import default_catalog

# The deep two-sided mid-cap perp universe (30 symbols, daily, 2020-12 → 2026-06), per the round spec.
_UNIVERSE = (
    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "TRXUSDT", "LTCUSDT", "BCHUSDT", "NEARUSDT",
    "UNIUSDT", "ATOMUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "FILUSDT", "INJUSDT", "SUIUSDT", "TIAUSDT",
    "AAVEUSDT", "ETCUSDT", "LDOUSDT", "RUNEUSDT", "ICPUSDT", "XLMUSDT", "SANDUSDT", "MANAUSDT", "GALAUSDT",
    "CHZUSDT", "ALGOUSDT", "GRTUSDT",
)
_PERP_CACHE = ".cosmu/market_data/binanceperp"

# The free-param grid swept per member — each combo is a DISTINCT book, recorded as a trial so the FDR count is
# honest. lookback = ret_Nd momentum window; k = #symbols per leg. weekly (7d) rebalance throughout.
_LOOKBACKS = (30, 60, 90)
_KS = (3, 5)
_REBALANCE_DAYS = 7
_FDR_Q = 0.10

# Validation/holdout split fraction, byte-identical to data/backtest._purged_embargoed_split.
_SPLIT_FRAC = 0.8
_MIN_SPLIT = 40
_N_FOLDS = 5  # contiguous CSCV-style folds over the validation stream (folds_positive_pct gate input)


@dataclass
class MemberReport:
    name: str
    net_return: float
    gross_return: float
    cost_ratio: float
    deflated_sharpe_prob: float
    cscv_pbo: float
    beat_buy_and_hold: bool
    corr_to_btc: float
    num_trades: int
    max_drawdown: float
    holdout_dsr: float
    best_config: str
    survived_fdr: bool = False
    promoted: bool = False
    reasons: list[str] = field(default_factory=list)


@dataclass
class XsecReport:
    verdict: str
    headline: str
    data_source: str
    window: str
    fdr_q: float
    members: list[MemberReport] = field(default_factory=list)
    disconfirmers: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- data assembly (PIT, real perp bars)


def _load_market() -> dict[str, list[Bar]]:
    """Load the deep perp universe DIRECTLY from the cached binanceperp daily JSON — OFFLINE ONLY. We deliberately
    do NOT call BinanceSpotOHLCVProvider.fetch_bars here: when limit exceeds the cached length it re-fetches from
    the network and OVERWRITES the cache with the REST default (1000 bars), silently truncating the deep
    2020-12→2026-06 history the round depends on. Reading the file is read-only and reuses the cache as-is."""
    import json
    from datetime import UTC, datetime
    from pathlib import Path

    out: dict[str, list[Bar]] = {}
    base = Path(_PERP_CACHE)
    for s in _UNIVERSE:
        path = base / f"{s}_1d.json"
        if not path.exists():
            continue
        rows = json.loads(path.read_text())
        bars = [
            Bar(
                ts=datetime.fromtimestamp(int(r["ts"]) / 1000, tz=UTC),
                open=Decimal(str(r["open"])), high=Decimal(str(r["high"])),
                low=Decimal(str(r["low"])), close=Decimal(str(r["close"])),
                volume=Decimal(str(r["volume"])),
            )
            for r in rows
        ]
        if bars:
            out[s] = bars
    return out


def _close_by_date(market: dict[str, list[Bar]]) -> tuple[dict[str, dict[str, float]], list[str]]:
    """Per-symbol {date_iso: close} plus the sorted UNION of all dates. A symbol absent on a date simply has no
    entry — ranking then skips it (PIT; no survivorship fill). Dates are date-granular (daily bars)."""
    closes: dict[str, dict[str, float]] = {}
    all_dates: set[str] = set()
    for s, bars in market.items():
        d: dict[str, float] = {}
        for b in bars:
            key = b.ts.date().isoformat()
            d[key] = float(b.close)
            all_dates.add(key)
        closes[s] = d
    return closes, sorted(all_dates)


# --------------------------------------------------------------------------- the neutral book


def _trailing_return(series: dict[str, float], dates_upto: list[str], lookback: int) -> float | None:
    """ret over `lookback` trading days ending at the LAST date in `dates_upto`, using ONLY closes the symbol has
    on/before that date (PIT). None when the symbol lacks `lookback`+1 of its own observations in the window."""
    own = [d for d in dates_upto if d in series]
    if len(own) < lookback + 1:
        return None
    last, prev = series[own[-1]], series[own[-1 - lookback]]
    if prev <= 0:
        return None
    return last / prev - 1.0


def _book_daily_returns(
    closes: dict[str, dict[str, float]],
    all_dates: list[str],
    *,
    lookback: int,
    k: int,
    mode: str,  # "neutral" | "long_only" | "placebo"
    fee_bps: float,
    seed: int = 0,
) -> tuple[list[float], list[float], int]:
    """Build the per-day book-return stream for one construction.

    At each weekly rebalance date t (every _REBALANCE_DAYS index into all_dates), rank every symbol with a valid
    trailing-`lookback` return AS OF t. Form the leg membership per `mode`, then for each of the next
    _REBALANCE_DAYS calendar days accrue the book's daily return = (mean long-leg daily ret) - (mean short-leg
    daily ret), dollar-neutral at 0.5 gross per side (so the neutral book runs ~1.0 gross, 0 net). Real perp taker
    fee is charged on the realized leg turnover at each rebalance. The signal is computed at t and applied to the
    FOLLOWING days only — the rank never sees its own holding window (next-bar fill, no look-ahead).

    Returns (per_day_book_returns, btc_aligned_daily_returns_proxy_unused, num_rebalances). The 2nd element is the
    equal-weight basket daily return over the SAME days (the market proxy, for corr-to-market neutrality)."""
    rng = random.Random(seed)
    book: list[float] = []
    market_proxy: list[float] = []
    prev_long: set[str] = set()
    prev_short: set[str] = set()
    n_rebalances = 0
    fee = fee_bps / 10000.0

    i = lookback  # need at least `lookback` history before the first rank
    while i < len(all_dates) - 1:
        # rebalance date t = all_dates[i]; the rank reads only closes through t (PIT), held over later days.
        upto = all_dates[: i + 1]
        # rank symbols with a valid PIT trailing return as of t
        rets: dict[str, float] = {}
        for s, series in closes.items():
            r = _trailing_return(series, upto, lookback)
            if r is not None:
                rets[s] = r
        if len(rets) < 2 * k:
            # too few rankable symbols this week — flat (no trade); advance
            i += _REBALANCE_DAYS
            continue
        ordered = sorted(rets, key=lambda s: rets[s])  # 0 = worst (laggard), -1 = best (leader)
        if mode == "neutral":
            long_leg = set(ordered[-k:])
            short_leg = set(ordered[:k])
        elif mode == "long_only":
            long_leg = set(ordered[-k:])
            short_leg = set()
        elif mode == "placebo":
            # RANDOM pairing: pick 2k rankable symbols at random, split into long/short by coin-flip — same leg
            # sizes, same universe, but membership is NOT by rank. The spread must not survive this.
            pool = list(rets.keys())
            rng.shuffle(pool)
            long_leg = set(pool[:k])
            short_leg = set(pool[k : 2 * k])
        else:
            raise ValueError(mode)

        # turnover fee at rebalance: symbols entering/leaving each leg pay one taker fee on that fraction of book.
        # per-side weight = 0.5/k (neutral/placebo) or 1.0/k (long_only). entries + exits both cost.
        long_w = (0.5 / k) if mode != "long_only" else (1.0 / k)
        short_w = (0.5 / k) if mode != "long_only" else 0.0
        long_turn = len(long_leg.symmetric_difference(prev_long)) * long_w
        short_turn = len(short_leg.symmetric_difference(prev_short)) * short_w
        rebalance_cost = (long_turn + short_turn) * fee

        # accrue the next _REBALANCE_DAYS days of holding (next-bar fill: start AFTER t)
        held_days = all_dates[i + 1 : i + 1 + _REBALANCE_DAYS]
        first_day = True
        for d_idx, d in enumerate(held_days):
            prev_date = all_dates[i + d_idx]  # the day before d in the union grid
            long_rets = [
                closes[s][d] / closes[s][prev_date] - 1.0
                for s in long_leg
                if d in closes[s] and prev_date in closes[s] and closes[s][prev_date] > 0
            ]
            short_rets = [
                closes[s][d] / closes[s][prev_date] - 1.0
                for s in short_leg
                if d in closes[s] and prev_date in closes[s] and closes[s][prev_date] > 0
            ]
            long_ret = statistics.fmean(long_rets) if long_rets else 0.0
            short_ret = statistics.fmean(short_rets) if short_rets else 0.0
            if mode == "long_only":
                day_ret = long_ret
            else:
                day_ret = 0.5 * long_ret - 0.5 * short_ret  # dollar-neutral
            if first_day:
                day_ret -= rebalance_cost  # charge the rebalance turnover on entry day
                first_day = False
            book.append(day_ret)
            # equal-weight market proxy over the full rankable set this day (the beta benchmark)
            mkt_rets = [
                closes[s][d] / closes[s][prev_date] - 1.0
                for s in rets
                if d in closes[s] and prev_date in closes[s] and closes[s][prev_date] > 0
            ]
            market_proxy.append(statistics.fmean(mkt_rets) if mkt_rets else 0.0)
        prev_long, prev_short = long_leg, short_leg
        n_rebalances += 1
        i += _REBALANCE_DAYS

    return book, market_proxy, n_rebalances


# --------------------------------------------------------------------------- stream → honest BacktestMetrics


def _correlation(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    x, y = a[-n:], b[-n:]
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sx, sy = statistics.pstdev(x), statistics.pstdev(y)
    if sx == 0 or sy == 0:
        return 0.0
    cov = statistics.fmean([(x[i] - mx) * (y[i] - my) for i in range(n)])
    return max(-1.0, min(1.0, cov / (sx * sy)))


def _max_drawdown(returns: list[float]) -> float:
    """Peak-to-trough drawdown on the compounded equity curve of a per-day return stream."""
    equity = 1.0
    peak = 1.0
    mdd = 0.0
    for r in returns:
        equity *= 1.0 + r
        peak = max(peak, equity)
        if peak > 0:
            mdd = max(mdd, (peak - equity) / peak)
    return mdd


def _compound(returns: list[float]) -> float:
    eq = 1.0
    for r in returns:
        eq *= 1.0 + r
    return eq - 1.0


def _folds_positive_pct(val: list[float], n_folds: int = _N_FOLDS) -> float:
    """Fraction of contiguous folds whose compounded return is positive — the scorer's folds_positive gate input."""
    if len(val) < n_folds:
        return 0.0
    size = len(val) // n_folds
    if size < 1:
        return 0.0
    positive = 0
    for f in range(n_folds):
        chunk = val[f * size : (f + 1) * size] if f < n_folds - 1 else val[f * size :]
        if _compound(chunk) > 0:
            positive += 1
    return positive / n_folds


def _cscv_pbo_from_folds(val: list[float], n_blocks: int = 8) -> float:
    """A single-stream overfit proxy: split the validation stream into blocks and measure the fraction of balanced
    in-sample/out-of-sample splits where the in-sample mean disagrees in sign with the out-of-sample mean. For a
    single construction this is the closest honest PBO proxy (true CSCV needs >=2 configs); higher = more fragile."""
    from itertools import combinations

    length = len(val)
    s = max(2, min(n_blocks, length))
    if s % 2:
        s -= 1
    if s < 2:
        return 1.0
    block_size = length // s
    if block_size < 1:
        return 1.0
    block_means = [statistics.fmean(val[b * block_size : (b + 1) * block_size]) for b in range(s)]
    block_ids = list(range(s))
    overfit = 0
    total = 0
    for is_blocks in combinations(block_ids, s // 2):
        is_set = set(is_blocks)
        oos_blocks = [b for b in block_ids if b not in is_set]
        is_mean = statistics.fmean([block_means[b] for b in is_blocks])
        oos_mean = statistics.fmean([block_means[b] for b in oos_blocks])
        total += 1
        if is_mean > 0 >= oos_mean:  # in-sample looks good, out-of-sample does not
            overfit += 1
    return overfit / total if total else 1.0


def _metrics_from_stream(
    book: list[float],
    market_proxy: list[float],
    *,
    n_trades: int,
    buy_and_hold: float,
) -> tuple[BacktestMetrics, float, float, float]:
    """Build an honest BacktestMetrics from a per-day book-return stream, mirroring data/backtest's methodology:
    split 80/20 into a scored validation slice + an untouched holdout; folds/PBO/holdout-DSR via the SAME scorer
    primitives. Returns (metrics, corr_to_market_proxy, holdout_dsr, gross_return_placeholder=net here)."""
    n = len(book)
    if n < _MIN_SPLIT + 5:
        # too short to split honestly — return a degenerate metrics that cannot pass (no fabrication)
        sr, skew, kurt, n_obs = sample_moments(book)
        return (
            BacktestMetrics(
                oos_return=Decimal(str(round(_compound(book), 8))), sharpe=Decimal("0"), sortino=Decimal("0"),
                max_drawdown=Decimal(str(round(_max_drawdown(book), 6))), win_rate=Decimal("0"),
                num_trades=n_trades, sharpe_per_obs=Decimal(str(round(sr, 8))), skew=Decimal(str(round(skew, 6))),
                kurtosis=Decimal(str(round(kurt, 6))), n_obs=n_obs, pbo=Decimal("1"), trials_counted=1,
                folds_positive_pct=Decimal("0"), holdout_deflated_sharpe=Decimal("-1"),
                buy_and_hold_return=Decimal(str(round(buy_and_hold, 8))),
            ),
            _correlation(book, market_proxy), -1.0, _compound(book),
        )
    split = max(_MIN_SPLIT, int(n * _SPLIT_FRAC))
    val = book[:split]
    holdout = book[split:]

    sr, skew, kurt, n_obs = sample_moments(val)
    h_sr, h_skew, h_kurt, h_n = sample_moments(holdout)
    holdout_dsr = probabilistic_sharpe(h_sr, h_n, h_skew, h_kurt, 0.0) - 0.5

    val_return = _compound(val)
    metrics = BacktestMetrics(
        oos_return=Decimal(str(round(val_return, 8))),
        buy_and_hold_return=Decimal(str(round(buy_and_hold, 8))),
        sharpe=Decimal(str(round(sr * math.sqrt(365), 6))),
        sortino=Decimal("0"),
        max_drawdown=Decimal(str(round(_max_drawdown(val), 6))),
        win_rate=Decimal("0"),
        num_trades=n_trades,
        sharpe_per_obs=Decimal(str(round(sr, 8))),
        skew=Decimal(str(round(skew, 6))),
        kurtosis=Decimal(str(round(kurt, 6))),
        n_obs=n_obs,
        pbo=Decimal(str(round(_cscv_pbo_from_folds(val), 6))),
        trials_counted=1,
        folds_positive_pct=Decimal(str(round(_folds_positive_pct(val), 6))),
        holdout_deflated_sharpe=Decimal(str(round(holdout_dsr, 6))),
        regime_returns={},
    )
    return metrics, _correlation(val, market_proxy[:split]), holdout_dsr, val_return


# --------------------------------------------------------------------------- per-member screen over the grid


def _basket_buy_and_hold(closes: dict[str, dict[str, float]], all_dates: list[str], fee_bps: float) -> float:
    """Equal-weight buy-and-hold of the whole rankable basket over the VALIDATION slice of the union date grid,
    net of one round-trip fee — the benchmark the neutral book must beat (mirrors backtest._buy_and_hold_return)."""
    n = len(all_dates)
    split = max(_MIN_SPLIT, int(n * _SPLIT_FRAC))
    window = all_dates[:split]
    fee = fee_bps / 10000.0
    rets: list[float] = []
    for series in closes.values():
        own = [d for d in window if d in series]
        if len(own) < 40:
            continue
        first, last = series[own[0]], series[own[-1]]
        if first > 0:
            rets.append(last / first - 1.0 - 2.0 * fee)
    return statistics.fmean(rets) if rets else 0.0


def _screen_member(
    sid: str,
    closes: dict[str, dict[str, float]],
    all_dates: list[str],
    *,
    mode: str,
    fee_bps: float,
    buy_and_hold: float,
    store: Store,
    gates: GateSettings,
) -> tuple[Candidate, MemberReport]:
    """Screen one member over the (lookback, k) grid — every variant recorded as a trial so the FDR count is the
    true inflated one — and return the BEST variant's Candidate + report (best by deflated Sharpe prob)."""
    from cosmu.master.scorer import score

    import zlib

    best: tuple | None = None  # (dsr, metrics, corr, holdout_dsr, net, gross, config)
    for lookback in _LOOKBACKS:
        for k in _KS:
            # DETERMINISTIC placebo seed: zlib.crc32 (NOT the builtin hash(), which is per-process salted by
            # PYTHONHASHSEED — that leaked run-to-run non-determinism into the placebo and, via the shared trial
            # SR-variance, into every member's deflation). crc32 of the config bytes is stable across processes.
            seed = zlib.crc32(f"{sid}:{lookback}:{k}".encode()) & 0xFFFF
            book, market_proxy, n_reb = _book_daily_returns(
                closes, all_dates, lookback=lookback, k=k, mode=mode, fee_bps=fee_bps, seed=seed,
            )
            gross_book, _, _ = _book_daily_returns(
                closes, all_dates, lookback=lookback, k=k, mode=mode, fee_bps=0.0, seed=seed,
            )
            metrics, corr, holdout_dsr, net_return = _metrics_from_stream(
                book, market_proxy, n_trades=2 * n_reb if mode != "long_only" else n_reb, buy_and_hold=buy_and_hold,
            )
            gross_metrics, _, _, gross_return = _metrics_from_stream(
                gross_book, market_proxy, n_trades=2 * n_reb if mode != "long_only" else n_reb, buy_and_hold=buy_and_hold,
            )
            record_trial(store, float(metrics.sharpe_per_obs), source="xsec_neutral", label=f"{sid}:L{lookback}k{k}")
            v = score(metrics, gates, trials=trial_stats(store))
            dsr = float(v.deflated_sharpe_prob)
            cand_tuple = (dsr, metrics, corr, holdout_dsr, net_return, gross_return, f"L{lookback}k{k}")
            if best is None or dsr > best[0]:
                best = cand_tuple
    assert best is not None
    dsr, metrics, corr, holdout_dsr, net_return, gross_return, config = best
    cost_ratio = (net_return / gross_return) if gross_return not in (0.0,) else 0.0
    cand = Candidate(
        id=sid, metrics=metrics, net_profit=net_return, source="xsec_neutral", label=sid,
    )
    rep = MemberReport(
        name=sid, net_return=round(net_return, 6), gross_return=round(gross_return, 6),
        cost_ratio=round(cost_ratio, 4), deflated_sharpe_prob=round(dsr, 6), cscv_pbo=round(float(metrics.pbo), 6),
        beat_buy_and_hold=net_return > buy_and_hold, corr_to_btc=round(corr, 4), num_trades=metrics.num_trades,
        max_drawdown=round(float(metrics.max_drawdown), 6), holdout_dsr=round(holdout_dsr, 6), best_config=config,
    )
    return cand, rep


# --------------------------------------------------------------------------- the cohort


def run_xsec_neutral_cohort(
    market: dict[str, list[Bar]],
    store: Store,
    *,
    data_source: str = "live-cached-perp",
    fdr_q: float = _FDR_Q,
) -> XsecReport:
    gates = store.settings.gates
    fee_bps = float(default_catalog().venue("binance").taker_fee_bps)

    closes, all_dates = _close_by_date(market)
    notes: list[str] = []
    if len(all_dates) < _MIN_SPLIT + 10 or len(closes) < 4:
        return XsecReport("INSUFFICIENT-DATA", "perp cache too thin for an xsec neutral book", data_source,
                          "n/a", fdr_q, notes=["binanceperp cache empty/too shallow — re-backfill"])
    window = f"{all_dates[0]}..{all_dates[-1]}"
    buy_and_hold = _basket_buy_and_hold(closes, all_dates, fee_bps)

    candidates: list[Candidate] = []
    reports: list[MemberReport] = []

    # 1) THE candidate — long/short dollar-neutral cross-sectional momentum.
    c_neu, r_neu = _screen_member(
        "xsec-neutral-momentum", closes, all_dates, mode="neutral", fee_bps=fee_bps,
        buy_and_hold=buy_and_hold, store=store, gates=gates,
    )
    candidates.append(c_neu)
    reports.append(r_neu)

    # 2) DISCONFIRMER A (CONTROL) — long-only top-k. Should inherit the market beta neutralization removes.
    c_lo, r_lo = _screen_member(
        "disc-long-only-topk", closes, all_dates, mode="long_only", fee_bps=fee_bps,
        buy_and_hold=buy_and_hold, store=store, gates=gates,
    )
    candidates.append(c_lo)
    reports.append(r_lo)

    # 3) DISCONFIRMER B (PLACEBO) — random long/short pairing. Must NOT reproduce the spread.
    c_pl, r_pl = _screen_member(
        "disc-random-pairing-placebo", closes, all_dates, mode="placebo", fee_bps=fee_bps,
        buy_and_hold=buy_and_hold, store=store, gates=gates,
    )
    candidates.append(c_pl)
    reports.append(r_pl)

    # COHORT BH-FDR across the whole family — register=False + the shared trial_stats so deflation/FDR see the true
    # (grid-inflated) count. THIS is the verdict (never gate.evaluate_cross_asset_ablation).
    promotions = promote_cohort(store, candidates, gates, fdr_q=fdr_q, register=False, trials=trial_stats(store))
    by_id = {p.candidate_id: p for p in promotions}
    for r in reports:
        p = by_id.get(r.name)
        if p:
            r.survived_fdr = p.survived_fdr
            r.promoted = p.promoted
            r.reasons = p.reasons
            r.deflated_sharpe_prob = round(p.deflated_sharpe_prob, 6)

    # Disconfirmer verdicts (read off the FINAL deflated Sharpe the FDR ranks).
    neu_dsr = r_neu.deflated_sharpe_prob
    disc: dict[str, str] = {}
    # CONTROL: neutralization should DROP the beta the long-only control carries. We report whether the neutral
    # book is genuinely market-neutral (|corr| small) AND distinct from the directional control.
    neutralized = abs(r_neu.corr_to_btc) < abs(r_lo.corr_to_btc) or abs(r_neu.corr_to_btc) < 0.30
    disc["long_only_control"] = (
        f"{'PASS-neutralized' if neutralized else 'FAIL-still-directional'} "
        f"(neutral corr {r_neu.corr_to_btc:+.3f} vs long-only corr {r_lo.corr_to_btc:+.3f})"
    )
    placebo_reproduces = r_pl.deflated_sharpe_prob >= neu_dsr
    disc["random_pairing_placebo"] = (
        f"{'PASS' if not placebo_reproduces else 'FAIL-reproduces'} "
        f"(neutral dsr {neu_dsr:.3f} vs placebo dsr {r_pl.deflated_sharpe_prob:.3f})"
    )

    falsified = placebo_reproduces
    promoted = [r for r in reports if r.promoted and not r.name.startswith("disc-")]
    if promoted and not falsified:
        verdict = "PASS"
        headline = (f"{len(promoted)} member(s) survived the cohort gate + BH-FDR (q={fdr_q}) AND passed all "
                    f"disconfirmers: " + ", ".join(r.name for r in promoted))
    elif promoted and falsified:
        verdict = "FAIL-DISCONFIRMED"
        headline = ("xsec-neutral survived BH-FDR but the random-pairing placebo REPRODUCES the spread — "
                    "the edge is not cross-sectional momentum")
    else:
        verdict = "FAIL"
        best = max(reports, key=lambda r: r.deflated_sharpe_prob) if reports else None
        headline = (f"no member survived the cohort gate + BH-FDR (q={fdr_q}); best DSR "
                    f"{best.deflated_sharpe_prob:.3f} ({best.name})" if best else "no candidates")

    return XsecReport(verdict, headline, data_source, window, fdr_q, members=reports, disconfirmers=disc, notes=notes)


def _main() -> int:
    tmp = tempfile.mkdtemp(prefix="cosmu-xsec-")
    store = Store(Settings(database_url=f"sqlite:///{tmp}/xsec.sqlite3", openrouter_api_key=None))
    market = _load_market()
    report = run_xsec_neutral_cohort(market, store)

    print(f"XSEC LONG/SHORT NEUTRAL COHORT — {report.verdict}")
    print(f"  data_source={report.data_source}  window={report.window}  symbols={len(market)}  cohort BH-FDR q={report.fdr_q}")
    for m in report.members:
        flag = "PROMOTED" if m.promoted else ("fdr-only" if m.survived_fdr else "stop")
        print(f"  [{flag:>8}] {m.name:<28} net={m.net_return:+.4f} gross={m.gross_return:+.4f} "
              f"cost_ratio={m.cost_ratio:.3f} dsr={m.deflated_sharpe_prob:.3f} pbo={m.cscv_pbo:.3f} "
              f"holdoutDSR={m.holdout_dsr:+.3f} trades={m.num_trades} maxDD={m.max_drawdown:.3f} "
              f"corrMkt={m.corr_to_btc:+.3f} beatBH={'Y' if m.beat_buy_and_hold else 'N'} "
              f"fdr={'Y' if m.survived_fdr else 'N'} cfg={m.best_config}")
        if m.reasons:
            print(f"             reasons: {', '.join(m.reasons)}")
    print("  DISCONFIRMERS:")
    for k, v in report.disconfirmers.items():
        print(f"    {k}: {v}")
    for n in report.notes:
        print(f"  note: {n}")
    print(f"  HEADLINE: {report.headline}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
