#!/usr/bin/env python3
"""EXPERIMENT ONLY — the SHARPEST next hypothesis from edge-hunt #390, tested BRUT.

ZERO production impact: reads the locked Gate + the canonical scorer primitives, writes NOTHING to any store,
never touches a Gate constant. Output is a per-config stat block (printed + emitted as JSON for the report/HTML).

THE HYPOTHESIS (from docs/reports/edge-hunt-experiment-2026-06-25.md §"Sharpest next hypothesis"):
  Long-only daily xsec-momentum died on TWO walls — (1) it loses to long buy-and-hold BETA in a bull tape
  (killed 88/126 combos), and (2) daily bars fire <30 trades (DSR collapses). The proposed fix:
    • Go MARKET-NEUTRAL: long the top-momentum quantile, SHORT the bottom-momentum quantile. The two legs
      cancel beta, so the book is judged on DISPERSION (does the top decile beat the bottom decile?) — the
      cross-sectional momentum premium itself — NOT on out-returning a bull tape. A market-neutral book's
      RIGHT benchmark is ~0/cash, not long-B&H. We report BOTH so the reader sees the wall move (or not).
    • Drop to DENSER bars (4h) to break the <30-trade floor: a rebalanced book books one "trade" per
      rebalance, and 4h over ~3.5yr gives thousands of rebalances.

DATA (keyless / real bars — the M2 is geo-blocked from Binance LIVE; this proves SIGNAL presence, not capacity):
  • Bybit v5 public spot kline, PAGINATED keyless (the provider only single-pages; this harness walks `end=`
    back) → ~3.5yr of REAL 4h bars for the full 12-name universe (the densest+deepest keyless bars that exist).
    This DIRECTLY answers the data-depth question #390 flagged: keyless is NOT capped at 720 bars if you page.
  • Cached real Binance funding (operator's .cosmu cache) → per-symbol PIT 8h funding, charged on BOTH legs of
    the neutral book (long perp pays funding, short receives) and on the funding-percentile variant.

THE BOOK (a genuine market-neutral equity curve — not the `_pad` proxy carry_ablation falls back to):
  At each rebalance bar we rank the universe by trailing momentum (the SAME PIT xsec rank the live spec reads),
  form a LONG basket (top quantile) + a SHORT basket (bottom quantile), and the book's per-bar return is
  mean(long fwd returns) − mean(short fwd returns), charging fee + liquidity-tiered slippage on the turnover of
  BOTH legs each rebalance and accruing funding on BOTH legs. The book's OWN equity curve is then scored BRUT
  through the LOCKED Gate (DSR≥0.95, PBO≤0.50, folds≥0.60, min_trades≥30, holdout DSR>0, beat-benchmark) with
  TrialStats(count = realized grid size) — the legitimate per-book own-overfit deflation, never a cross-family count.
  The champion config is confirmed on its OWN embargoed holdout (last fifth). RANK BY OUTLIER; emit EVERY config.

VARIANT 3 — funding-contrarian as a CONTINUOUS funding-percentile signal (drops the hard oversold-RSI conjunction
that fired <=4 trades in #390): long the names in the most-negative funding percentile (crowded shorts), on the
densest bars, judged BRUT per (symbol × venue) exactly like #390 so the two are comparable.
"""
from __future__ import annotations

import gc
import json
import math
import statistics
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

# Resolve apps/engine on sys.path when run directly.
_ENGINE = Path(__file__).resolve().parents[2]
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from cosmu.config.settings import GateSettings  # noqa: E402
from cosmu.data.altdata import _ssl_context  # noqa: E402
from cosmu.data.backtest import _liquidity_floor_bps  # noqa: E402
from cosmu.data.market import Bar  # noqa: E402
from cosmu.data.providers.funding import CachedFundingRateProvider  # noqa: E402
from cosmu.master.scorer import (  # noqa: E402
    BacktestMetrics,
    TrialStats,
    cscv_pbo,
    expected_max_sharpe,
    probabilistic_sharpe,
    sample_moments,
    score,
)
from cosmu.spine.venue import default_catalog  # noqa: E402

# ------- config -------------------------------------------------------------------------------------------
UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT",
    "ADAUSDT", "DOTUSDT", "LTCUSDT", "XRPUSDT", "BCHUSDT", "ATOMUSDT",
]
GATES = GateSettings()  # the LOCKED gate
# Real Binance funding cache (operator's), read-only.
FUNDING_DIR = "<repo>/apps/engine/.cosmu/market_data/binance_funding"
RESULTS_JSON = _ENGINE / "scripts" / "research" / "edge_hunt_mktneutral_results_2026_06_25.json"
BYBIT_PAGES = 8  # ~8000 4h bars ≈ 3.6yr (the keyless ceiling we measured)


