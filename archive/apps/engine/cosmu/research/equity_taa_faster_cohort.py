# intent: ANSWER ONE QUESTION — can a FASTER-than-monthly multi-asset momentum / rotation / risk-parity / trend
# strategy survive the SAME locked Gate that only the SLOW monthly equity-TAA cohort (DAA/GEM/Faber/VAA/RP) has
# cleared, or does the edge REQUIRE the monthly cadence? The operator wants profit faster; the surviving books
# rebalance monthly (slow). We author a SMALL, PRE-REGISTERED set of variants that are SIMILAR IN SPIRIT to the
# TAA cohort (cross-sectional sector momentum / dual-momentum / risk-parity / trend) but DIFFERENT and FASTER —
# WEEKLY or DAILY rebalance, SHORTER momentum lookbacks, vol-targeting, faster trend — and route each variant's
# realized NET-of-fee return stream through the EXISTING locked Gate (per-combo BRUT), changing NO threshold.
#
# WHY THIS IS HONEST, NOT GATE-LOOSENING (mirrors research/equity_taa_cohort.py exactly):
#   * The 0.95 DSR, BH-FDR q=0.10, the REAL purged+embargoed holdout (equity_holdout.metrics_with_holdout), the
#     CSCV-PBO overfit guard, the folds/drawdown floors are ALL intact and UNCHANGED. No constant is touched.
#   * The trial population is the N PRE-REGISTERED variants in this file (+ 2 disconfirmers). DSR deflates against
#     that count and BH-FDR corrects across it. Each variant is one fixed config (NO per-variant param search) — its
#     lookback/cadence/target-vol are declared in the spec table below BEFORE any backtest is read.
#   * Two DISCONFIRMERS ride the SAME cohort so FDR/CSCV see them: a Buy&Hold-SPY NULL (resampled to the variant
#     cadence; bench==net so it can never beat itself) and a random-rotation PLACEBO (no signal, pays turnover).
#     Both are EXPECTED to fail; a surviving placebo would make the cohort gate suspect.
#   * The holdout tail is computed inside metrics_with_holdout and never inspected or tuned. An honest FAIL is a FAIL.
#
# DATA — the BINDING constraint, deep-fetched (memory: lesson_data_depth_not_self_capped — never self-cap the
# lookback). A faster rebalance needs DAILY total-return bars. In our equities cache the DEEPEST daily-TR coverage is:
#   * the 9 SPDR sectors XLB/XLE/XLF/XLI/XLK/XLP/XLU/XLV/XLY  (`*_tr.json` are DAILY 1d bars) back to 1998-12  (~27y)
#   * SPY / AGG / GLD  (`*_tr_daily.json`) back to 2003-01 / 2003-09 / 2004-11.
# So the natural deepest universe for a fast cross-sectional book is the 9 sectors (rank/hold) + SPY (regime filter
# + benchmark) + AGG (risk-off sleeve), and for risk-parity {SPY,AGG,GLD}. We use the FULL available daily history
# of each variant (the window binds on its youngest required series), never a truncated last-N-bars slice.
#
# CADENCE — WEEKLY variants resample to Friday (the last trading day on or before each week's Friday); DAILY
# variants step every trading day. The signal for each rebalance period is formed from data through the PRIOR
# period-end (signal@t-1, trade@t — PIT, no look-ahead). Annualization: 52 (weekly) / 252 (daily) periods/year.
#
# FEES — REAL IBKR all-in on liquid ETFs, taker/conservative 1 bp/side, charged on realized one-sided turnover at
# each rebalance. A faster book trades MORE OFTEN, so the fee leg is exactly where a faster cadence should die if it
# is going to — that is the point of the test. We also report the fee sweep {1,2,3,5} bps/side per variant so the
# verdict is not knife-edge.
#
# Propose/measure-only — moves NO money, no merge, no live. ZERO LLM on the gate path; deterministic for fixed data.

from __future__ import annotations

import json
import math
import os
import statistics
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.cohort import Candidate, promote_cohort
from cosmu.master.scorer import BacktestMetrics, cscv_pbo
from cosmu.master.strategy_correlation import pairwise_correlation as _pairwise_corr
from cosmu.master.trials import register_trial, trial_stats_for_cohort
from cosmu.master.verdict_log import durable_persist
from cosmu.research.equity_holdout import metrics_with_holdout, purged_embargoed_split

CACHE = Path(os.environ.get("COSMU_EQUITY_CACHE", "<repo>/.cosmu/market_data/equities"))

# Universe (all carry DEEP daily total-return history in our cache).
SECTORS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]  # 9 SPDR sectors, daily TR from 1998-12
MARKET = "SPY"      # regime-filter instrument + buy-and-hold benchmark (daily TR from 2003-01)
RISK_OFF = "AGG"    # risk-off sleeve (US aggregate bonds; daily TR from 2003-09)
GOLD = "GLD"        # risk-parity third sleeve (daily TR from 2004-11)

IBKR_ETF_BPS_PER_SIDE = 1.0
FEE_SWEEP_BPS = [1.0, 2.0, 3.0, 5.0]
TRADING_DAYS_YR = 252

# Gate scoring needs ENOUGH observations for an honest in-sample + holdout. With weekly bars over ~20y we have ~1000+
# obs; we require >= 120 periods (≈2.3y weekly) so the holdout tail is meaningful for every variant we keep.
MIN_PERIODS = 120
HOLDOUT_FRAC = 0.20


