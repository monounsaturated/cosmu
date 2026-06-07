# intent: the cross-venue funding-DISPERSION cohort harness — the orthogonal axis to single-venue funding.
# Build per-symbol cross-exchange funding SPREAD / DISPERSION features (Binance vs Bybit vs OKX), author them
# as a family of mean-reversion / carry / crowding hypotheses, and route the family verdict through the EXISTING
# deterministic scorer + promote_cohort BH-FDR (q=0.10) on REAL bars + REAL multi-venue funding + PIT fees, as
# ONE cohort so the multiple-testing correction applies across the family. inputs: cached real daily perp bars
# (offline JSON read — NEVER fetch/write the shared cache) + cached real funding from THREE venues
# (Binance binance_funding/, Bybit + OKX xvenue_funding/) + a fresh-tempfile Store for the trial ledger;
# outputs: a CohortReport. invariants: ZERO LLM calls; the scorer's statistical thresholds + promote_cohort
# q=0.10 are NOT changed here (we only INTERPRET); funding spreads are SIGNALS/CONDITIONS, never a carry premium
# to harvest; ALL features are point-in-time (each venue's rate align-as-of the bar close — no look-ahead);
# every grid variant is recorded as a trial so deflation/FDR see the true count; deterministic for a fixed
# cache; real perp taker ~5bps; honest about data depth — the OKX venue is API-capped at ~90d so the 3-venue
# (max-min) axis is intrinsically thin; the deep, gateable axis is Binance-Bybit (~730d). A FAIL or an
# INSUFFICIENT-DATA verdict is valid; we do NOT tune to pass.
#
# Disconfirmers (pre-registered): (a) PRICE-ONLY control — the same entries minus the dispersion feature, same
# costs; the dispersion edge must beat it. (b) SHUFFLE placebo — the dispersion series circularly permuted
# (PIT-preserving block shuffle) must NOT reproduce the edge; if it does, the "edge" is an artefact.

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cosmu.data.backtest import (
    _regime_labels,
    align_asof,
    run_strategy_backtest_detailed,
)
from cosmu.data.market import Bar
from cosmu.data.providers._types import AltDataPoint
from cosmu.data.providers.funding import CachedFundingRateProvider
from cosmu.knowledge.store import Store
from cosmu.master.cohort import Candidate, promote_cohort
from cosmu.master.scorer import cscv_pbo, score
from cosmu.master.trials import record_trial, trial_stats
from cosmu.strategy.spec import StrategySpec

# The cross-venue feature names this harness COMPUTES and joins via the alt dict (read through the backtest's
# _feature_matrix else-branch, exactly like xsec_momentum_rank — NOT store-routed, NOT a registry feature).
FEAT_SPREAD_BYBIT = "fund_spread_bybit"   # Binance_rate - Bybit_rate   (per-period, per-symbol)
FEAT_SPREAD_OKX = "fund_spread_okx"       # Binance_rate - OKX_rate
FEAT_DISP = "fund_disp"                   # max - min across all venues present at the bar (>= 0)
FEAT_DISP_RANK = "fund_disp_rank"         # cross-sectional [0,1] percentile of fund_disp across the universe
FEAT_SPREAD_BYBIT_RANK = "fund_spread_bybit_rank"  # cross-sectional [0,1] percentile of the SIGNED B-Bybit spread

# Perp realistic taker (the prompt's "real perp taker ~5bps"): Binance USDⓈ-M taker, VIP0 ~4-5bps.
PERP_TAKER_BPS = Decimal("5")

# The 21 symbols present on ALL THREE venues' funding caches AND with deep daily perp bars (computed once;
# see the overlap audit). Binance funding starts 2024-06 (the binding depth limit for the deep Bybit axis).
TRIVENUE_SYMBOLS = [
    "ADAUSDT", "ALGOUSDT", "APTUSDT", "ARBUSDT", "AVAXUSDT", "BCHUSDT", "CHZUSDT", "DOGEUSDT",
    "DOTUSDT", "FILUSDT", "GRTUSDT", "INJUSDT", "LDOUSDT", "LINKUSDT", "LTCUSDT", "MANAUSDT",
    "NEARUSDT", "OPUSDT", "SANDUSDT", "TRXUSDT", "UNIUSDT",
]