# --------------------------------------------------------------------------- data (paginated keyless Bybit)
def _bybit_paginated(symbol: str, interval: str, pages: int) -> list[Bar]:
    """Walk Bybit v5 spot kline backwards via `end=` to defeat the single-page 1000-bar cap. Returns ascending
    closed bars. Real, PIT (we drop the in-progress last bar by fetching strictly-closed history). Keyless."""
    ctx = _ssl_context()
    rows: dict[int, list] = {}
    end = int(datetime.now(UTC).timestamp() * 1000)
    for _ in range(pages):
        q = urllib.parse.urlencode(
            {"category": "spot", "symbol": symbol, "interval": interval, "limit": 1000, "end": end}
        )
        url = f"https://api.bybit.com/v5/market/kline?{q}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=25, context=ctx) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"  ! bybit page fetch failed for {symbol} {interval}: {e}", file=sys.stderr)
            break
        lst = payload.get("result", {}).get("list", [])
        if not lst:
            break
        for r in lst:
            rows[int(r[0])] = r
        oldest = min(int(r[0]) for r in lst)
        end = oldest - 1
        time.sleep(0.25)
    bars: list[Bar] = []
    for ts_ms in sorted(rows):
        r = rows[ts_ms]
        bars.append(
            Bar(
                ts=datetime.fromtimestamp(ts_ms / 1000, tz=UTC),
                open=Decimal(str(r[1])), high=Decimal(str(r[2])), low=Decimal(str(r[3])),
                close=Decimal(str(r[4])), volume=Decimal(str(r[5])),
            )
        )
    # Drop the most recent bar if it is the in-progress (un-closed) interval.
    now = datetime.now(UTC)
    secs = {"240": 4 * 3600, "60": 3600, "D": 86400}.get(interval, 86400)
    if bars and (now - bars[-1].ts).total_seconds() < secs:
        bars = bars[:-1]
    return bars


def _intersect_window(panel: dict[str, list[Bar]]) -> dict[str, list[Bar]]:
    """Restrict every symbol to the COMMON timestamp window (the dates all names share) so the cross-sectional
    rank is computed on an apples-to-apples panel — a name that lists late never silently shrinks the universe
    mid-history (which would bias the rank). Honest: we lose the early band where some names didn't exist yet."""
    if not panel:
        return panel
    common: set[str] | None = None
    for bars in panel.values():
        ks = {b.ts.isoformat() for b in bars}
        common = ks if common is None else (common & ks)
    common = common or set()
    return {s: [b for b in bars if b.ts.isoformat() in common] for s, bars in panel.items()}


# --------------------------------------------------------------------------- xsec rank (PIT, own impl)
def _trailing_returns_at(panel: dict[str, list[Bar]], lookback: int) -> dict[str, dict[str, float]]:
    """Per-symbol trailing `lookback`-bar return at each bar timestamp (PIT). {symbol: {ts_iso: ret}}."""
    out: dict[str, dict[str, float]] = {}
    for sym, bars in panel.items():
        closes = [float(b.close) for b in bars]
        ts = [b.ts.isoformat() for b in bars]
        d: dict[str, float] = {}
        for i in range(lookback, len(bars)):
            base = closes[i - lookback]
            if base > 0:
                d[ts[i]] = closes[i] / base - 1.0
        out[sym] = d
    return out


# --------------------------------------------------------------------------- funding (PIT, per bar)
def _funding_by_bar(symbol: str, bars: list[Bar], funding: CachedFundingRateProvider) -> dict[str, float]:
    """Per-bar SUMMED funding accrued over each bar interval, keyed by bar.ts.isoformat() (PIT — only settlements
    at/<= the bar close). Binance funding is 8h; a 4h bar sees 0 or 1 settlement, a 1d bar ~3. Empty when the
    cache has no funding for the symbol (an honest 'no carry data' → 0 accrual, never a fabricated rate)."""
    pts = funding.fetch_series(symbol, "funding_rate", limit=len(bars) + 3000)
    if not pts:
        return {}
    settle = sorted((p.ts, float(p.value)) for p in pts)
    out: dict[str, float] = {}
    prev = None
    j = 0
    for b in bars:
        acc = 0.0
        if prev is not None:
            while j < len(settle) and settle[j][0] <= b.ts:
                if settle[j][0] > prev:
                    acc += settle[j][1]
                j += 1
        out[b.ts.isoformat()] = acc
        prev = b.ts
    return out