# =============================================================================================================
# DATA — daily total-return loader (handles BOTH `*_tr.json` 1d-cadence sectors and `*_tr_daily.json` SPY/AGG/GLD)
# =============================================================================================================


@dataclass
class DailyTR:
    symbol: str
    ts: list[int]        # ms, ascending
    close: list[float]   # total-return (adjusted) daily close


def _load_daily_tr(symbol: str) -> DailyTR:
    """Load the DEEPEST available daily total-return series for `symbol`.

    Prefer `<sym>_tr_daily.json` (SPY/AGG/GLD); else fall back to `<sym>_tr.json` which, for the SPDR sectors, IS a
    daily 1d total-return series in this cache (verified medgap=1.0d, 6905 rows from 1998-12). NO synthetic fill —
    Yahoo gap days are simply absent; the resampler tolerates that."""
    daily = CACHE / f"{symbol}_tr_daily.json"
    path = daily if daily.exists() else CACHE / f"{symbol}_tr.json"
    rows = json.loads(path.read_text())
    rows.sort(key=lambda r: int(r["ts"]))
    return DailyTR(symbol, [int(r["ts"]) for r in rows], [float(r["close"]) for r in rows])


def _date(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


@dataclass
class Panel:
    """A cadence-resampled total-return panel: one close per PERIOD per symbol, on a shared period axis.

    `periods` is the ascending list of period keys (each key is a sortable tuple). `close[sym][p]` is that symbol's
    total-return close at the END of period p (the last available daily bar in the period). Missing => symbol absent
    that period (no fabrication)."""

    symbols: list[str]
    periods: list[tuple]                       # ascending period keys (week or day)
    close: dict[str, dict[tuple, float]]       # sym -> period -> period-end close
    periods_per_year: int


def _period_key_daily(ms: int) -> tuple:
    d = _date(ms).date()
    return (d.year, d.month, d.day)


def _period_key_weekly(ms: int) -> tuple:
    iso = _date(ms).date().isocalendar()
    return (iso[0], iso[1])


def build_panel(symbols: list[str], *, weekly: bool) -> Panel:
    """Resample each symbol's daily TR series to weekly (last bar per ISO week) or daily, on a shared period axis.

    PIT-safe: a period's close is the LAST realized daily bar that falls in that period; we never look past it."""
    key = _period_key_weekly if weekly else _period_key_daily
    ppy = 52 if weekly else TRADING_DAYS_YR
    close: dict[str, dict[tuple, float]] = {}
    all_periods: set[tuple] = set()
    for sym in symbols:
        s = _load_daily_tr(sym)
        by_p: dict[tuple, tuple[int, float]] = {}
        for t, c in zip(s.ts, s.close, strict=True):
            p = key(t)
            if p not in by_p or t >= by_p[p][0]:
                by_p[p] = (t, c)
        close[sym] = {p: by_p[p][1] for p in by_p}
        all_periods |= set(by_p)
    periods = sorted(all_periods)
    return Panel(symbols, periods, close, ppy)


# index the panel periods once for O(1) neighbour lookups (signal primitives step panel.periods by index directly)
def _index_panel(panel: Panel) -> Panel:
    panel._idx = {p: i for i, p in enumerate(panel.periods)}  # type: ignore[attr-defined]
    return panel


# =============================================================================================================
# SIGNAL PRIMITIVES (operate on the resampled panel; all PIT — period-end p, decide for p+1)
# =============================================================================================================


def _trailing_return(panel: Panel, sym: str, p_idx: int, lookback_periods: int) -> float | None:
    """Total return of `sym` over the trailing `lookback_periods` PANEL periods ending at panel.periods[p_idx]."""
    if p_idx < lookback_periods:
        return None
    p_now = panel.periods[p_idx]
    p_past = panel.periods[p_idx - lookback_periods]
    cs = panel.close.get(sym, {})
    c_now = cs.get(p_now)
    c_past = cs.get(p_past)
    if c_now is None or c_past is None or c_past <= 0:
        return None
    return c_now / c_past - 1.0


def _period_return(panel: Panel, sym: str, p_idx: int) -> float | None:
    """Realized return of holding `sym` THROUGH period panel.periods[p_idx] (close[p]/close[p-1] - 1)."""
    if p_idx < 1:
        return None
    p_now = panel.periods[p_idx]
    p_prev = panel.periods[p_idx - 1]
    cs = panel.close.get(sym, {})
    c_now = cs.get(p_now)
    c_prev = cs.get(p_prev)
    if c_now is None or c_prev is None or c_prev <= 0:
        return None
    return c_now / c_prev - 1.0


def _sma_close(panel: Panel, sym: str, p_idx: int, window_periods: int) -> float | None:
    """Trailing `window_periods`-period SMA of `sym`'s period-end close ending at p_idx (the regime filter)."""
    if p_idx + 1 < window_periods:
        return None
    cs = panel.close.get(sym, {})
    vals = []
    for j in range(p_idx - window_periods + 1, p_idx + 1):
        v = cs.get(panel.periods[j])
        if v is None:
            return None
        vals.append(v)
    return statistics.fmean(vals)


def _realized_vol(panel: Panel, sym: str, p_idx: int, lookback_periods: int) -> float | None:
    """Annualized stdev of the trailing `lookback_periods` PERIOD returns of `sym` ending at p_idx (for vol-target /
    inverse-vol weighting). Uses the panel's own cadence, annualized by periods_per_year."""
    if p_idx < lookback_periods:
        return None
    rets: list[float] = []
    for j in range(p_idx - lookback_periods + 1, p_idx + 1):
        r = _period_return(panel, sym, j)
        if r is None:
            return None
        rets.append(r)
    if len(rets) < 2:
        return None
    sd = statistics.pstdev(rets)
    return sd * math.sqrt(panel.periods_per_year)


# =============================================================================================================
# BACKTEST ENGINE — generic weighted multi-asset book on the panel; signal-fn returns target weights at period-end
# =============================================================================================================


@dataclass
class StreamResult:
    periods: list[tuple]
    net: list[float]
    gross: list[float]
    bench: list[float]          # buy-and-hold SPY return over the SAME periods (the require_beat hurdle)
    turnover_sum: float
    n_rebalances: int           # periods where the book actually traded (turnover>0)


def _first_tradeable_idx(panel: Panel, warmup_periods: int) -> int:
    """First period index at which the longest warmup window is satisfied for SPY (the always-present anchor) so a
    signal can be formed. Concrete per-variant warmups are enforced inside each signal-fn returning None."""
    return max(warmup_periods, 1)


def run_book(panel: Panel, signal_fn, *, fee_bps_per_side: float, warmup_periods: int,
             start_idx: int | None = None) -> StreamResult:
    """Step the panel period-by-period. For each period p (>= warmup), form target weights from data through p-1
    (signal_fn(panel, p-1)) and realize the book return over period p. Charge a one-sided turnover fee at the
    rebalance. SPY must have a realized return each period (the benchmark + liquidity anchor)."""
    fee = fee_bps_per_side / 1e4
    p0 = start_idx if start_idx is not None else _first_tradeable_idx(panel, warmup_periods)
    periods_out: list[tuple] = []
    net_r: list[float] = []
    gross_r: list[float] = []
    bench_r: list[float] = []
    turnover_sum = 0.0
    n_reb = 0
    prev_w: dict[str, float] | None = None
    for i in range(p0, len(panel.periods)):
        w = signal_fn(panel, i - 1)  # decide at the PRIOR period-end (PIT)
        if w is None:
            continue
        # require every held leg + SPY to have a realized return this period (no synthetic fill)
        legs: dict[str, float] = {}
        ok = True
        for sym in w:
            r = _period_return(panel, sym, i)
            if r is None:
                ok = False
                break
            legs[sym] = r
        spy = _period_return(panel, MARKET, i)
        if not ok or spy is None:
            continue
        gross = sum(w[sym] * legs[sym] for sym in w)
        if prev_w is None:
            turnover = 1.0  # initial deployment pays one side on the full notional
        else:
            names = set(w) | set(prev_w)
            turnover = 0.5 * sum(abs(w.get(s, 0.0) - prev_w.get(s, 0.0)) for s in names)
        if turnover > 1e-9 and prev_w is not None:
            n_reb += 1
        turnover_sum += turnover
        net = gross - turnover * fee
        periods_out.append(panel.periods[i])
        gross_r.append(gross)
        net_r.append(net)
        bench_r.append(spy)
        prev_w = w
    return StreamResult(periods_out, net_r, gross_r, bench_r, turnover_sum, n_reb)


# =============================================================================================================
# THE PRE-REGISTERED VARIANTS (each = ONE fixed config; the spec is declared here BEFORE any backtest is read)
# =============================================================================================================


def _sig_sector_mom(top_k: int, lookback_periods: int, sma_periods: int | None):
    """Cross-sectional sector momentum: optional SPY-vs-SMA regime filter, then hold the top-k of 9 sectors by
    trailing-`lookback_periods` total return, equal-weight. Risk-off -> AGG when the regime filter is bearish."""
    def fn(panel: Panel, p_idx: int) -> dict[str, float] | None:
        if sma_periods is not None:
            sma = _sma_close(panel, MARKET, p_idx, sma_periods)
            spy_c = panel.close.get(MARKET, {}).get(panel.periods[p_idx]) if p_idx < len(panel.periods) else None
            if sma is None or spy_c is None:
                return None
            if spy_c < sma:
                return {RISK_OFF: 1.0}
        scored: list[tuple[str, float]] = []
        for sym in SECTORS:
            r = _trailing_return(panel, sym, p_idx, lookback_periods)
            if r is not None:
                scored.append((sym, r))
        if len(scored) < top_k:
            return None
        scored.sort(key=lambda x: x[1], reverse=True)
        held = [s for s, _ in scored[:top_k]]
        return {s: 1.0 / top_k for s in held}
    return fn


def _sig_sector_dualmom(top_k: int, lookback_periods: int):
    """Sector DUAL momentum: rank by trailing return AND require absolute momentum > 0 (else that slot goes to AGG).
    No SMA; the absolute-momentum filter IS the de-risk. Daily-capable, fully cross-sectional + trend-aware."""
    def fn(panel: Panel, p_idx: int) -> dict[str, float] | None:
        scored: list[tuple[str, float]] = []
        for sym in SECTORS:
            r = _trailing_return(panel, sym, p_idx, lookback_periods)
            if r is not None:
                scored.append((sym, r))
        if len(scored) < top_k:
            return None
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:top_k]
        w: dict[str, float] = {}
        for sym, r in top:
            tgt = sym if r > 0 else RISK_OFF  # absolute-momentum: park in bonds if the sector itself is falling
            w[tgt] = w.get(tgt, 0.0) + 1.0 / top_k
        return w
    return fn