_BAR_CACHE = Path(".cosmu/market_data/binanceperp")
_BYBIT_DIR = Path(".cosmu/xvenue_funding/bybit")
_OKX_DIR = Path(".cosmu/xvenue_funding/okx")


# --------------------------------------------------------------------------- offline data assembly (PIT, real)


def _read_bars_offline(symbol: str, timeframe: str = "1d") -> list[Bar]:
    """Read the deep perp bar cache DIRECTLY (offline JSON) — never via a provider that could fetch/write the
    shared cache (the DOCTRINE footgun). Returns ascending Bar records."""
    path = _BAR_CACHE / f"{symbol}_{timeframe}.json"
    if not path.exists():
        return []
    rows = json.loads(path.read_text())
    out: list[Bar] = []
    for r in rows:
        out.append(Bar(
            ts=datetime.fromtimestamp(int(r["ts"]) / 1000, tz=UTC),
            open=Decimal(str(r["open"])), high=Decimal(str(r["high"])),
            low=Decimal(str(r["low"])), close=Decimal(str(r["close"])), volume=Decimal(str(r["volume"])),
        ))
    out.sort(key=lambda b: b.ts)
    return out


def _read_xvenue_funding(directory: Path, symbol: str) -> list[AltDataPoint]:
    """Read a Bybit/OKX funding JSON ([{ts_ms, funding_rate}]) as ascending AltDataPoints.
    available_at == ts (the exchange publishes the realized rate at the settlement instant — PIT, no look-ahead)."""
    path = directory / f"{symbol}.json"
    if not path.exists():
        return []
    rows = json.loads(path.read_text())
    out: list[AltDataPoint] = []
    for r in rows:
        ts = datetime.fromtimestamp(int(r["ts_ms"]) / 1000, tz=UTC)
        out.append(AltDataPoint(ts=ts, available_at=ts, value=float(r["funding_rate"])))
    out.sort(key=lambda p: p.ts)
    return out


def _xvenue_funding_alt(
    market: dict[str, list[Bar]],
    binance: CachedFundingRateProvider,
) -> tuple[dict[str, dict[str, dict[str, float]]], dict[str, int]]:
    """Build the PIT cross-venue funding feature join: symbol -> {feature -> {bar.ts.isoformat(): value}}.

    For each symbol and each venue we align-as-of the LATEST funding rate <= the bar close (the point-in-time
    LEVEL — what we would actually have known at the bar). Then per bar:
      fund_spread_bybit = binance - bybit   (signed; positive = Binance pays more)
      fund_spread_okx   = binance - okx
      fund_disp         = max(present rates) - min(present rates)  (>= 0; the cross-venue DISPERSION)
    The cross-sectional ranks (fund_disp_rank, fund_spread_bybit_rank) are computed in a second pass across the
    universe AS OF each bar timestamp. A venue absent at a bar is simply not used for that bar's spread/disp
    (honest 'no data', never a 0-fill). Returns (alt, coverage) where coverage[symbol] = #bars with all 3 venues."""
    # 1. per-symbol per-venue PIT level series, keyed by bar.ts.isoformat()
    per_symbol_rates: dict[str, dict[str, dict[str, float]]] = {}
    coverage: dict[str, int] = {}
    for symbol, bars in market.items():
        bin_pts = binance.fetch_series(symbol, "funding_rate", limit=len(bars) * 3 + 1100)
        byb_pts = _read_xvenue_funding(_BYBIT_DIR, symbol)
        okx_pts = _read_xvenue_funding(_OKX_DIR, symbol)
        bin_lvl = align_asof(bin_pts, bars)
        byb_lvl = align_asof(byb_pts, bars)
        okx_lvl = align_asof(okx_pts, bars)
        per_symbol_rates[symbol] = {"binance": bin_lvl, "bybit": byb_lvl, "okx": okx_lvl}
        n_all = sum(1 for b in bars
                    if b.ts.isoformat() in bin_lvl and b.ts.isoformat() in byb_lvl and b.ts.isoformat() in okx_lvl)
        coverage[symbol] = n_all

    # 2. per-symbol spread / dispersion features
    alt: dict[str, dict[str, dict[str, float]]] = {}
    for symbol, bars in market.items():
        r = per_symbol_rates[symbol]
        sb: dict[str, float] = {}
        so: dict[str, float] = {}
        disp: dict[str, float] = {}
        for b in bars:
            k = b.ts.isoformat()
            bn = r["binance"].get(k)
            by = r["bybit"].get(k)
            ok = r["okx"].get(k)
            if bn is not None and by is not None:
                sb[k] = bn - by
            if bn is not None and ok is not None:
                so[k] = bn - ok
            present = [v for v in (bn, by, ok) if v is not None]
            if len(present) >= 2:
                disp[k] = max(present) - min(present)
        feats: dict[str, dict[str, float]] = {}
        if sb:
            feats[FEAT_SPREAD_BYBIT] = sb
        if so:
            feats[FEAT_SPREAD_OKX] = so
        if disp:
            feats[FEAT_DISP] = disp
        if feats:
            alt[symbol] = feats

    # 3. cross-sectional ranks (computed PIT across the universe at each bar ts)
    _add_xsec_rank(alt, FEAT_DISP, FEAT_DISP_RANK)
    _add_xsec_rank(alt, FEAT_SPREAD_BYBIT, FEAT_SPREAD_BYBIT_RANK)
    return alt, coverage