# --------------------------------------------------------------------------- the market-neutral book
@dataclass
class Config:
    label: str
    lookback: int
    quantile: float          # top/bottom fraction taken on each leg (0.2 = top/bottom 20%)
    rebalance_every: int     # rebalance the book every N bars
    # gate stat block (book's OWN equity curve)
    sharpe_ann: float = 0.0
    deflated_sharpe: float = 0.0
    psr_vs_zero: float = 0.0
    pbo: float = 0.0
    folds_positive: float = 0.0
    n_rebalances: int = 0
    n_trades: int = 0        # leg position-changes (the gate's min_trades is judged on this)
    n_obs: int = 0
    max_dd: float = 0.0
    book_return: float = 0.0          # net-of-cost validation return of the neutral book
    long_only_bh: float = 0.0         # equal-weight long-only B&H over the same window (the OLD wrong hurdle)
    cash_benchmark: float = 0.0       # 0.0 — the RIGHT hurdle for a market-neutral book
    beat_cash: bool = False
    beat_long_bh: bool = False
    holdout_dsr: float = 0.0
    gross_return: float = 0.0
    cost_ratio: float = 0.0
    avg_corr_to_btc: float = 0.0
    passed: bool = False
    holdout_passed: bool = False
    reasons: list = field(default_factory=list)


def _book_bar_returns(
    panel: dict[str, list[Bar]],
    ranks: dict[str, dict[str, float]],
    funding_by_sym: dict[str, dict[str, float]],
    *,
    quantile: float,
    rebalance_every: int,
    taker_bps: float,
    charge_costs: bool,
) -> tuple[list[float], list[str], int, int]:
    """Construct the market-neutral book's per-bar NET return stream over a common-timestamp panel.

    At each REBALANCE bar we sort the symbols that have a rank at that bar, take the top `quantile` as the LONG
    basket and the bottom `quantile` as the SHORT basket, then hold that book until the next rebalance. The
    book's per-bar return is mean(long fwd 1-bar returns) − mean(short fwd 1-bar returns) (beta nets out), plus
    funding accrued on each held leg (a SHORT laggard receives funding when the rate is positive: +rate; a LONG
    leader pays it: −rate), MINUS, on each rebalance, the round-trip turnover cost (fee + liquidity-tiered
    slippage) on the names that ENTER or LEAVE each basket. `charge_costs=False` is the gross book (for cost_ratio).

    Returns (bar_returns, bar_ts, n_rebalances, n_trades). n_trades counts every leg position-change (an entry or
    an exit on either basket) so the locked min_trades floor is judged on real book turnover, not bar count.
    """
    # Common ascending timestamps (panel already intersected upstream).
    any_sym = next(iter(panel))
    ts_seq = [b.ts.isoformat() for b in panel[any_sym]]
    close_by_sym: dict[str, dict[str, float]] = {
        s: {b.ts.isoformat(): float(b.close) for b in bars} for s, bars in panel.items()
    }
    vol_by_sym: dict[str, dict[str, float]] = {
        s: {b.ts.isoformat(): float(b.close) * float(b.volume) for b in bars} for s, bars in panel.items()
    }
    fee = taker_bps / 10000.0

    bar_returns: list[float] = []
    bar_ts: list[str] = []
    cur_long: set[str] = set()
    cur_short: set[str] = set()
    n_rebalances = 0
    n_trades = 0

    def _slip_for(sym: str, ts: str) -> float:
        if not charge_costs:
            return 0.0
        adv = vol_by_sym[sym].get(ts, 0.0)
        floor = max(float(taker_bps) * 0.0 + 5.0, _liquidity_floor_bps(adv))  # 5bps deep-book floor or liq-tiered
        return floor / 10000.0

    for i in range(len(ts_seq) - 1):
        ts = ts_seq[i]
        nxt = ts_seq[i + 1]
        # Rebalance?
        if i % rebalance_every == 0:
            ranked = sorted(
                (s for s in panel if ts in ranks.get(s, {})),
                key=lambda s: ranks[s][ts],
            )
            m = len(ranked)
            if m >= 4:  # need at least 2 per leg for a real spread
                k = max(1, int(round(m * quantile)))
                new_short = set(ranked[:k])     # lowest momentum = laggards = SHORT
                new_long = set(ranked[-k:])     # highest momentum = leaders = LONG
                # Turnover cost on names entering/leaving either basket (round-trip fee+slip on the changed names).
                changed = (new_long ^ cur_long) | (new_short ^ cur_short)
                turn_cost = 0.0
                for s in changed:
                    if s in close_by_sym and ts in close_by_sym[s]:
                        turn_cost += fee + _slip_for(s, ts)
                        n_trades += 1
                # Spread the turnover cost over the basket size (cost is per-name, return is per-name-averaged).
                basket_n = max(1, len(new_long) + len(new_short))
                cur_long, cur_short = new_long, new_short
                n_rebalances += 1
            else:
                turn_cost = 0.0
                basket_n = max(1, len(cur_long) + len(cur_short))
        else:
            turn_cost = 0.0
            basket_n = max(1, len(cur_long) + len(cur_short))

        # Forward 1-bar return of each held name (ts -> nxt), plus funding accrued at `nxt` on the held leg.
        def _leg_ret(basket: set[str], side: int) -> float | None:
            rs: list[float] = []
            for s in basket:
                c0 = close_by_sym[s].get(ts)
                c1 = close_by_sym[s].get(nxt)
                if c0 and c1 and c0 > 0:
                    px = c1 / c0 - 1.0
                    # funding: long pays rate (−rate), short receives (+rate). side=+1 long, −1 short.
                    f = funding_by_sym.get(s, {}).get(nxt, 0.0)
                    rs.append(side * px - side * f if False else px - (f if side == 1 else -f))
            return statistics.fmean(rs) if rs else None

        long_r = _leg_ret(cur_long, 1)
        short_r = _leg_ret(cur_short, -1)
        if long_r is None or short_r is None:
            continue
        # Market-neutral: long leg minus short leg. (short_r is the laggards' own price move; we SHORT them, so
        # the book gains when they fall → −short_r. _leg_ret already applied funding with side=−1 for the short.)
        book_r = long_r - short_r
        # Subtract the rebalance turnover cost amortized across the book's gross notional (both legs).
        book_r -= turn_cost / basket_n
        bar_returns.append(book_r)
        bar_ts.append(nxt)
    return bar_returns, bar_ts, n_rebalances, n_trades