def _sig_accel_dualmom(top_k: int, lbs: tuple[int, ...]):
    """ACCELERATING dual momentum on sectors: score = mean of the trailing-return over several SHORT lookbacks
    (e.g. ~1/3/6-month equivalents in panel periods). Hold top-k; abs-mom filter -> AGG. Faster analogue of ADM."""
    def fn(panel: Panel, p_idx: int) -> dict[str, float] | None:
        scored: list[tuple[str, float]] = []
        for sym in SECTORS:
            parts = [_trailing_return(panel, sym, p_idx, lb) for lb in lbs]
            if any(x is None for x in parts):
                continue
            scored.append((sym, statistics.fmean(parts)))  # type: ignore[arg-type]
        if len(scored) < top_k:
            return None
        scored.sort(key=lambda x: x[1], reverse=True)
        w: dict[str, float] = {}
        for sym, sc in scored[:top_k]:
            tgt = sym if sc > 0 else RISK_OFF
            w[tgt] = w.get(tgt, 0.0) + 1.0 / top_k
        return w
    return fn


def _sig_risk_parity(vol_lookback_periods: int):
    """Inverse-realized-vol risk parity on {SPY, AGG, GLD}, rebalanced at the panel cadence (the FAST analogue of the
    monthly RP sleeve)."""
    assets = [MARKET, RISK_OFF, GOLD]
    def fn(panel: Panel, p_idx: int) -> dict[str, float] | None:
        inv: dict[str, float] = {}
        for sym in assets:
            v = _realized_vol(panel, sym, p_idx, vol_lookback_periods)
            if v is None or v <= 0:
                return None
            inv[sym] = 1.0 / v
        tot = sum(inv.values())
        if tot <= 0:
            return None
        return {s: inv[s] / tot for s in assets}
    return fn