def _add_xsec_rank(alt: dict[str, dict[str, dict[str, float]]], src: str, dst: str) -> None:
    """Add a [0,1] cross-sectional percentile rank of `src` across all symbols AS OF each bar timestamp (PIT:
    a bar's rank uses only that bar's same-timestamp values, no future). 0 = lowest, 1 = highest. Written into
    each symbol's feature dict under `dst`. Symbols missing `src` at a ts are simply not ranked then."""
    # gather all timestamps that have a value, per symbol
    by_ts: dict[str, dict[str, float]] = {}
    for symbol, feats in alt.items():
        for k, v in feats.get(src, {}).items():
            by_ts.setdefault(k, {})[symbol] = v
    for symbol in alt:
        alt[symbol].setdefault(dst, {})
    for k, sym_vals in by_ts.items():
        if len(sym_vals) < 2:
            continue
        ordered = sorted(sym_vals, key=lambda s: sym_vals[s])
        m = len(ordered)
        for i, s in enumerate(ordered):
            alt[s][dst][k] = i / (m - 1)


def _shuffle_disp(alt: dict[str, dict[str, dict[str, float]]], seed: int) -> dict[str, dict[str, dict[str, float]]]:
    """SHUFFLE-PLACEBO: circularly rotate each symbol's dispersion / spread / rank series by a per-symbol offset
    (deterministic from seed). This DESTROYS the alignment between the dispersion signal and the forward return
    while PRESERVING the marginal distribution (same values, same autocorrelation structure within the rotated
    block) and the PIT keying (values still attach to real bar timestamps). If a 'dispersion edge' survives this,
    it is an artefact of the value distribution / the price path, NOT of cross-venue dispersion timing."""
    import random

    rng = random.Random(seed)
    out: dict[str, dict[str, dict[str, float]]] = {}
    shuf_feats = {FEAT_SPREAD_BYBIT, FEAT_SPREAD_OKX, FEAT_DISP, FEAT_DISP_RANK, FEAT_SPREAD_BYBIT_RANK}
    for symbol, feats in alt.items():
        out[symbol] = {}
        for fname, series in feats.items():
            if fname not in shuf_feats:
                out[symbol][fname] = dict(series)
                continue
            keys = sorted(series)  # chronological bar timestamps
            vals = [series[k] for k in keys]
            if len(vals) < 4:
                out[symbol][fname] = dict(series)
                continue
            off = rng.randint(1, len(vals) - 1)
            rotated = vals[off:] + vals[:off]  # circular rotation: same values, broken alignment
            out[symbol][fname] = {k: rotated[i] for i, k in enumerate(keys)}
    return out


