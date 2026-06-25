#!/usr/bin/env python3
"""EXPERIMENT ONLY — slate #6, H5: BASIS-MOMENTUM CARRY, tested BRUT with a DECISIVE beta-orthogonality gate.

ZERO production impact: reads the LOCKED Gate + canonical scorer primitives, writes NOTHING to any store, never
touches a Gate constant, changes no behavior. Output = a per-config stat block (printed + JSON for the report/HTML).

THESIS (docs/reports/edge-hypothesis-slate-2026-06-25.md §H5):
  Ride an ACCELERATING perp-spot basis. Leverage build-up TRENDS for days, so the tradeable signal is the
  TIME-DERIVATIVE  d(basis)/dt  — NOT the level (level-fade was already tested elsewhere). This is a different
  signal FAMILY from price-momentum, so it is NOT mechanically blocked by the just-confirmed "crypto xsec
  price-momentum is uneconomic at our cost tier" result (#390/#396). The honest open question: is basis-momentum
  a REAL carry/positioning edge, or is it just disguised price-momentum / bull-beta wearing a basis mask?

THE BASIS (faithful to the registered tier0 PIT feature `perp_spot_basis`):
  The production provider (cosmu/data/providers/onchain.BinanceBasisProvider) computes basis = (mark − index)/index
  from Binance USDⓈ-M premiumIndex, with available_at == observation time (NO look-ahead lag). That provider only
  fetches the CURRENT snapshot — there is no historical basis series in any store. To get ~3.65yr of REAL history
  offline we reconstruct it the honest way: paginated keyless Bybit v5 klines for BOTH the `spot` and `linear`
  (perpetual) leg of each name, intersect on the common bar timestamps, and compute
        basis_t = (perp_close_t − spot_close_t) / spot_close_t
  i.e. the perp close is the mark proxy and the spot close is the index proxy — the SAME (mark−index)/index shape
  the registered feature uses, evaluated strictly at bar close (PIT: a bar's basis is only knowable once that bar
  has closed; the signal at bar i trades the i→i+1 forward return, never the same bar).

THE SIGNAL (pre-registered — NO sweep on the headline):
  basis_momentum_t = basis_t − basis_{t-LB}   (the discrete d(basis)/dt over LB bars), then CROSS-SECTIONALLY
  z-scored across the universe at each bar (PIT — only names present at that bar). Long the names whose basis is
  accelerating MOST positively (top of the xsec z), short the names accelerating most negatively (bottom). The
  book's per-bar return is mean(long fwd) − mean(short fwd), beta nets out by construction, charged fee +
  liquidity-tiered slippage on BOTH legs' turnover and funding accrued on BOTH legs.

  PRE-REGISTERED HEADLINE CONFIG (chosen before seeing results, ONE point — no cherry-pick):
      LB = 6 bars (= 24h of basis change), QUANTILE = 0.33 (tertile legs), REBALANCE every 6 bars (~daily).
  A small DIAGNOSTIC grid around it is ALSO run, but ONLY to give the Gate's own-overfit deflation (DSR/PBO) an
  honest trial count — the GO/KILL verdict is read off the pre-registered config, never the grid's best cell.

THE DECISIVE DISCONFIRMER — β-ORTHOGONALITY (this is what makes H5 different from #390 honest, not hopeful):
  Regress the book's per-bar net returns on BTC buy-and-hold per-bar returns:  r_book = α + β·r_btc + ε.
  REQUIRE the residual intercept α, ANNUALIZED and already NET of fees, to be > 0. If α ≤ 0 (the book's positive
  return, if any, is just loaded beta) → it is the same bull-beta trap that killed price xsec-momentum → KILL,
  stated plainly. We report α (annualized), β, the t-stat of α, and corr-to-BTC. A market-neutral book SHOULD have
  β ≈ 0 and corr ≈ 0; if it does and α is still ≤ 0, the signal simply has no carry edge net of cost.

PRIOR (stated honestly up front): carry / funding / basis signals across crypto were repeatedly flagged in this
repo's research as "largely arbitraged toward ~0 by 2026" (the funding-dispersion and orthogonal-data rounds). So
a CLEAN NEGATIVE — gross spread small and/or eaten by two-leg turnover cost, and α ≤ 0 — is the LIKELY and honest
outcome. We do not strain to manufacture an edge; if it KILLs, we say so and show every number.
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
    effective_trials,
    expected_max_sharpe,
    probabilistic_sharpe,
    sample_moments,
    score,
)
from cosmu.spine.venue import default_catalog  # noqa: E402

# ------- config -------------------------------------------------------------------------------------------
# Same 12-name liquid perp universe as the mkt-neutral edge-hunt (so the result is directly comparable).
UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT",
    "ADAUSDT", "DOTUSDT", "LTCUSDT", "XRPUSDT", "BCHUSDT", "ATOMUSDT",
]
GATES = GateSettings()  # the LOCKED gate
FUNDING_DIR = "/Users/device/cosmu/apps/engine/.cosmu/market_data/binance_funding"
RESULTS_JSON = _ENGINE / "scripts" / "research" / "h5_basis_momentum_results_2026_06_25.json"
BYBIT_PAGES = 8  # ~8000 4h bars ≈ 3.65yr per leg (the keyless ceiling we measured)
INTERVAL = "240"  # 4h — densest keyless bar with deep paginated history

# PRE-REGISTERED headline config (fixed BEFORE any result was seen).
PRE_LB = 6          # basis change over 6×4h = 24h (d(basis)/dt window)
PRE_QUANTILE = 0.33  # tertile legs
PRE_REBALANCE = 6   # rebalance ~daily


# --------------------------------------------------------------------------- data (paginated keyless Bybit)
def _bybit_paginated(symbol: str, category: str, interval: str, pages: int) -> list[Bar]:
    """Walk Bybit v5 kline backwards via `end=` to defeat the single-page 1000-bar cap. `category` is 'spot' or
    'linear' (the perpetual). Returns ascending CLOSED bars (in-progress last bar dropped) — real, PIT, keyless."""
    ctx = _ssl_context()
    rows: dict[int, list] = {}
    end = int(datetime.now(UTC).timestamp() * 1000)
    for _ in range(pages):
        q = urllib.parse.urlencode(
            {"category": category, "symbol": symbol, "interval": interval, "limit": 1000, "end": end}
        )
        url = f"https://api.bybit.com/v5/market/kline?{q}"
        req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=25, context=ctx) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"  ! bybit page fetch failed for {symbol} {category} {interval}: {e}", file=sys.stderr)
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
    now = datetime.now(UTC)
    secs = {"240": 4 * 3600, "60": 3600, "D": 86400}.get(interval, 86400)
    if bars and (now - bars[-1].ts).total_seconds() < secs:
        bars = bars[:-1]
    return bars


def _basis_panel(spot: dict[str, list[Bar]], perp: dict[str, list[Bar]]) -> dict[str, dict[str, float]]:
    """Per-symbol historical basis series keyed by bar.ts.isoformat() over the timestamps the spot AND perp leg
    BOTH closed:  basis = (perp_close − spot_close) / spot_close  (the registered (mark−index)/index shape, PIT)."""
    out: dict[str, dict[str, float]] = {}
    for sym in spot:
        if sym not in perp:
            continue
        s_by = {b.ts.isoformat(): float(b.close) for b in spot[sym]}
        p_by = {b.ts.isoformat(): float(b.close) for b in perp[sym]}
        d: dict[str, float] = {}
        for ts, sc in s_by.items():
            pc = p_by.get(ts)
            if pc is not None and sc > 0:
                d[ts] = (pc - sc) / sc
        if d:
            out[sym] = d
    return out


def _intersect_spot_panel(spot: dict[str, list[Bar]], basis: dict[str, dict[str, float]]) -> dict[str, list[Bar]]:
    """Restrict every name's SPOT bars to the COMMON timestamp window shared by every name's basis series, so the
    cross-sectional rank is on an apples-to-apples panel (a late-listing name never silently shrinks the universe
    mid-history). The book trades SPOT price moves (we hold spot legs); the perp leg only defines the signal+funding."""
    names = [s for s in spot if s in basis]
    if not names:
        return {}
    common: set[str] | None = None
    for s in names:
        ks = set(basis[s])
        common = ks if common is None else (common & ks)
    common = common or set()
    return {s: [b for b in spot[s] if b.ts.isoformat() in common] for s in names}


# --------------------------------------------------------------------------- basis-momentum xsec rank (PIT)
def _basis_momentum(basis: dict[str, dict[str, float]], panel: dict[str, list[Bar]], lb: int) -> dict[str, dict[str, float]]:
    """Per-symbol basis-MOMENTUM = basis_t − basis_{t-lb} (discrete d(basis)/dt over lb bars), keyed by ts.isoformat().
    Computed on each name's own ascending common-window bar sequence (PIT — only uses basis at/<= t)."""
    out: dict[str, dict[str, float]] = {}
    for sym, bars in panel.items():
        bser = basis.get(sym, {})
        ts = [b.ts.isoformat() for b in bars]
        d: dict[str, float] = {}
        for i in range(lb, len(ts)):
            b_now = bser.get(ts[i])
            b_prev = bser.get(ts[i - lb])
            if b_now is not None and b_prev is not None:
                d[ts[i]] = b_now - b_prev
        out[sym] = d
    return out