def _sig_voltarget_sector_mom(top_k: int, lookback_periods: int, vol_lookback_periods: int, target_vol: float):
    """Vol-targeted sector momentum: pick top-k sectors by momentum (equal-weight), then SCALE total equity exposure
    so the equal-weight basket's realized vol ~= `target_vol` annual; the un-deployed fraction parks in AGG (cash
    proxy). Caps leverage at 1.0 (long-only, no borrowing). Faster + risk-managed."""
    base = _sig_sector_mom(top_k, lookback_periods, sma_periods=None)
    def fn(panel: Panel, p_idx: int) -> dict[str, float] | None:
        raw = base(panel, p_idx)
        if raw is None:
            return None
        # realized vol of the equal-weight basket = avg leg vol scaled by intra-basket correlation; approximate with
        # the mean of the legs' own realized vols (conservative: ignores diversification, so we never over-lever).
        vols = []
        for sym in raw:
            v = _realized_vol(panel, sym, p_idx, vol_lookback_periods)
            if v is None or v <= 0:
                return None
            vols.append(v)
        basket_vol = statistics.fmean(vols)
        scale = min(1.0, target_vol / basket_vol) if basket_vol > 0 else 0.0
        w = {sym: raw[sym] * scale for sym in raw}
        cash = 1.0 - sum(w.values())
        if cash > 1e-9:
            w[RISK_OFF] = w.get(RISK_OFF, 0.0) + cash  # park the de-levered fraction in bonds
        return w
    return fn


def _sig_fast_trend(top_k: int, lookback_periods: int, sma_periods: int):
    """Fast trend: SPY vs a SHORT SMA (e.g. ~100-day equivalent). Risk-on -> top-k sector momentum; risk-off -> AGG.
    The monthly sector rotation uses a 200-DAY SMA; this is the FASTER trend filter (shorter SMA + faster rebalance)."""
    return _sig_sector_mom(top_k, lookback_periods, sma_periods=sma_periods)


# --- disconfirmers (ride the cohort so FDR/CSCV see them; both EXPECTED to fail) ------------------------------


def _sig_spy_null():
    """Buy & Hold SPY at the panel cadence. bench == net by construction, so it can NEVER beat itself (fails
    require_beat_buy_and_hold). A directional gate that promoted plain beta would be broken."""
    def fn(panel: Panel, p_idx: int) -> dict[str, float] | None:
        return {MARKET: 1.0}
    return fn


def _sig_random_placebo(lookback_periods: int, seed: int = 7):
    """Rotate into a DETERMINISTIC pseudo-random sector each period and pay the turnover. No signal -> should fail
    the holdout/DSR. A real PLACEBO guard on the cohort (uses lookback only to match the warmup of real variants)."""
    def fn(panel: Panel, p_idx: int) -> dict[str, float] | None:
        if p_idx < lookback_periods:
            return None
        pick = SECTORS[hash((seed, panel.periods[p_idx])) % len(SECTORS)]
        return {pick: 1.0}
    return fn