def _clip_to_funding_overlap(
    market: dict[str, list[Bar]], binance: CachedFundingRateProvider, *, require_okx: bool
) -> dict[str, list[Bar]]:
    """Restrict bars to the window where the REQUIRED venues' funding overlaps. require_okx=False clips to the
    Binance & Bybit overlap (the deep ~730d axis); require_okx=True clips to all-three (the thin ~90d axis).
    Apples-to-apples: a bar with no required funding can never trade the dispersion signal."""
    clipped: dict[str, list[Bar]] = {}
    for symbol, bars in market.items():
        bin_pts = binance.fetch_series(symbol, "funding_rate", limit=len(bars) * 3 + 1100)
        byb_pts = _read_xvenue_funding(_BYBIT_DIR, symbol)
        okx_pts = _read_xvenue_funding(_OKX_DIR, symbol)
        if not bin_pts or not byb_pts or (require_okx and not okx_pts):
            continue
        lo = max(bin_pts[0].ts, byb_pts[0].ts, okx_pts[0].ts if require_okx else bin_pts[0].ts)
        hi = min(bin_pts[-1].ts, byb_pts[-1].ts, okx_pts[-1].ts if require_okx else bin_pts[-1].ts)
        clipped[symbol] = [b for b in bars if lo <= b.ts <= hi]
    return clipped


# --------------------------------------------------------------------------- spec family