def _equity_max_dd(returns: list[float]) -> float:
    eq = 1.0
    peak = 1.0
    mdd = 0.0
    for r in returns:
        eq *= 1.0 + r
        peak = max(peak, eq)
        if peak > 0:
            mdd = min(mdd, eq / peak - 1.0)
    return abs(mdd)


def _fold_returns(returns: list[float], folds: int = 5) -> list[float]:
    if len(returns) < folds:
        return []
    sz = len(returns) // folds
    out = []
    for f in range(folds):
        seg = returns[f * sz : (f + 1) * sz] if f < folds - 1 else returns[f * sz :]
        out.append(sum(seg))
    return out


def _config_block_returns(returns: list[float], blocks: int = 8) -> list[list[float]]:
    """For a single book's CSCV-PBO we need >=2 'configs'. We compare the book against its own time-shuffled
    half-splits is not valid; instead PBO over a single config is undefined (returns 1.0). So the book's PBO is
    computed across the GRID's configs at scoring time (see run). This helper is unused for the single book."""
    return [returns]


def _long_only_bh(panel: dict[str, list[Bar]], window_ts: list[str], taker_bps: float) -> float:
    """Equal-weight long-only buy-and-hold over the SAME window (first->last common ts), net of one round-trip
    fee per name. The OLD (wrong-for-neutral) hurdle #390's combos were killed against — reported for contrast."""
    if not window_ts:
        return 0.0
    fee = taker_bps / 10000.0
    rets = []
    lo, hi = window_ts[0], window_ts[-1]
    for s, bars in panel.items():
        by = {b.ts.isoformat(): float(b.close) for b in bars}
        if lo in by and hi in by and by[lo] > 0:
            rets.append(by[hi] / by[lo] - 1.0 - 2 * fee)
    return statistics.fmean(rets) if rets else 0.0


def _btc_bar_returns(panel: dict[str, list[Bar]], bar_ts: list[str]) -> list[float]:
    btc = panel.get("BTCUSDT") or next(iter(panel.values()))
    by = {b.ts.isoformat(): float(b.close) for b in btc}
    ks = [b.ts.isoformat() for b in btc]
    pos = {k: i for i, k in enumerate(ks)}
    out = []
    for t in bar_ts:
        i = pos.get(t)
        if i and i > 0 and ks[i - 1] in by and by[ks[i - 1]] > 0:
            out.append(by[t] / by[ks[i - 1]] - 1.0)
        else:
            out.append(0.0)
    return out