@dataclass
class VariantSpec:
    name: str
    label: str
    weekly: bool                # True => weekly cadence; False => daily
    warmup_periods: int         # longest trailing window the signal needs (binds the first tradeable period)
    signal_factory: object      # a zero-arg-bound signal-fn (closure over its fixed params)
    is_disconfirmer: bool = False
    cadence_days: float = 0.0   # nominal rebalance spacing in calendar days (7 weekly / ~1.4 daily) — for the report


# ---------------------------------------------------------------------------------------------------------------
# THE PRE-REGISTERED SLATE. Each row is ONE fixed config. Lookbacks are in PANEL PERIODS:
#   weekly: 13w≈3mo, 26w≈6mo, 4w≈1mo, 40w≈200d-SMA, 20w≈100d-SMA, 12w≈60d-vol.
#   daily : 120d≈6mo, 100d-SMA, 60d-vol, 20d≈1mo.
# ---------------------------------------------------------------------------------------------------------------
def build_specs() -> list[VariantSpec]:
    return [
        # 1. WEEKLY sector momentum, top-3, 13-week (~3mo) lookback, 40-week (~200d) SMA regime filter.
        VariantSpec("wk_sector_mom_13w_top3_sma40", "Weekly sector mom top-3 · 13w lb · 200d-SMA regime",
                    weekly=True, warmup_periods=40, cadence_days=7.0,
                    signal_factory=_sig_sector_mom(top_k=3, lookback_periods=13, sma_periods=40)),
        # 2. WEEKLY sector momentum, top-3, 26-week (~6mo) lookback — SAME lookback as the monthly book, faster cadence.
        VariantSpec("wk_sector_mom_26w_top3_sma40", "Weekly sector mom top-3 · 26w lb · 200d-SMA regime",
                    weekly=True, warmup_periods=40, cadence_days=7.0,
                    signal_factory=_sig_sector_mom(top_k=3, lookback_periods=26, sma_periods=40)),
        # 3. WEEKLY sector DUAL-momentum, top-3, 13-week lookback, absolute-momentum -> AGG (no SMA).
        VariantSpec("wk_sector_dualmom_13w_top3", "Weekly sector dual-mom top-3 · 13w lb · abs-mom→AGG",
                    weekly=True, warmup_periods=13, cadence_days=7.0,
                    signal_factory=_sig_sector_dualmom(top_k=3, lookback_periods=13)),
        # 4. WEEKLY accelerating dual-momentum on sectors (mean of 4/13/26-week ≈ 1/3/6-mo), top-3, abs-mom -> AGG.
        VariantSpec("wk_accel_dualmom_4_13_26_top3", "Weekly accel dual-mom top-3 · avg(4,13,26w) · abs-mom→AGG",
                    weekly=True, warmup_periods=26, cadence_days=7.0,
                    signal_factory=_sig_accel_dualmom(top_k=3, lbs=(4, 13, 26))),
        # 5. WEEKLY risk parity inverse-vol {SPY,AGG,GLD}, 12-week (~60d) vol lookback.
        VariantSpec("wk_risk_parity_12w", "Weekly risk-parity inverse-vol SPY/AGG/GLD · 12w vol",
                    weekly=True, warmup_periods=12, cadence_days=7.0,
                    signal_factory=_sig_risk_parity(vol_lookback_periods=12)),
        # 6. WEEKLY vol-targeted sector momentum, top-3, 13-week lb, 12-week vol, 10% annual target vol (AGG buffer).
        VariantSpec("wk_voltgt10_sector_mom_13w_top3", "Weekly vol-tgt 10% sector mom top-3 · 13w lb · AGG buffer",
                    weekly=True, warmup_periods=13, cadence_days=7.0,
                    signal_factory=_sig_voltarget_sector_mom(top_k=3, lookback_periods=13,
                                                             vol_lookback_periods=12, target_vol=0.10)),
        # 7. WEEKLY FAST trend: SPY vs 20-week (~100d) SMA -> top-3 sector mom (13w) else AGG (faster trend filter).
        VariantSpec("wk_fast_trend_sma20_sector13_top3", "Weekly fast-trend 100d-SMA → sector mom top-3 · 13w",
                    weekly=True, warmup_periods=20, cadence_days=7.0,
                    signal_factory=_sig_fast_trend(top_k=3, lookback_periods=13, sma_periods=20)),
        # 8. DAILY sector dual-momentum, top-3, 120-day (~6mo) lookback, abs-mom -> AGG (the fastest cross-sectional).
        VariantSpec("dy_sector_dualmom_120d_top3", "Daily sector dual-mom top-3 · 120d lb · abs-mom→AGG",
                    weekly=False, warmup_periods=120, cadence_days=1.4,
                    signal_factory=_sig_sector_dualmom(top_k=3, lookback_periods=120)),
        # 9. DAILY fast trend: SPY vs 100-day SMA -> top-3 sector mom (120d) else AGG.
        VariantSpec("dy_fast_trend_sma100_sector120_top3", "Daily fast-trend 100d-SMA → sector mom top-3 · 120d",
                    weekly=False, warmup_periods=120, cadence_days=1.4,
                    signal_factory=_sig_fast_trend(top_k=3, lookback_periods=120, sma_periods=100)),
        # --- disconfirmers ---
        VariantSpec("disc_wk_buyhold_spy_null", "Buy & Hold SPY (NULL, weekly)", weekly=True, warmup_periods=2,
                    cadence_days=7.0, signal_factory=_sig_spy_null(), is_disconfirmer=True),
        VariantSpec("disc_wk_random_rotation", "Random weekly sector rotation (PLACEBO)", weekly=True,
                    warmup_periods=13, cadence_days=7.0, signal_factory=_sig_random_placebo(lookback_periods=13),
                    is_disconfirmer=True),
    ]