@dataclass
class SpecReport:
    name: str
    net_return: float
    gross_return: float
    cost_ratio: float
    deflated_sharpe_prob: float
    cscv_pbo: float
    regimes_positive: int
    num_trades: int
    max_drawdown: float
    skew: float
    gate_passed: bool
    survived_fdr: bool = False
    promoted: bool = False
    price_only_net: float | None = None      # disconfirmer (a): same entries minus the dispersion feature
    placebo_net: float | None = None         # disconfirmer (b): shuffled dispersion series
    placebo_dsr: float | None = None
    adds_over_price: bool | None = None
    beats_placebo: bool | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class CohortReport:
    verdict: str
    headline: str
    data_source: str
    window: str
    axis: str
    regimes_covered: dict[str, int]
    coverage: dict[str, int]
    fdr_q: float
    specs: list[SpecReport] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _disp_specs() -> list[tuple[str, StrategySpec]]:
    """The cross-venue funding-dispersion FAMILY, all pre-registered. Each is a typed StrategySpec referencing
    the computed dispersion features. NO magic numbers — every threshold is a ParamRef fit by the Finder grid.

    Pre-registered directions:
      1. disp-meanrev-short:  HIGH cross-venue dispersion = a transient venue mispricing / crowding stress →
         fade the asset (short) expecting reversion as venues re-converge. (mean-reversion on dispersion)
      2. spread-carry-long:   Binance funding RICHER than Bybit (positive B-Bybit spread) = relatively crowded
         long on Binance perp; a SPOT long captures the convergence as Binance funding normalizes down.
         (signed spread as a relative-positioning read; long direction)
      3. xsec-disp-low-long:  cross-sectionally, LOW-dispersion names (venues agree → consensus, less stress)
         are the calm book → long the low-dispersion percentile. (xsec dispersion rank, long calm)
      4. xsec-spread-high-short: cross-sectionally, names where Binance funding is HIGHEST vs Bybit (top spread
         percentile) are the most crowded-on-Binance → short them. (xsec signed-spread rank, short crowded)
    """
    universe = {
        "venues": ["binance"], "asset_classes": ["crypto"],
        "min_liquidity_usd": 10000000, "min_instruments": 5,
    }
    risk = {"max_concurrent_positions": 5, "max_position_pct": 0.2, "conviction": 0.5}
    horizon = {"bar_size": "1d", "min_hold_days": 1, "max_hold_days": 10}
    common_exit_params = {
        "stop": {"kind": "float", "lo": 0.04, "hi": 0.15},
        "tp": {"kind": "float", "lo": 0.05, "hi": 0.25},
        "time_stop": {"kind": "int", "lo": 3, "hi": 10, "step": 1},
    }

    specs: list[dict] = [
        {
            "name": "x-venue dispersion mean-reversion (fade high dispersion, short)",
            "rationale": "High cross-venue funding dispersion = a transient mispricing/crowding-stress flare; "
                         "fade the asset expecting venues to re-converge.",
            "catalyst": "cross-exchange funding dispersion spike",
            "universe": universe, "horizon": horizon,
            "entry": [
                {"feature": {"name": FEAT_DISP}, "op": "gt", "threshold": {"param": "disp_floor"}},
            ],
            "exit": {
                "stop_loss": {"param": "stop"}, "take_profit": {"param": "tp"},
                "time_stop_days": {"param": "time_stop"},
                "signal_exits": [
                    {"feature": {"name": FEAT_DISP}, "op": "lt", "threshold": {"param": "disp_reset"}},
                ],
            },
            "risk": risk, "direction": -1,
            "param_space": {
                "disp_floor": {"kind": "float", "lo": 0.0001, "hi": 0.0015},
                "disp_reset": {"kind": "float", "lo": 0.00002, "hi": 0.0005},
                **common_exit_params,
            },
        },
        {
            "name": "x-venue spread carry-convergence (Binance richer than Bybit, long spot)",
            "rationale": "Binance funding richer than Bybit = relatively crowded-long on Binance perp; a spot "
                         "long captures convergence as Binance funding normalizes down.",
            "catalyst": "Binance-Bybit funding spread positive",
            "universe": universe, "horizon": horizon,
            "entry": [
                {"feature": {"name": FEAT_SPREAD_BYBIT}, "op": "gt", "threshold": {"param": "spread_floor"}},
            ],
            "exit": {
                "stop_loss": {"param": "stop"}, "take_profit": {"param": "tp"},
                "time_stop_days": {"param": "time_stop"},
                "signal_exits": [
                    {"feature": {"name": FEAT_SPREAD_BYBIT}, "op": "lt", "threshold": {"param": "spread_reset"}},
                ],
            },
            "risk": risk, "direction": 1,
            "param_space": {
                "spread_floor": {"kind": "float", "lo": 0.00005, "hi": 0.0008},
                "spread_reset": {"kind": "float", "lo": -0.0002, "hi": 0.0001},
                **common_exit_params,
            },
        },
        {
            "name": "x-venue xsec low-dispersion (long the calm/consensus names)",
            "rationale": "Low cross-venue dispersion = venues agree, less stress, the calm book; long the "
                         "lowest-dispersion percentile of the universe.",
            "catalyst": "cross-sectional low funding dispersion",
            "universe": universe, "horizon": horizon,
            "entry": [
                {"feature": {"name": FEAT_DISP_RANK}, "op": "lt", "threshold": {"param": "rank_ceiling"}},
            ],
            "exit": {
                "stop_loss": {"param": "stop"}, "take_profit": {"param": "tp"},
                "time_stop_days": {"param": "time_stop"},
                "signal_exits": [
                    {"feature": {"name": FEAT_DISP_RANK}, "op": "gt", "threshold": {"param": "rank_exit"}},
                ],
            },
            "risk": risk, "direction": 1,
            "param_space": {
                "rank_ceiling": {"kind": "float", "lo": 0.1, "hi": 0.4},
                "rank_exit": {"kind": "float", "lo": 0.5, "hi": 0.9},
                **common_exit_params,
            },
        },
        {
            "name": "x-venue xsec high Binance-spread (short the crowded-on-Binance names)",
            "rationale": "Names where Binance funding is highest vs Bybit (top spread percentile) are the most "
                         "crowded-on-Binance; short them expecting relative convergence.",
            "catalyst": "cross-sectional high Binance-Bybit spread",
            "universe": universe, "horizon": horizon,
            "entry": [
                {"feature": {"name": FEAT_SPREAD_BYBIT_RANK}, "op": "gt", "threshold": {"param": "rank_floor"}},
            ],
            "exit": {
                "stop_loss": {"param": "stop"}, "take_profit": {"param": "tp"},
                "time_stop_days": {"param": "time_stop"},
                "signal_exits": [
                    {"feature": {"name": FEAT_SPREAD_BYBIT_RANK}, "op": "lt", "threshold": {"param": "rank_exit"}},
                ],
            },
            "risk": risk, "direction": -1,
            "param_space": {
                "rank_floor": {"kind": "float", "lo": 0.6, "hi": 0.9},
                "rank_exit": {"kind": "float", "lo": 0.1, "hi": 0.5},
                **common_exit_params,
            },
        },
    ]
    return [(s["name"], StrategySpec.model_validate(s)) for s in specs]


# --------------------------------------------------------------------------- the harness


def _disp_feature_of(spec: StrategySpec) -> str:
    """The dispersion/spread feature this spec keys on (for the price-only ablation)."""
    for c in spec.entry:
        if c.feature.name in (FEAT_SPREAD_BYBIT, FEAT_SPREAD_OKX, FEAT_DISP, FEAT_DISP_RANK, FEAT_SPREAD_BYBIT_RANK):
            return c.feature.name
    return ""