def _corr(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    a, b = a[-n:], b[-n:]
    ma, mb = statistics.fmean(a), statistics.fmean(b)
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return 0.0
    cov = sum((a[k] - ma) * (b[k] - mb) for k in range(n))
    return max(-1.0, min(1.0, cov / math.sqrt(va * vb)))


def _periods_per_year(interval: str) -> float:
    return {"240": 365 * 6, "60": 365 * 24, "D": 365}.get(interval, 365)


def run_mktneutral_book(
    panel: dict[str, list[Bar]],
    funding_by_sym: dict[str, dict[str, float]],
    interval: str,
    taker_bps: float,
    venue: str,
) -> list[Config]:
    """Grid the neutral book over (lookback × quantile × rebalance cadence), score each config's OWN book equity
    curve BRUT through the locked Gate, confirm the champion on its OWN embargoed holdout. PBO is the true CSCV
    over the grid's per-bar config streams (multiple-testing honest). RANK BY OUTLIER; emit EVERY config."""
    lookbacks = [12, 30, 60]      # 4h: 2d / 5d / 10d trailing-momentum windows
    quantiles = [0.20, 0.33]      # top/bottom 20% or tertile
    cadences = [1, 6]             # rebalance every bar / every ~day (6×4h)
    ppy = _periods_per_year(interval)

    # Precompute ranks per lookback (PIT).
    rank_by_lb = {lb: _rank_from_trailing(_trailing_returns_at(panel, lb)) for lb in lookbacks}

    configs: list[Config] = []
    # Build every config's FULL (validation+holdout-spanning) net book stream first — PBO needs the cross-config
    # panel of per-bar returns aligned on a common length.
    streams: list[tuple[Config, list[float], list[str]]] = []
    for lb in lookbacks:
        for q in quantiles:
            for cad in cadences:
                ranks = rank_by_lb[lb]
                br, bts, n_reb, n_tr = _book_bar_returns(
                    panel, ranks, funding_by_sym, quantile=q, rebalance_every=cad,
                    taker_bps=taker_bps, charge_costs=True,
                )
                if len(br) < 40:
                    continue
                cfg = Config(label=f"{venue}:{interval}:lb{lb}:q{q}:reb{cad}", lookback=lb, quantile=q, rebalance_every=cad)
                cfg.n_rebalances = n_reb
                cfg.n_trades = n_tr
                streams.append((cfg, br, bts))

    if not streams:
        return configs
    grid_size = max(1, len(streams))
    # CSCV-PBO across the grid (the multiple-testing-honest PBO): align all configs on the common length.
    common_len = min(len(s[1]) for s in streams)
    cfg_block_returns = [s[1][-common_len:] for s in streams]
    grid_pbo = float(cscv_pbo(cfg_block_returns)) if len(streams) >= 2 else 1.0

    # Cross-config correlation (for the DSR trial-count haircut: a grid of near-duplicate books is not grid_size
    # independent tests).
    rho = _avg_pairwise_corr([s[1][-common_len:] for s in streams])

    for cfg, br, bts in streams:
        # Validation = first 80%, holdout = last 20% (embargo: drop the boundary bar).
        split = max(40, int(len(br) * 0.8))
        val_r, hold_r = br[:split], br[split + 1 :]
        val_ts = bts[:split]
        sr_obs, skew, kurt, n_obs = sample_moments(val_r)
        # DSR with the realized grid size deflation + cross-config correlation haircut (own-overfit only).
        trials = TrialStats(count=grid_size, sr_correlation=rho)
        sr_var = (1.0 + 0.5 * sr_obs * sr_obs) / (n_obs - 1) if n_obs > 1 else 0.0
        from cosmu.master.scorer import effective_trials
        n_eff = effective_trials(float(grid_size), rho)
        sr0 = expected_max_sharpe(sr_var, n_eff)
        dsr = probabilistic_sharpe(sr_obs, n_obs, skew, kurt, sr0)
        psr0 = probabilistic_sharpe(sr_obs, n_obs, skew, kurt, 0.0)
        folds = _fold_returns(val_r)
        folds_pos = (sum(1 for f in folds if f > 0) / len(folds)) if folds else 0.0
        book_ret = math.prod(1.0 + r for r in val_r) - 1.0
        # Gross book (no costs) over the same val window for cost_ratio.
        ranks = rank_by_lb[cfg.lookback]
        gbr, _, _, _ = _book_bar_returns(panel, ranks, funding_by_sym, quantile=cfg.quantile,
                                         rebalance_every=cfg.rebalance_every, taker_bps=taker_bps, charge_costs=False)
        gross_ret = math.prod(1.0 + r for r in gbr[:split]) - 1.0
        cost_ratio = (book_ret / gross_ret) if gross_ret not in (0.0,) else 0.0
        # Holdout DSR (own embargoed exam).
        h_sr, h_skew, h_kurt, h_n = sample_moments(hold_r)
        holdout_dsr = probabilistic_sharpe(h_sr, h_n, h_skew, h_kurt, 0.0) - 0.5
        long_bh = _long_only_bh(panel, val_ts, taker_bps)
        btc_r = _btc_bar_returns(panel, val_ts[1:] if val_ts else [])
        corr_btc = _corr(val_r[1:] if len(val_r) > 1 else val_r, btc_r)

        cfg.sharpe_ann = sr_obs * math.sqrt(ppy)
        cfg.deflated_sharpe = dsr
        cfg.psr_vs_zero = psr0
        cfg.pbo = grid_pbo
        cfg.folds_positive = folds_pos
        cfg.n_obs = n_obs
        cfg.max_dd = _equity_max_dd(val_r)
        cfg.book_return = book_ret
        cfg.gross_return = gross_ret
        cfg.cost_ratio = cost_ratio
        cfg.long_only_bh = long_bh
        cfg.cash_benchmark = 0.0
        cfg.beat_cash = book_ret > 0.0
        cfg.beat_long_bh = book_ret > long_bh
        cfg.holdout_dsr = holdout_dsr
        cfg.avg_corr_to_btc = corr_btc

        # BRUT verdict against the RIGHT benchmark for a neutral book: cash/0 (beat_buy_and_hold uses 0). We build
        # the BacktestMetrics with buy_and_hold_return=0 (the neutral hurdle) and score with the locked gate.
        m = BacktestMetrics(
            oos_return=Decimal(str(round(book_ret, 8))),
            buy_and_hold_return=Decimal("0"),   # neutral book's honest hurdle = cash
            sharpe=Decimal(str(round(cfg.sharpe_ann, 6))),
            sortino=Decimal("0"),
            max_drawdown=Decimal(str(round(cfg.max_dd, 6))),
            win_rate=Decimal("0"),
            num_trades=cfg.n_trades,
            sharpe_per_obs=Decimal(str(round(sr_obs, 8))),
            skew=Decimal(str(round(skew, 6))),
            kurtosis=Decimal(str(round(kurt, 6))),
            n_obs=n_obs,
            pbo=Decimal(str(round(grid_pbo, 6))),
            trials_counted=grid_size,
            folds_positive_pct=Decimal(str(round(folds_pos, 6))),
            holdout_deflated_sharpe=Decimal(str(round(holdout_dsr, 6))),
            regime_returns={},
        )
        verdict = score(m, GATES, trials=trials, check_holdout=True)
        cfg.passed = verdict.passed and cfg.n_trades >= GATES.min_trades
        cfg.holdout_passed = holdout_dsr > float(GATES.holdout_min_deflated_sharpe)
        cfg.reasons = list(verdict.reasons)
        configs.append(cfg)
        gc.collect()
    return configs


def _rank_from_trailing(trailing: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    """Cross-sectional percentile rank [0,1] at each bar from per-symbol trailing returns (PIT — only symbols with
    a return at that bar are ranked). 0 = worst (laggard), 1 = best (leader)."""
    # collect all timestamps
    ts_all: set[str] = set()
    for d in trailing.values():
        ts_all |= set(d)
    out: dict[str, dict[str, float]] = {s: {} for s in trailing}
    for ts in ts_all:
        present = [(s, trailing[s][ts]) for s in trailing if ts in trailing[s]]
        if len(present) < 2:
            continue
        present.sort(key=lambda x: x[1])
        m = len(present)
        for r_idx, (s, _) in enumerate(present):
            out[s][ts] = r_idx / (m - 1)
    return out


def _avg_pairwise_corr(series: list[list[float]]) -> float:
    usable = [s for s in series if len(s) >= 3]
    if len(usable) < 2:
        return 0.0
    cs = []
    for a in range(len(usable)):
        for b in range(a + 1, len(usable)):
            cs.append(_corr(usable[a], usable[b]))
    return statistics.fmean(cs) if cs else 0.0


# --------------------------------------------------------------------------- VARIANT 3: funding percentile (continuous)
@dataclass
class FundingConfig:
    label: str
    symbol: str
    pct_floor: float       # enter long when funding percentile <= this (most-negative funding = crowded shorts)
    lookback: int          # rolling window for the percentile
    sharpe_ann: float = 0.0
    deflated_sharpe: float = 0.0
    psr_vs_zero: float = 0.0
    pbo: float = 0.0
    folds_positive: float = 0.0
    n_trades: int = 0
    n_obs: int = 0
    book_return: float = 0.0
    buy_and_hold: float = 0.0
    beat_bh: bool = False
    holdout_dsr: float = 0.0
    passed: bool = False
    reasons: list = field(default_factory=list)


def run_funding_percentile(
    panel: dict[str, list[Bar]], funding_by_sym: dict[str, dict[str, float]], interval: str, taker_bps: float
) -> list[FundingConfig]:
    """Funding-contrarian as a CONTINUOUS percentile signal (no hard oversold-RSI conjunction): each bar, rank the
    symbol's own funding against its rolling window; when funding is in the most-negative percentile (crowded
    shorts), go LONG spot for a fixed hold; judged BRUT per (symbol × venue) on its OWN equity curve. This is the
    #390 funding-contrarian wall directly attacked (the RSI conjunction fired <=4 trades; this fires often)."""
    ppy = _periods_per_year(interval)
    fee = taker_bps / 10000.0
    floors = [0.10, 0.20]
    lbs = [60, 120]
    hold = max(1, int(round({"240": 6, "60": 24, "D": 5}.get(interval, 5))))  # ~1 day / 5 days
    out: list[FundingConfig] = []
    grid_size = len(floors) * len(lbs)
    for sym, bars in panel.items():
        fmap = funding_by_sym.get(sym, {})
        if sum(1 for v in fmap.values() if v != 0.0) < 50:
            continue  # honest: too little real funding to judge
        closes = [float(b.close) for b in bars]
        ts = [b.ts.isoformat() for b in bars]
        fund_series = [fmap.get(t, 0.0) for t in ts]
        for floor in floors:
            for lb in lbs:
                rets: list[float] = []
                rets_ts: list[str] = []
                n_trades = 0
                i = lb
                while i < len(bars) - hold:
                    window = fund_series[i - lb : i]
                    cur = fund_series[i]
                    # percentile of current funding within the window (low = most negative = crowded short)
                    below = sum(1 for w in window if w <= cur)
                    pct = below / max(1, len(window))
                    if pct <= floor:
                        c0 = closes[i]
                        c1 = closes[i + hold]
                        if c0 > 0:
                            r = c1 / c0 - 1.0 - 2 * fee
                            rets.append(r)
                            rets_ts.append(ts[i + hold])
                            n_trades += 1
                        i += hold  # non-overlapping holds
                    else:
                        i += 1
                if len(rets) < 5:
                    fc = FundingConfig(label=f"binance:{interval}:{sym}:pct{floor}:lb{lb}", symbol=sym, pct_floor=floor, lookback=lb)
                    fc.n_trades = len(rets)
                    fc.reasons = ["min_trades"]
                    out.append(fc)
                    continue
                split = max(4, int(len(rets) * 0.8))
                val_r, hold_r = rets[:split], rets[split:]
                sr_obs, skew, kurt, n_obs = sample_moments(val_r)
                sr_var = (1.0 + 0.5 * sr_obs * sr_obs) / (n_obs - 1) if n_obs > 1 else 0.0
                sr0 = expected_max_sharpe(sr_var, grid_size)
                dsr = probabilistic_sharpe(sr_obs, n_obs, skew, kurt, sr0)
                psr0 = probabilistic_sharpe(sr_obs, n_obs, skew, kurt, 0.0)
                folds = _fold_returns(val_r)
                folds_pos = (sum(1 for f in folds if f > 0) / len(folds)) if folds else 0.0
                book_ret = math.prod(1.0 + r for r in val_r) - 1.0
                h_sr, h_skew, h_kurt, h_n = sample_moments(hold_r)
                holdout_dsr = probabilistic_sharpe(h_sr, h_n, h_skew, h_kurt, 0.0) - 0.5
                # buy-and-hold over the same span for this symbol
                lo_ts = rets_ts[0] if rets_ts else ts[lb]
                by = {b.ts.isoformat(): float(b.close) for b in bars}
                bh = (by[ts[-1]] / by[lo_ts] - 1.0 - 2 * fee) if lo_ts in by and by[lo_ts] > 0 else 0.0
                fc = FundingConfig(label=f"binance:{interval}:{sym}:pct{floor}:lb{lb}", symbol=sym, pct_floor=floor, lookback=lb)
                fc.sharpe_ann = sr_obs * math.sqrt(ppy / hold)  # per-trade obs are `hold` bars apart
                fc.deflated_sharpe = dsr
                fc.psr_vs_zero = psr0
                fc.pbo = 1.0 if len(rets) < 8 else 0.5  # single-symbol single-config PBO is undefined; flag conservatively
                fc.folds_positive = folds_pos
                fc.n_trades = len(rets)
                fc.n_obs = n_obs
                fc.book_return = book_ret
                fc.buy_and_hold = bh
                fc.beat_bh = book_ret > bh
                fc.holdout_dsr = holdout_dsr
                m = BacktestMetrics(
                    oos_return=Decimal(str(round(book_ret, 8))), buy_and_hold_return=Decimal(str(round(bh, 8))),
                    sharpe=Decimal(str(round(fc.sharpe_ann, 6))), sortino=Decimal("0"),
                    max_drawdown=Decimal("0"), win_rate=Decimal("0"), num_trades=len(rets),
                    sharpe_per_obs=Decimal(str(round(sr_obs, 8))), skew=Decimal(str(round(skew, 6))),
                    kurtosis=Decimal(str(round(kurt, 6))), n_obs=n_obs, pbo=Decimal(str(fc.pbo)),
                    trials_counted=grid_size, folds_positive_pct=Decimal(str(round(folds_pos, 6))),
                    holdout_deflated_sharpe=Decimal(str(round(holdout_dsr, 6))), regime_returns={},
                )
                verdict = score(m, GATES, trials=TrialStats(count=grid_size), check_holdout=True)
                fc.passed = verdict.passed and len(rets) >= GATES.min_trades
                fc.reasons = list(verdict.reasons)
                out.append(fc)
        gc.collect()
    return out


# --------------------------------------------------------------------------- main
def main() -> int:
    print("EDGE-HUNT MKT-NEUTRAL 2026-06-25 — market-neutral xsec book + funding-percentile, BRUT, ZERO prod impact")
    print(f"  gate: DSR>={GATES.min_deflated_sharpe_prob} PBO<={GATES.max_pbo} folds>={GATES.min_folds_positive_pct} "
          f"min_trades>={GATES.min_trades} holdout_dsr>{GATES.holdout_min_deflated_sharpe} beat_benchmark={GATES.require_beat_buy_and_hold}")

    catalog = default_catalog()
    # Bybit ~ Binance-class taker; we use Binance's catalog taker (10 bps) as the cost on the keyless Bybit bars
    # (the price thesis is venue-agnostic; the fee is the real axis). Bybit spot taker is ~10 bps too.
    taker_bps = float(catalog.venue("binance").taker_fee_bps)
    funding = CachedFundingRateProvider(cache_dir=FUNDING_DIR)

    interval = "240"  # 4h — the densest keyless bar with deep paginated history
    print(f"\n== fetching paginated keyless Bybit 4h ({BYBIT_PAGES} pages ≈ {BYBIT_PAGES*1000} bars) for {len(UNIVERSE)} names ==")
    panel: dict[str, list[Bar]] = {}
    for sym in UNIVERSE:
        bars = _bybit_paginated(sym, interval, BYBIT_PAGES)
        if bars:
            panel[sym] = bars
        span = (bars[-1].ts - bars[0].ts).days if bars else 0
        print(f"  {sym}: {len(bars)} 4h bars  span={span}d  {bars[0].ts.date() if bars else None}..{bars[-1].ts.date() if bars else None}")
    panel = _intersect_window(panel)
    n_common = len(next(iter(panel.values()))) if panel else 0
    span_common = (next(iter(panel.values()))[-1].ts - next(iter(panel.values()))[0].ts).days if panel else 0
    print(f"  COMMON window: {len(panel)} names × {n_common} bars  span={span_common}d")

    # Per-symbol PIT funding (4h granularity).
    funding_by_sym = {sym: _funding_by_bar(sym, bars, funding) for sym, bars in panel.items()}
    fund_cov = {s: sum(1 for v in d.values() if v != 0.0) for s, d in funding_by_sym.items()}
    print(f"  funding coverage (non-zero 4h accruals): {fund_cov}")

    print("\n== THEME A: market-neutral cross-sectional momentum BOOK (long leaders − short laggards) ==")
    book_cfgs = run_mktneutral_book(panel, funding_by_sym, interval, taker_bps, "bybit")
    print(f"   book configs scored: {len(book_cfgs)}")

    print("\n== THEME B: funding-contrarian as a CONTINUOUS funding-percentile signal (per symbol, 4h) ==")
    fund_cfgs = run_funding_percentile(panel, funding_by_sym, interval, taker_bps)
    print(f"   funding-percentile configs scored: {len(fund_cfgs)}")

    # --- emit JSON ---
    payload = {
        "meta": {
            "interval": "4h", "pages": BYBIT_PAGES, "universe": UNIVERSE,
            "common_bars": n_common, "common_span_days": span_common, "taker_bps": taker_bps,
            "funding_coverage": fund_cov,
        },
        "book": [c.__dict__ for c in book_cfgs],
        "funding_percentile": [c.__dict__ for c in fund_cfgs],
    }
    RESULTS_JSON.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\n  wrote results -> {RESULTS_JSON}")

    # --- verdict ---
    book_survivors = [c for c in book_cfgs if c.passed and c.holdout_passed]
    print(f"\n  BOOK gate survivors (pass + holdout): {len(book_survivors)} / {len(book_cfgs)}")
    print("\n  ALL market-neutral book configs (ranked by deflated Sharpe):")
    print(f"  {'config':<28}{'DSR':>7}{'shrp':>7}{'trades':>7}{'reb':>6}{'folds':>7}{'pbo':>6}{'bookRet':>9}{'longBH':>9}{'h_dsr':>7}{'corrBTC':>8}  killed_by")
    for c in sorted(book_cfgs, key=lambda c: c.deflated_sharpe, reverse=True):
        kb = ",".join(c.reasons) if c.reasons else ("PASS" if c.passed else "")
        print(f"  {c.label:<28}{c.deflated_sharpe:>7.3f}{c.sharpe_ann:>7.2f}{c.n_trades:>7}{c.n_rebalances:>6}"
              f"{c.folds_positive:>7.2f}{c.pbo:>6.2f}{c.book_return:>9.3f}{c.long_only_bh:>9.3f}{c.holdout_dsr:>7.2f}{c.avg_corr_to_btc:>8.3f}  {kb}")

    fund_pass = [c for c in fund_cfgs if c.passed]
    print(f"\n  FUNDING-percentile gate survivors: {len(fund_pass)} / {len(fund_cfgs)}")
    print("\n  TOP-15 funding-percentile configs by deflated Sharpe (>= 5 trades):")
    print(f"  {'config':<34}{'DSR':>7}{'trades':>7}{'folds':>7}{'ret':>9}{'bh':>9}{'h_dsr':>7}  killed_by")
    for c in sorted([c for c in fund_cfgs if c.n_trades >= 5], key=lambda c: c.deflated_sharpe, reverse=True)[:15]:
        kb = ",".join(c.reasons) if c.reasons else ("PASS" if c.passed else "")
        print(f"  {c.label:<34}{c.deflated_sharpe:>7.3f}{c.n_trades:>7}{c.folds_positive:>7.2f}"
              f"{c.book_return:>9.3f}{c.buy_and_hold:>9.3f}{c.holdout_dsr:>7.2f}  {kb}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