# =============================================================================================================
# BUILD EACH VARIANT'S REALIZED NET STREAM (the SAME object the Gate scores)
# =============================================================================================================


@dataclass
class VariantStream:
    spec: VariantSpec
    periods: list[tuple]
    net: list[float]
    gross: list[float]
    bench: list[float]
    periods_per_year: int
    turnover_per_year: float
    fee_sweep: dict[float, tuple[float, float, float]]  # bps -> (ann_sharpe, total_return, max_dd) on NET


def _ann_stats(returns: list[float], ppy: int) -> tuple[float, float, float]:
    """(annualized Sharpe, compounded total return, max drawdown) of a return stream."""
    n = len(returns)
    if n == 0:
        return (0.0, 0.0, 0.0)
    equity = peak = 1.0
    mdd = 0.0
    for r in returns:
        equity *= 1.0 + r
        peak = max(peak, equity)
        mdd = max(mdd, (peak - equity) / peak if peak > 0 else 0.0)
    total = equity - 1.0
    mean = statistics.fmean(returns)
    sd = statistics.pstdev(returns) if n > 1 else 0.0
    sharpe = (mean / sd) * math.sqrt(ppy) if sd > 0 else 0.0
    return (sharpe, total, mdd)


# panel cache so we build each cadence's panel once (the universes differ slightly, key by frozenset+cadence)
_PANEL_CACHE: dict[tuple, Panel] = {}


def _panel_for(symbols: list[str], weekly: bool) -> Panel:
    k = (frozenset(symbols), weekly)
    if k not in _PANEL_CACHE:
        _PANEL_CACHE[k] = _index_panel(build_panel(symbols, weekly=weekly))
    return _PANEL_CACHE[k]


def build_variant_stream(spec: VariantSpec) -> VariantStream | None:
    # the universe a variant touches: sectors + SPY + AGG always; risk-parity also needs GLD.
    syms = list(dict.fromkeys([*SECTORS, MARKET, RISK_OFF, GOLD])) if "risk_parity" in spec.name \
        else list(dict.fromkeys([*SECTORS, MARKET, RISK_OFF]))
    panel = _panel_for(syms, spec.weekly)
    res = run_book(panel, spec.signal_factory, fee_bps_per_side=IBKR_ETF_BPS_PER_SIDE,
                   warmup_periods=spec.warmup_periods)
    if len(res.net) < MIN_PERIODS:
        print(f"  [skip] {spec.name}: only {len(res.net)} periods (<{MIN_PERIODS})", file=sys.stderr)
        return None
    yrs = len(res.net) / panel.periods_per_year
    sweep: dict[float, tuple[float, float, float]] = {}
    for fee in FEE_SWEEP_BPS:
        r = run_book(panel, spec.signal_factory, fee_bps_per_side=fee, warmup_periods=spec.warmup_periods)
        sweep[fee] = _ann_stats(r.net, panel.periods_per_year)
    return VariantStream(spec, res.periods, res.net, res.gross, res.bench, panel.periods_per_year,
                         res.turnover_sum / max(yrs, 1e-9), sweep)


# =============================================================================================================
# THE GATE (composes the existing locked machinery — identical pattern to equity_taa_cohort.run)
# =============================================================================================================


def _embargo_for(spec: VariantSpec) -> int:
    """Embargo (in panel periods) >= the variant's longest formation window so no held-out signal is computed from
    an in-sample bar. We use warmup_periods (the longest trailing window any signal uses)."""
    return max(spec.warmup_periods, 1)


def _insample_total(stream: list[float], embargo: int) -> float:
    split = purged_embargoed_split(stream, holdout_frac=HOLDOUT_FRAC, embargo=embargo)
    total = 1.0
    for r in split.in_sample:
        total *= 1.0 + r
    return total - 1.0


def _metrics(vs: VariantStream, *, trials_counted: int) -> BacktestMetrics:
    embargo = _embargo_for(vs.spec)
    metrics, _ = metrics_with_holdout(
        vs.net, trials_counted=trials_counted, periods_per_year=vs.periods_per_year,
        holdout_frac=HOLDOUT_FRAC, embargo=embargo, long_only=True,
        bench_return=_insample_total(vs.bench, embargo),
    )
    return metrics


def _cohort_pbo(streams: list[VariantStream]) -> float:
    """CSCV-PBO across the cohort on the COMMON-period IN-SAMPLE slice only. Weekly and daily variants live on
    DIFFERENT axes, so we compute PBO within the WEEKLY sub-cohort (the majority) — the daily variants are PBO-guarded
    individually via their own holdout. Aligning only the same-cadence members keeps the configs comparable."""
    weekly = [s for s in streams if s.spec.weekly]
    if len(weekly) < 2:
        return 0.0
    common = sorted(set.intersection(*[set(s.periods) for s in weekly]))
    n = len(common)
    h = round(n * HOLDOUT_FRAC)
    embargo = max(_embargo_for(s.spec) for s in weekly)
    is_n = n - h - embargo
    if is_n < 24:
        return 1.0
    is_periods = common[:is_n]
    aligned: list[list[float]] = []
    for s in weekly:
        by_p = dict(zip(s.periods, s.net, strict=True))
        aligned.append([by_p[p] for p in is_periods])
    return cscv_pbo(aligned)