def _resolve_params(spec: StrategySpec) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, ps in spec.param_space.items():
        if ps.kind == "choice" and ps.choices:
            out[k] = float(ps.choices[0])
        elif ps.lo is not None and ps.hi is not None:
            mid = (float(ps.lo) + float(ps.hi)) / 2.0
            out[k] = float(round(mid)) if ps.kind == "int" else mid
        else:
            out[k] = 0.0
    return out


def _spec_best(spec, market, *, fee_bps, alt, store, gates, label):  # noqa: ANN001
    """Finder-faithful: build the spec's coarse param GRID, screen EVERY variant on REAL bars/funding/fees,
    RECORD each as a trial (so deflation/FDR see the true count), return the gate-best variant's params + result
    + the per-variant validation-return streams (for a real CSCV-PBO)."""
    from cosmu.lab.finder import build_grid

    grid = build_grid(spec, max_variants=64)
    best_params = _resolve_params(spec)
    best_result = None
    best_key = (-1, -1.0)
    most_trades = -1
    most_trading = None
    streams: list[list[float]] = []
    for variant in grid:
        res = run_strategy_backtest_detailed(spec, variant.params, market, fee_bps=fee_bps, alt_by_symbol=alt)
        m = res.metrics
        record_trial(store, float(m.sharpe_per_obs), source="xvenue_funding", label=f"{label}:{variant.config_tag}")
        v = score(m, gates, trials=trial_stats(store))
        if res.val_returns:
            streams.append(res.val_returns)
        key = (1 if v.passed else 0, float(v.deflated_sharpe_prob))
        if key > best_key or best_result is None or (key == best_key and m.num_trades > best_result.metrics.num_trades):
            best_key, best_params, best_result = key, variant.params, res
        if m.num_trades > most_trades:
            most_trades, most_trading = m.num_trades, (variant.params, res)
    if best_result is not None and best_result.metrics.num_trades == 0 and most_trades > 0 and most_trading:
        best_params, best_result = most_trading
    if best_result is None:
        best_result = run_strategy_backtest_detailed(spec, best_params, market, fee_bps=fee_bps, alt_by_symbol=alt)
    return best_params, best_result, streams