def _xsec_z(signal: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    """Cross-sectional z-score of a per-symbol signal at each bar (PIT — only names present at that bar are
    standardized). Returns {symbol: {ts: z}}. Names with <2 present at a bar are skipped at that bar."""
    ts_all: set[str] = set()
    for d in signal.values():
        ts_all |= set(d)
    out: dict[str, dict[str, float]] = {s: {} for s in signal}
    for ts in ts_all:
        present = [(s, signal[s][ts]) for s in signal if ts in signal[s]]
        if len(present) < 2:
            continue
        vals = [v for _, v in present]
        mu = statistics.fmean(vals)
        sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        if sd <= 0:
            continue
        for s, v in present:
            out[s][ts] = (v - mu) / sd
    return out


# --------------------------------------------------------------------------- funding (PIT, per bar)
def _funding_by_bar(symbol: str, bars: list[Bar], funding: CachedFundingRateProvider) -> dict[str, float]:
    """Per-bar SUMMED funding accrued over each bar interval, keyed by bar.ts.isoformat() (PIT — only settlements
    at/<= bar close). Empty when the cache has no funding for the symbol (honest 'no carry data' → 0 accrual)."""
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


# --------------------------------------------------------------------------- the market-neutral basis-momentum book
@dataclass
class Config:
    label: str
    lookback: int
    quantile: float
    rebalance_every: int
    pre_registered: bool = False
    sharpe_ann: float = 0.0
    deflated_sharpe: float = 0.0
    psr_vs_zero: float = 0.0
    pbo: float = 0.0
    folds_positive: float = 0.0
    n_rebalances: int = 0
    n_trades: int = 0
    n_obs: int = 0
    max_dd: float = 0.0
    book_return: float = 0.0
    gross_return: float = 0.0
    cost_ratio: float = 0.0
    long_only_bh: float = 0.0
    cash_benchmark: float = 0.0
    beat_cash: bool = False
    beat_long_bh: bool = False
    holdout_dsr: float = 0.0
    avg_corr_to_btc: float = 0.0
    # --- the decisive disconfirmer ---
    alpha_ann: float = 0.0      # annualized residual intercept (NET of fees) from r_book = a + b*r_btc
    beta_btc: float = 0.0
    alpha_t: float = 0.0        # t-stat of the intercept
    alpha_positive: bool = False
    passed: bool = False
    holdout_passed: bool = False
    reasons: list = field(default_factory=list)


def _slip_for(sym: str, ts: str, vol_by_sym, taker_bps, charge_costs) -> float:
    if not charge_costs:
        return 0.0
    adv = vol_by_sym[sym].get(ts, 0.0)
    floor = max(5.0, _liquidity_floor_bps(adv))  # 5bps deep-book floor or liquidity-tiered
    return floor / 10000.0


def _book_bar_returns(
    panel: dict[str, list[Bar]],
    zsig: dict[str, dict[str, float]],
    funding_by_sym: dict[str, dict[str, float]],
    *,
    quantile: float,
    rebalance_every: int,
    taker_bps: float,
    charge_costs: bool,
) -> tuple[list[float], list[str], int, int]:
    """Market-neutral basis-momentum book over a common-timestamp SPOT panel. At each rebalance bar, sort names by
    their xsec basis-momentum z; LONG the top `quantile` (accelerating-positive basis), SHORT the bottom `quantile`
    (accelerating-negative). Per-bar return = mean(long fwd) − mean(short fwd) + funding on each held leg, MINUS
    round-trip turnover cost (fee + liquidity slippage) on names entering/leaving either basket. Returns
    (bar_returns, bar_ts, n_rebalances, n_trades)."""
    any_sym = next(iter(panel))
    ts_seq = [b.ts.isoformat() for b in panel[any_sym]]
    close_by_sym = {s: {b.ts.isoformat(): float(b.close) for b in bars} for s, bars in panel.items()}
    vol_by_sym = {s: {b.ts.isoformat(): float(b.close) * float(b.volume) for b in bars} for s, bars in panel.items()}
    fee = taker_bps / 10000.0

    bar_returns: list[float] = []
    bar_ts: list[str] = []
    cur_long: set[str] = set()
    cur_short: set[str] = set()
    n_rebalances = 0
    n_trades = 0

    for i in range(len(ts_seq) - 1):
        ts = ts_seq[i]
        nxt = ts_seq[i + 1]
        if i % rebalance_every == 0:
            ranked = sorted((s for s in panel if ts in zsig.get(s, {})), key=lambda s: zsig[s][ts])
            m = len(ranked)
            if m >= 4:
                k = max(1, int(round(m * quantile)))
                new_short = set(ranked[:k])    # lowest z = most accelerating-negative basis = SHORT
                new_long = set(ranked[-k:])    # highest z = most accelerating-positive basis = LONG
                changed = (new_long ^ cur_long) | (new_short ^ cur_short)
                turn_cost = 0.0
                for s in changed:
                    if s in close_by_sym and ts in close_by_sym[s]:
                        turn_cost += fee + _slip_for(s, ts, vol_by_sym, taker_bps, charge_costs)
                        n_trades += 1
                basket_n = max(1, len(new_long) + len(new_short))
                cur_long, cur_short = new_long, new_short
                n_rebalances += 1
            else:
                turn_cost = 0.0
                basket_n = max(1, len(cur_long) + len(cur_short))
        else:
            turn_cost = 0.0
            basket_n = max(1, len(cur_long) + len(cur_short))

        def _leg_ret(basket: set[str], side: int) -> float | None:
            rs: list[float] = []
            for s in basket:
                c0 = close_by_sym[s].get(ts)
                c1 = close_by_sym[s].get(nxt)
                if c0 and c1 and c0 > 0:
                    px = c1 / c0 - 1.0
                    f = funding_by_sym.get(s, {}).get(nxt, 0.0)
                    # long pays funding (−f), short receives (+f).
                    rs.append(px - (f if side == 1 else -f))
            return statistics.fmean(rs) if rs else None

        long_r = _leg_ret(cur_long, 1)
        short_r = _leg_ret(cur_short, -1)
        if long_r is None or short_r is None:
            continue
        book_r = long_r - short_r
        book_r -= turn_cost / basket_n
        bar_returns.append(book_r)
        bar_ts.append(nxt)
    return bar_returns, bar_ts, n_rebalances, n_trades


def _equity_max_dd(returns: list[float]) -> float:
    eq = peak = 1.0
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
    return [
        sum(returns[f * sz : (f + 1) * sz] if f < folds - 1 else returns[f * sz :])
        for f in range(folds)
    ]


def _long_only_bh(panel: dict[str, list[Bar]], window_ts: list[str], taker_bps: float) -> float:
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


def _ols_alpha_beta(y: list[float], x: list[float], ppy: float) -> tuple[float, float, float]:
    """OLS  y = a + b*x + e.  Returns (alpha_annualized, beta, t_stat_of_alpha). y, x are per-bar returns aligned
    on the same length. alpha is the per-bar intercept compounded to a year (the residual return net of BTC beta);
    t-stat uses the classical OLS standard error of the intercept. This is the decisive β-orthogonality test:
    a market-neutral carry edge must show a POSITIVE residual alpha that does NOT collapse into loaded beta."""
    n = min(len(y), len(x))
    if n < 10:
        return 0.0, 0.0, 0.0
    y, x = y[-n:], x[-n:]
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sxx = sum((xi - mx) ** 2 for xi in x)
    if sxx <= 0:
        # No BTC variance to regress on; alpha = mean(y) (degenerate, treat beta=0).
        a_bar = my
        beta = 0.0
        resid = [yi - a_bar for yi in y]
    else:
        sxy = sum((x[i] - mx) * (y[i] - my) for i in range(n))
        beta = sxy / sxx
        a_bar = my - beta * mx
        resid = [y[i] - (a_bar + beta * x[i]) for i in range(n)]
    # classical OLS SE of the intercept
    dof = max(1, n - 2)
    s2 = sum(r * r for r in resid) / dof
    se_a = math.sqrt(s2 * (1.0 / n + (mx * mx) / sxx)) if sxx > 0 else math.sqrt(s2 / n)
    t_a = a_bar / se_a if se_a > 0 else 0.0
    # annualize the per-bar intercept by compounding (a_bar is a per-bar arithmetic mean residual return)
    alpha_ann = (1.0 + a_bar) ** ppy - 1.0
    return alpha_ann, beta, t_a


def _periods_per_year(interval: str) -> float:
    return {"240": 365 * 6, "60": 365 * 24, "D": 365}.get(interval, 365)


def run_basis_momentum_book(
    panel: dict[str, list[Bar]],
    basis: dict[str, dict[str, float]],
    funding_by_sym: dict[str, dict[str, float]],
    interval: str,
    taker_bps: float,
    venue: str,
) -> list[Config]:
    """Build the pre-registered basis-momentum book PLUS a small diagnostic grid; score each config's OWN equity
    curve BRUT through the locked Gate; run the decisive β-regression on each; confirm the champion on its embargoed
    holdout. PBO is the true CSCV across the grid. RANK BY OUTLIER; emit EVERY config; verdict read off pre-reg."""
    lookbacks = [3, 6, 12]    # 4h: 12h / 24h / 48h basis-change windows (6 = pre-registered)
    quantiles = [0.20, 0.33]  # 0.33 = pre-registered tertile
    cadences = [6, 12]        # rebalance ~daily / ~2-daily (6 = pre-registered)
    ppy = _periods_per_year(interval)

    z_by_lb = {lb: _xsec_z(_basis_momentum(basis, panel, lb)) for lb in lookbacks}

    streams: list[tuple[Config, list[float], list[str]]] = []
    for lb in lookbacks:
        for q in quantiles:
            for cad in cadences:
                br, bts, n_reb, n_tr = _book_bar_returns(
                    panel, z_by_lb[lb], funding_by_sym, quantile=q, rebalance_every=cad,
                    taker_bps=taker_bps, charge_costs=True,
                )
                if len(br) < 40:
                    continue
                is_pre = (lb == PRE_LB and abs(q - PRE_QUANTILE) < 1e-9 and cad == PRE_REBALANCE)
                cfg = Config(
                    label=f"{venue}:{interval}:lb{lb}:q{q}:reb{cad}" + (" *PRE-REG" if is_pre else ""),
                    lookback=lb, quantile=q, rebalance_every=cad, pre_registered=is_pre,
                )
                cfg.n_rebalances = n_reb
                cfg.n_trades = n_tr
                streams.append((cfg, br, bts))

    configs: list[Config] = []
    if not streams:
        return configs
    grid_size = max(1, len(streams))
    common_len = min(len(s[1]) for s in streams)
    cfg_block_returns = [s[1][-common_len:] for s in streams]
    grid_pbo = float(cscv_pbo(cfg_block_returns)) if len(streams) >= 2 else 1.0
    rho = _avg_pairwise_corr([s[1][-common_len:] for s in streams])

    for cfg, br, bts in streams:
        split = max(40, int(len(br) * 0.8))
        val_r, hold_r = br[:split], br[split + 1 :]
        val_ts = bts[:split]
        sr_obs, skew, kurt, n_obs = sample_moments(val_r)
        trials = TrialStats(count=grid_size, sr_correlation=rho)
        sr_var = (1.0 + 0.5 * sr_obs * sr_obs) / (n_obs - 1) if n_obs > 1 else 0.0
        n_eff = effective_trials(float(grid_size), rho)
        sr0 = expected_max_sharpe(sr_var, n_eff)
        dsr = probabilistic_sharpe(sr_obs, n_obs, skew, kurt, sr0)
        psr0 = probabilistic_sharpe(sr_obs, n_obs, skew, kurt, 0.0)
        folds = _fold_returns(val_r)
        folds_pos = (sum(1 for f in folds if f > 0) / len(folds)) if folds else 0.0
        book_ret = math.prod(1.0 + r for r in val_r) - 1.0
        gbr, _, _, _ = _book_bar_returns(panel, z_by_lb[cfg.lookback], funding_by_sym, quantile=cfg.quantile,
                                         rebalance_every=cfg.rebalance_every, taker_bps=taker_bps, charge_costs=False)
        gross_ret = math.prod(1.0 + r for r in gbr[:split]) - 1.0
        cost_ratio = (book_ret / gross_ret) if gross_ret not in (0.0,) else 0.0
        h_sr, h_skew, h_kurt, h_n = sample_moments(hold_r)
        holdout_dsr = probabilistic_sharpe(h_sr, h_n, h_skew, h_kurt, 0.0) - 0.5
        long_bh = _long_only_bh(panel, val_ts, taker_bps)
        btc_r = _btc_bar_returns(panel, val_ts[1:] if val_ts else [])
        val_r_aligned = val_r[1:] if len(val_r) > 1 else val_r
        corr_btc = _corr(val_r_aligned, btc_r)
        # --- decisive β-orthogonality disconfirmer ---
        alpha_ann, beta_btc, alpha_t = _ols_alpha_beta(val_r_aligned, btc_r, ppy)

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
        cfg.alpha_ann = alpha_ann
        cfg.beta_btc = beta_btc
        cfg.alpha_t = alpha_t
        cfg.alpha_positive = alpha_ann > 0.0

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
        # H5 GO requires the Gate AND the decisive β-orthogonality test (residual alpha > 0).
        cfg.passed = verdict.passed and cfg.n_trades >= GATES.min_trades and cfg.alpha_positive
        cfg.holdout_passed = holdout_dsr > float(GATES.holdout_min_deflated_sharpe)
        cfg.reasons = list(verdict.reasons)
        if not cfg.alpha_positive and "alpha_collapsed_to_beta" not in cfg.reasons:
            cfg.reasons.append("alpha<=beta")
        configs.append(cfg)
        gc.collect()
    return configs


def _avg_pairwise_corr(series: list[list[float]]) -> float:
    usable = [s for s in series if len(s) >= 3]
    if len(usable) < 2:
        return 0.0
    cs = []
    for a in range(len(usable)):
        for b in range(a + 1, len(usable)):
            cs.append(_corr(usable[a], usable[b]))
    return statistics.fmean(cs) if cs else 0.0


# --------------------------------------------------------------------------- main
def main() -> int:
    print("H5 BASIS-MOMENTUM CARRY 2026-06-25 — d(basis)/dt xsec book, BRUT + decisive β-orthogonality, ZERO prod impact")
    print(f"  gate: DSR>={GATES.min_deflated_sharpe_prob} PBO<={GATES.max_pbo} folds>={GATES.min_folds_positive_pct} "
          f"min_trades>={GATES.min_trades} holdout_dsr>{GATES.holdout_min_deflated_sharpe} +residual-alpha>0")
    print(f"  PRE-REGISTERED: lb={PRE_LB} (24h) quantile={PRE_QUANTILE} rebalance={PRE_REBALANCE} (~daily)")

    catalog = default_catalog()
    taker_bps = float(catalog.venue("binance").taker_fee_bps)
    funding = CachedFundingRateProvider(cache_dir=FUNDING_DIR)

    print(f"\n== fetching paginated keyless Bybit 4h SPOT+PERP ({BYBIT_PAGES} pages ≈ {BYBIT_PAGES*1000} bars/leg) for {len(UNIVERSE)} names ==")
    spot: dict[str, list[Bar]] = {}
    perp: dict[str, list[Bar]] = {}
    for sym in UNIVERSE:
        sb = _bybit_paginated(sym, "spot", INTERVAL, BYBIT_PAGES)
        pb = _bybit_paginated(sym, "linear", INTERVAL, BYBIT_PAGES)
        if sb:
            spot[sym] = sb
        if pb:
            perp[sym] = pb
        sspan = (sb[-1].ts - sb[0].ts).days if sb else 0
        pspan = (pb[-1].ts - pb[0].ts).days if pb else 0
        print(f"  {sym}: spot {len(sb)} bars ({sspan}d) · perp {len(pb)} bars ({pspan}d)")

    basis = _basis_panel(spot, perp)
    panel = _intersect_spot_panel(spot, basis)
    n_common = len(next(iter(panel.values()))) if panel else 0
    span_common = (next(iter(panel.values()))[-1].ts - next(iter(panel.values()))[0].ts).days if panel else 0
    print(f"  COMMON window: {len(panel)} names × {n_common} bars  span={span_common}d ≈ {span_common/365:.2f}yr")
    # basis sanity (mean abs basis per name — should be small, a few bps to tens of bps)
    basis_mean_abs = {s: round(statistics.fmean(abs(v) for v in basis[s].values()) * 1e4, 2) for s in panel if basis.get(s)}
    print(f"  mean |basis| (bps): {basis_mean_abs}")

    funding_by_sym = {sym: _funding_by_bar(sym, bars, funding) for sym, bars in panel.items()}
    fund_cov = {s: sum(1 for v in d.values() if v != 0.0) for s, d in funding_by_sym.items()}
    print(f"  funding coverage (non-zero 4h accruals): {fund_cov}")

    print("\n== BASIS-MOMENTUM market-neutral book (long accelerating-positive basis − short accelerating-negative) ==")
    book_cfgs = run_basis_momentum_book(panel, basis, funding_by_sym, INTERVAL, taker_bps, "bybit")
    print(f"   book configs scored: {len(book_cfgs)}")

    payload = {
        "meta": {
            "interval": "4h", "pages": BYBIT_PAGES, "universe": UNIVERSE,
            "common_bars": n_common, "common_span_days": span_common, "taker_bps": taker_bps,
            "funding_coverage": fund_cov, "basis_mean_abs_bps": basis_mean_abs,
            "pre_registered": {"lookback": PRE_LB, "quantile": PRE_QUANTILE, "rebalance": PRE_REBALANCE},
        },
        "book": [c.__dict__ for c in book_cfgs],
    }
    RESULTS_JSON.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\n  wrote results -> {RESULTS_JSON}")

    pre = next((c for c in book_cfgs if c.pre_registered), None)
    survivors = [c for c in book_cfgs if c.passed and c.holdout_passed]
    print(f"\n  GATE survivors (pass + holdout + alpha>0): {len(survivors)} / {len(book_cfgs)}")
    print("\n  ALL basis-momentum book configs (ranked by deflated Sharpe):")
    hdr = (f"  {'config':<30}{'DSR':>7}{'shrp':>7}{'trades':>7}{'reb':>6}{'folds':>7}{'pbo':>6}"
           f"{'netRet':>9}{'grossRet':>10}{'aAnn':>9}{'beta':>7}{'a_t':>7}{'corrBTC':>8}  killed_by")
    print(hdr)
    for c in sorted(book_cfgs, key=lambda c: c.deflated_sharpe, reverse=True):
        kb = ",".join(c.reasons) if c.reasons else ("PASS" if c.passed else "")
        print(f"  {c.label:<30}{c.deflated_sharpe:>7.3f}{c.sharpe_ann:>7.2f}{c.n_trades:>7}{c.n_rebalances:>6}"
              f"{c.folds_positive:>7.2f}{c.pbo:>6.2f}{c.book_return:>9.3f}{c.gross_return:>10.3f}"
              f"{c.alpha_ann:>9.3f}{c.beta_btc:>7.2f}{c.alpha_t:>7.2f}{c.avg_corr_to_btc:>8.3f}  {kb}")

    print("\n  ===== PRE-REGISTERED VERDICT (read off the ONE pre-registered config, not the grid's best) =====")
    if pre is None:
        print("  ! pre-registered config produced too few bars to score — see grid above.")
    else:
        go = pre.passed and pre.holdout_passed
        print(f"  config           : {pre.label}")
        print(f"  N (leg trades)   : {pre.n_trades}   (min_trades floor {GATES.min_trades})")
        print(f"  net book return  : {pre.book_return:+.4f}   gross: {pre.gross_return:+.4f}   cost-ratio: {pre.cost_ratio:+.3f}")
        print(f"  residual alpha   : {pre.alpha_ann:+.4f} /yr   beta-BTC: {pre.beta_btc:+.3f}   alpha t-stat: {pre.alpha_t:+.2f}")
        print(f"  corr-to-BTC      : {pre.avg_corr_to_btc:+.3f}   DSR: {pre.deflated_sharpe:.3f}   holdout DSR: {pre.holdout_dsr:+.3f}")
        print(f"  killed by        : {','.join(pre.reasons) if pre.reasons else 'PASS'}")
        print(f"\n  >>> {'GO' if go else 'KILL'} — "
              + ("residual alpha collapsed to beta (or <=0)" if not pre.alpha_positive
                 else ("edge eaten by cost / fails gate" if not go else "alpha survives the beta regression AND the gate")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