@dataclass
class FasterRow:
    name: str
    label: str
    is_disconfirmer: bool
    cadence: str
    rebal_per_year: float
    turnover_per_year: float
    n_periods: int
    ann_sharpe: float
    sharpe_per_obs: float
    deflated_sharpe_prob: float
    holdout_dsr: float
    pbo: float
    folds_positive: float
    max_dd: float
    in_sample_total: float
    spy_in_sample_total: float
    net_total_full: float       # full-stream net total (all bps=1) — the headline return
    fee_sweep: dict[float, tuple[float, float, float]]
    promoted_strict: bool
    survived_dsr_holdout: bool
    survived_fdr: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class FasterVerdict:
    n_candidates: int
    window: str
    cohort_pbo: float
    rows: list[FasterRow]
    strict_survivors: list[str]
    dsr_holdout_survivors: list[str]
    fastest_survivor_cadence: str | None
    verdict: str
    headline: str


def run(*, persist: bool = False) -> FasterVerdict:
    specs = build_specs()
    streams: list[VariantStream] = []
    for sp in specs:
        try:
            vs = build_variant_stream(sp)
        except Exception as exc:  # noqa: BLE001 — a variant that can't load is an honest skip
            print(f"  [skip] {sp.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        if vs is not None:
            streams.append(vs)
    if len(streams) < 3:
        return FasterVerdict(len(streams), "n/a", 1.0, [], [], [], None, "INSUFFICIENT-DATA",
                             "fewer than 3 faster variants loaded")

    store = Store(Settings(database_url=f"sqlite:///{tempfile.mkdtemp(prefix='cosmu-taa-fast-')}/g.sqlite3",
                           openrouter_api_key=None))
    gates = store.settings.gates  # the FULL default gate — no threshold is changed

    trials_counted = len(streams)
    metrics_by_name: dict[str, BacktestMetrics] = {}
    cohort_pbo = _cohort_pbo(streams)

    for vs in streams:
        m = _metrics(vs, trials_counted=trials_counted)
        m = m.model_copy(update={"pbo": Decimal(str(round(cohort_pbo, 6)))})
        metrics_by_name[vs.spec.name] = m
        register_trial(store, float(m.sharpe_per_obs), source="equity_taa_faster", label=vs.spec.name)

    # correlation haircut on the SAME-cadence common window (weekly sub-cohort) — effective-K, not raw K.
    weekly = [s for s in streams if s.spec.weekly]
    _common = sorted(set.intersection(*[set(s.periods) for s in weekly])) if len(weekly) >= 2 else []
    _sd = {
        s.spec.name: [dict(zip(s.periods, s.net, strict=True))[p] for p in _common]
        for s in weekly if s.net
    } if len(_common) >= 2 else {}
    _corr = _pairwise_corr(_sd) if len(_sd) >= 2 else None
    _rho_bar = _corr.average_pairwise_correlation if _corr is not None else None
    trials = trial_stats_for_cohort(store, trials_counted, _rho_bar)

    candidates = [
        Candidate(id=vs.spec.name, metrics=metrics_by_name[vs.spec.name],
                  net_profit=float(metrics_by_name[vs.spec.name].oos_return), source="equity_taa_faster",
                  label=vs.spec.label,
                  return_variance=(statistics.pvariance(vs.net) if len(vs.net) > 1 else 1.0) or 1.0)
        for vs in streams
    ]

    persist_spec = durable_persist(
        run_id="equity-taa-faster-cohort",
        hypothesis="a FASTER-than-monthly (weekly/daily) multi-asset momentum/rotation/risk-parity/trend book "
                   "survives the SAME locked Gate (DSR>=0.95 + real holdout + BH-FDR + PBO) that only the slow "
                   "MONTHLY equity-TAA cohort has cleared — or the edge requires the monthly cadence",
        source="research/equity_taa_faster_cohort", data_source="equities-daily-tr",
        universe="9-spdr-sectors+SPY+AGG(+GLD)-daily-total-return",
    ) if persist else None

    promotions = promote_cohort(store, candidates, gates, fdr_q=0.10, register=False, trials=trials,
                                persist=persist_spec)
    by_id = {p.candidate_id: p for p in promotions}

    rows: list[FasterRow] = []
    for vs in streams:
        m = metrics_by_name[vs.spec.name]
        p = by_id[vs.spec.name]
        reasons = list(p.reasons)
        dsr_holdout_ok = not [r for r in reasons if r != "buy_and_hold"]
        full_sharpe, full_total, _ = _ann_stats(vs.net, vs.periods_per_year)
        rows.append(FasterRow(
            name=vs.spec.name, label=vs.spec.label, is_disconfirmer=vs.spec.is_disconfirmer,
            cadence="weekly" if vs.spec.weekly else "daily",
            rebal_per_year=(52.0 if vs.spec.weekly else 252.0), turnover_per_year=round(vs.turnover_per_year, 2),
            n_periods=m.num_trades, ann_sharpe=float(m.sharpe), sharpe_per_obs=float(m.sharpe_per_obs),
            deflated_sharpe_prob=round(float(p.deflated_sharpe_prob), 6),
            holdout_dsr=round(float(m.holdout_deflated_sharpe), 6), pbo=float(m.pbo),
            folds_positive=float(m.folds_positive_pct), max_dd=float(m.max_drawdown),
            in_sample_total=round(float(m.oos_return), 6), spy_in_sample_total=round(float(m.buy_and_hold_return), 6),
            net_total_full=round(full_total, 6), fee_sweep=vs.fee_sweep,
            promoted_strict=p.promoted, survived_dsr_holdout=dsr_holdout_ok, survived_fdr=p.survived_fdr,
            reasons=reasons,
        ))

    rows.sort(key=lambda r: (r.promoted_strict, r.survived_dsr_holdout, r.deflated_sharpe_prob), reverse=True)
    strict = [r.name for r in rows if r.promoted_strict and not r.is_disconfirmer]
    dsr_hold = [r.name for r in rows if r.survived_dsr_holdout and not r.is_disconfirmer]

    all_p = sorted({p for s in streams for p in s.periods})
    window = f"{all_p[0]} .. {all_p[-1]}" if all_p else "n/a"

    # fastest surviving cadence: among survivors (strict first, else dsr-holdout), the one with the most rebalances/yr.
    survivor_names = strict or dsr_hold
    fastest_cadence: str | None = None
    if survivor_names:
        surv_rows = [r for r in rows if r.name in survivor_names]
        fastest = max(surv_rows, key=lambda r: r.rebal_per_year)
        fastest_cadence = fastest.cadence

    if strict:
        verdict = "PASS-STRICT"
        headline = (f"{len(strict)} FASTER variant(s) SURVIVED the FULL gate (DSR>=0.95 + real holdout + BH-FDR + "
                    f"beat-B&H-SPY) — faster-than-monthly TAA IS feasible: {', '.join(strict)}")
    elif dsr_hold:
        verdict = "PASS-DSR-HOLDOUT"
        headline = (f"{len(dsr_hold)} FASTER variant(s) cleared DSR>=0.95 + positive real holdout + BH-FDR + PBO "
                    f"(risk-adjusted-superior but not out-returning SPY in-sample): {', '.join(dsr_hold)}")
    else:
        verdict = "NO-SURVIVOR"
        headline = ("NO faster-than-monthly variant cleared the honest Gate — on this universe the multi-asset "
                    "momentum edge REQUIRES the slow monthly cadence (the fee/turnover drag of weekly/daily "
                    "rebalancing kills the risk-adjusted edge)")

    return FasterVerdict(len(streams), window, round(cohort_pbo, 6), rows, strict, dsr_hold, fastest_cadence,
                         verdict, headline)


def _print(v: FasterVerdict) -> None:
    print("\n" + "=" * 128)
    print("FASTER-THAN-MONTHLY EQUITY-TAA VARIANTS — weekly/daily multi-asset momentum through the LOCKED Gate")
    print(f"  candidates={v.n_candidates}  window={v.window}  weekly-sub-cohort CSCV-PBO={v.cohort_pbo:.3f}")
    print("  gate: DSR>=0.95 vs trial-inflated benchmark · BH-FDR q=0.10 · REAL purged+embargoed holdout · net of "
          "REAL IBKR fees (1bps/side taker) · NO threshold changed")
    print("=" * 128)
    print(f"  {'variant':<52} {'cad':>6} {'reb/y':>6} {'trn/y':>6} {'n':>5} {'annSR':>6} {'DSR':>6} "
          f"{'hldDSR':>7} {'PBO':>5} {'fold+':>5} {'maxDD':>6} {'IStot':>8} {'SPYis':>8} {'netTot':>9}  flags")
    for r in v.rows:
        if r.promoted_strict:
            flag = "STRICT-PASS"
        elif r.survived_dsr_holdout:
            flag = "DSR+HOLDOUT"
        else:
            flag = ("fdr-only" if r.survived_fdr else "stop")
        tag = " [disc]" if r.is_disconfirmer else ""
        print(f"  {r.label[:52]:<52} {r.cadence[:6]:>6} {r.rebal_per_year:>6.0f} {r.turnover_per_year:>6.1f} "
              f"{r.n_periods:>5} {r.ann_sharpe:>6.2f} {r.deflated_sharpe_prob:>6.3f} {r.holdout_dsr:>+7.3f} "
              f"{r.pbo:>5.2f} {r.folds_positive:>5.2f} {r.max_dd:>6.3f} {r.in_sample_total:>+8.1%} "
              f"{r.spy_in_sample_total:>+8.1%} {r.net_total_full:>+9.1%}  {flag}{tag}")
        if r.reasons:
            print(f"  {'':<52} reasons: {', '.join(r.reasons)}")
        sweep = "  ".join(f"{int(b)}bps:SR{r.fee_sweep[b][0]:+.2f}" for b in sorted(r.fee_sweep))
        print(f"  {'':<52} fee-sweep(net annSR): {sweep}")
    print("-" * 128)
    print(f"  VERDICT: {v.verdict}")
    if v.fastest_survivor_cadence:
        print(f"  fastest surviving cadence: {v.fastest_survivor_cadence}")
    print(f"  {v.headline}")
    print("=" * 128)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    v = run(persist="--persist" in argv)
    _print(v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