def run_cohort(
    specs: list[tuple[str, StrategySpec]],
    market: dict[str, list[Bar]],
    binance: CachedFundingRateProvider,
    store: Store,
    *,
    axis: str,
    require_okx: bool,
    data_source: str = "live-cached",
    fdr_q: float = 0.10,
    min_trades_floor: int = 30,
) -> CohortReport:
    gates = store.settings.gates
    fee_bps = PERP_TAKER_BPS

    regimes_covered: dict[str, int] = {}
    win_lo = win_hi = None
    for symbol, bars in market.items():
        for r in _regime_labels([float(b.close) for b in bars]):
            regimes_covered[r] = regimes_covered.get(r, 0) + 1
        if bars:
            win_lo = min(win_lo, bars[0].ts) if win_lo else bars[0].ts
            win_hi = max(win_hi, bars[-1].ts) if win_hi else bars[-1].ts
    window = f"{win_lo.date()}..{win_hi.date()}" if win_lo and win_hi else "n/a"

    alt, coverage = _xvenue_funding_alt(market, binance)
    notes: list[str] = []
    has_disp = any(FEAT_DISP in feats or FEAT_SPREAD_BYBIT in feats for feats in alt.values())
    if not alt or not has_disp:
        return CohortReport("INSUFFICIENT-DATA", "no cross-venue funding overlap in cache", data_source, window,
                            axis, regimes_covered, coverage, fdr_q,
                            notes=["cross-venue funding caches do not overlap the bars — nothing to gate"])

    # The HONEST window/coverage = the span where the dispersion feature actually exists (the gateable window),
    # NOT the raw bar span. On the deep axis this is the Binance-Bybit spread span; `coverage` is the count of
    # bars per symbol where the spread is computable (the real per-symbol sample size feeding the gate).
    spread_keys = sorted({k for feats in alt.values() for k in feats.get(FEAT_SPREAD_BYBIT, {})})
    if spread_keys:
        window = f"{spread_keys[0][:10]}..{spread_keys[-1][:10]}"
    coverage = {s: len(alt[s].get(FEAT_SPREAD_BYBIT, {})) for s in alt}

    placebo_alt = _shuffle_disp(alt, seed=1234)

    candidates: list[Candidate] = []
    reports: list[SpecReport] = []
    max_trades = 0
    for name, spec in specs:
        disp_feat = _disp_feature_of(spec)
        # OKX-keyed spec on the deep (Bybit) axis would be empty — skip honestly
        if disp_feat == FEAT_SPREAD_OKX and not require_okx:
            continue
        params, res, streams = _spec_best(spec, market, fee_bps=fee_bps, alt=alt, store=store, gates=gates, label=name)
        m = res.metrics
        max_trades = max(max_trades, m.num_trades)
        gross = run_strategy_backtest_detailed(spec, params, market, fee_bps=Decimal("0"), slippage_bps=Decimal("0"),
                                               impact_bps=Decimal("0"), alt_by_symbol=alt).metrics
        net_return = float(m.oos_return)
        gross_return = float(gross.oos_return)
        cost_ratio = float(m.cost_ratio)
        if cost_ratio == 0.0 and gross_return:
            cost_ratio = net_return / gross_return
        usable = [s for s in streams if s]
        pbo = cscv_pbo(usable) if len(usable) >= 2 else float(m.pbo)

        # --- disconfirmer (a): PRICE-ONLY control (drop the dispersion feature from entry + signal-exits) ---
        po_spec = spec.model_copy(update={
            "entry": [c for c in spec.entry if c.feature.name != disp_feat],
            "exit": spec.exit.model_copy(update={
                "signal_exits": [c for c in spec.exit.signal_exits if c.feature.name != disp_feat]
            }),
        })
        # if dropping the feature leaves NO entry condition, the price-only book is "always-in" at the same params
        po = run_strategy_backtest_detailed(po_spec, params, market, fee_bps=fee_bps, alt_by_symbol=alt)
        price_only_net = float(po.metrics.oos_return)
        adds_over_price = net_return > price_only_net

        # --- disconfirmer (b): SHUFFLE placebo (same spec/params, shuffled dispersion series) ---
        pl = run_strategy_backtest_detailed(spec, params, market, fee_bps=fee_bps, alt_by_symbol=placebo_alt)
        placebo_net = float(pl.metrics.oos_return)
        placebo_dsr = float(score(pl.metrics, gates, trials=trial_stats(store)).deflated_sharpe_prob)
        real_dsr = float(score(m, gates, trials=trial_stats(store)).deflated_sharpe_prob)
        beats_placebo = real_dsr > placebo_dsr and net_return > placebo_net

        var = statistics.pvariance(res.val_returns) if len(res.val_returns) > 1 else 1.0
        candidates.append(Candidate(id=name, metrics=m, net_profit=net_return, source="xvenue_funding",
                                    label=name, return_variance=var or 1.0))
        reports.append(SpecReport(
            name=name, net_return=round(net_return, 6), gross_return=round(gross_return, 6),
            cost_ratio=round(cost_ratio, 4), deflated_sharpe_prob=round(real_dsr, 6), cscv_pbo=round(pbo, 6),
            regimes_positive=sum(1 for v in m.regime_returns.values() if v > 0), num_trades=m.num_trades,
            max_drawdown=round(float(m.max_drawdown), 6), skew=round(float(m.skew), 4), gate_passed=False,
            price_only_net=round(price_only_net, 6), placebo_net=round(placebo_net, 6),
            placebo_dsr=round(placebo_dsr, 6), adds_over_price=adds_over_price, beats_placebo=beats_placebo,
        ))

    if not candidates:
        return CohortReport("INSUFFICIENT-DATA", "no spec produced a candidate on this axis", data_source, window,
                            axis, regimes_covered, coverage, fdr_q, notes=["no gateable spec on this axis"])

    # honest depth gate: if the deepest spec trades < min_trades_floor, the axis is too thin to gate honestly.
    if max_trades < min_trades_floor:
        return CohortReport(
            "INSUFFICIENT-DATA",
            f"deepest dispersion spec traded {max_trades} times (< {min_trades_floor}) — axis too thin to gate",
            data_source, window, axis, regimes_covered, coverage, fdr_q, specs=reports,
            notes=notes + [f"the {axis} cross-venue funding overlap yields too few entries for a significant sample"],
        )

    # COHORT BH-FDR across the family — the ledger already holds every grid variant, so register=False + the
    # shared trial_stats so deflation/FDR see the true (grid-inflated) count, not just the family representatives.
    promotions = promote_cohort(store, candidates, gates, fdr_q=fdr_q, register=False, trials=trial_stats(store))
    by_id = {p.candidate_id: p for p in promotions}
    for r in reports:
        p = by_id.get(r.name)
        if p:
            r.survived_fdr = p.survived_fdr
            r.promoted = p.promoted
            r.gate_passed = p.promoted
            r.reasons = p.reasons

    # A promotion only COUNTS as a real edge if it ALSO survives BOTH disconfirmers (adds over price + beats placebo).
    real_survivors = [r for r in reports if r.promoted and r.adds_over_price and r.beats_placebo]
    promoted_but_fragile = [r for r in reports if r.promoted and not (r.adds_over_price and r.beats_placebo)]
    if real_survivors:
        verdict = "PASS"
        headline = (f"{len(real_survivors)} spec(s) survived gate + BH-FDR (q={fdr_q}) AND both disconfirmers: "
                    + ", ".join(r.name for r in real_survivors))
    else:
        verdict = "FAIL"
        best = max(reports, key=lambda r: r.deflated_sharpe_prob) if reports else None
        if promoted_but_fragile:
            headline = (f"spec(s) passed gate+FDR but FAILED a disconfirmer (price-only or placebo) — not a real "
                        f"x-venue edge: " + ", ".join(r.name for r in promoted_but_fragile))
        else:
            headline = (f"no spec survived gate + BH-FDR (q={fdr_q}); best DSR {best.deflated_sharpe_prob} "
                        f"({best.name})" if best else "no candidates")
    return CohortReport(verdict, headline, data_source, window, axis, regimes_covered, coverage, fdr_q,
                        specs=reports, notes=notes)


def _main() -> int:
    import tempfile

    from cosmu.config.settings import Settings

    binance = CachedFundingRateProvider()
    specs = _disp_specs()
    raw_market = {s: _read_bars_offline(s) for s in TRIVENUE_SYMBOLS}
    raw_market = {s: b for s, b in raw_market.items() if b}

    for axis, require_okx in (("binance-bybit (deep ~730d)", False), ("tri-venue+okx (thin ~90d)", True)):
        tmp = tempfile.mkdtemp(prefix="cosmu-xvenue-")
        store = Store(Settings(database_url=f"sqlite:///{tmp}/xvenue.sqlite3", openrouter_api_key=None))
        market = _clip_to_funding_overlap(raw_market, binance, require_okx=require_okx)
        report = run_cohort(specs, market, binance, store, axis=axis, require_okx=require_okx)
        print(f"\n=== X-VENUE FUNDING-DISPERSION COHORT — {report.verdict}  [{axis}] ===")
        print(f"  data_source={report.data_source}  window={report.window}  regimes={report.regimes_covered}")
        cov = [v for v in report.coverage.values() if v]
        print(f"  symbols traded: {len(market)}  spread bars/symbol (the real per-symbol sample): "
              f"min={min(cov) if cov else 0} max={max(cov) if cov else 0}  total={sum(cov)}")
        print(f"  cohort BH-FDR q={report.fdr_q}  perp_taker={PERP_TAKER_BPS}bps")
        for a in report.specs:
            flag = "PROMOTED" if a.promoted else ("fdr-only" if a.survived_fdr else "stop")
            print(f"  [{flag:>8}] {a.name[:52]:<52} net={a.net_return:+.4f} gross={a.gross_return:+.4f} "
                  f"cr={a.cost_ratio:.2f} dsr={a.deflated_sharpe_prob:.3f} pbo={a.cscv_pbo:.3f} "
                  f"reg+={a.regimes_positive} trades={a.num_trades} skew={a.skew:+.2f} fdr={'Y' if a.survived_fdr else 'N'}")
            print(f"             disconfirmers: price_only_net={a.price_only_net} (adds={a.adds_over_price}) "
                  f"placebo_net={a.placebo_net} placebo_dsr={a.placebo_dsr} (beats={a.beats_placebo})")
            if a.reasons:
                print(f"             reasons: {', '.join(a.reasons)}")
        for n in report.notes:
            print(f"  note: {n}")
        print(f"  HEADLINE: {report.headline}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
