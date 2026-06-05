# intent: run the existing gate infrastructure against a matrix of REAL perpetual-futures cost scenarios
# (venue × funding-regime) and report skew/tail/cost_ratio per cell — the Phase 0 P0.6 cost-surface pass for
# the funding-dispersion strategy. Inputs: cached real Binance USDT-M daily bars + funding history (the same
# offline cache the carry-ablation harness uses) + the two authored dispersion specs. Outputs: a PerpSweepReport
# containing per-scenario BacktestMetrics with skew/kurtosis/cost_ratio highlighted. Invariants: ZERO LLM calls;
# the gate's statistical thresholds are NOT changed; the Gate/scorer is called read-only; fees and funding rates
# are PIT; deterministic for a fixed cache; honest about data depth (empty cache = INSUFFICIENT-DATA, not a fake).
#
# Modal entrypoint: modal run apps/engine/remote/app.py --job run_module --module cosmu.research.perp_gate_sweep
# Local quick-run:  python -m cosmu.research.perp_gate_sweep

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from cosmu.data.altdata import AltDataProvider, CachedFundingRateProvider
from cosmu.data.backtest import align_asof, run_strategy_backtest
from cosmu.data.market import Bar, BinanceSpotOHLCVProvider
from cosmu.data.universe import PERP_UNIVERSE
from cosmu.knowledge.store import Store
from cosmu.master.scorer import BacktestMetrics, sample_moments
from cosmu.master.trials import trial_stats
from cosmu.research.carry_ablation import (
    _best_variant,
    _metrics_from_returns,
    _merge_alt,
    _xsec_rank_alt,
)
from cosmu.spine.venue import default_catalog
from cosmu.strategy.spec import StrategySpec

# Pre-registered cost scenarios — FIXED before looking. Changing them after a run is itself a new trial.
# Rows represent the real per-side taker fee + a descriptive funding regime.
SWEEP_SCENARIOS: list[dict] = [
    # ---- baseline: the venue the existing Gate priced at (Binance spot, 10 bps taker, no funding)
    {"venue": "binance",         "fee_bps": 10.0, "funding_bps_per_bar": 0.0,  "label": "binance_spot_no_fund"},
    # ---- OKX perp (MiCA EU, FR-legal): 10 bps taker base — same fee as Binance, different venue
    {"venue": "okx",             "fee_bps": 10.0, "funding_bps_per_bar": 0.0,  "label": "okx_perp_no_fund"},
    # ---- OKX perp + typical positive funding (+0.01%/8h = 3 bps/day, annualised ≈ +11%)
    {"venue": "okx",             "fee_bps": 10.0, "funding_bps_per_bar": 3.0,  "label": "okx_perp_typ_fund"},
    # ---- OKX perp + high positive funding (+0.03%/8h = 9 bps/day, annualised ≈ +33%)
    {"venue": "okx",             "fee_bps": 10.0, "funding_bps_per_bar": 9.0,  "label": "okx_perp_high_fund"},
    # ---- Kraken Futures (MiCA EU, FR-legal): 5 bps taker — cheapest perp venue we have
    {"venue": "kraken_futures",  "fee_bps":  5.0, "funding_bps_per_bar": 0.0,  "label": "kf_perp_no_fund"},
    # ---- Kraken Futures + typical positive funding
    {"venue": "kraken_futures",  "fee_bps":  5.0, "funding_bps_per_bar": 3.0,  "label": "kf_perp_typ_fund"},
    # ---- friction-free gross (the theoretical edge before any cost; shared denominator for cost_ratio)
    {"venue": "binance",         "fee_bps":  0.0, "funding_bps_per_bar": 0.0,  "label": "gross_frictionless"},
]

# Interpretation guide for the sweep output.
COST_RATIO_FLOOR = 0.40   # net/gross >= 40% = the edge is not a thin sliver
SKEW_FLOOR       = -2.0   # return-series skew below this = the carry negative-skew failure mode
CORR_BTC_BAND    = 0.30   # |corr-to-BTC| <= this = plausibly market-neutral


@dataclass(frozen=True)
class ScenarioResult:
    label: str
    venue: str
    fee_bps: float
    funding_bps_per_bar: float
    # ---- long leg ----
    long_net: float
    long_sharpe: float
    long_skew: float
    long_kurt: float
    long_max_dd: float
    long_cost_ratio: float
    long_trades: int
    # ---- short leg ----
    short_net: float
    short_sharpe: float
    short_skew: float
    short_kurt: float
    short_max_dd: float
    short_cost_ratio: float
    short_trades: int
    # ---- combined neutral pair (50/50 legs) ----
    pair_net: float
    pair_sharpe: float
    pair_skew: float
    pair_kurt: float
    pair_max_dd: float
    pair_cost_ratio: float
    pair_trades: int
    # ---- interpretation flags ----
    fragile: bool    # cost_ratio < COST_RATIO_FLOOR (pair)
    bad_tail: bool   # pair skew < SKEW_FLOOR
    holds: bool      # pair_net > 0


@dataclass
class PerpSweepReport:
    verdict: str                   # "PASS" | "FAIL" | "INSUFFICIENT-DATA"
    data_source: str               # "live-cached" | "synthetic"
    window: str                    # overlapping bar window actually traded
    funding_points: dict[str, int] # per-symbol funding cache depth
    gross_pair_return: float       # friction-free pair return (the shared denominator)
    gross_long_skew: float         # long-leg skew in the frictionless run (the carry left-tail check)
    scenarios: list[ScenarioResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Feature helpers
# ---------------------------------------------------------------------------


def _xsec_funding_rank_alt(
    market: dict[str, list[Bar]],
    funding: AltDataProvider,
    feature: str = "xsec_funding_rank",
) -> dict[str, dict[str, dict[str, float]]]:
    """Cross-sectional percentile rank of the funding rate across the universe at each bar close.

    At each bar, rank all symbols whose funding history is non-empty by their latest PIT funding rate.
    Percentile 0 = lowest funding (cheapest-to-hold-long), 1 = highest (most crowded).
    Symbol missing from funding data is not ranked at that bar (no survivorship look-ahead).
    """
    # collect PIT funding per symbol per bar-ts key
    fund_pts: dict[str, list] = {}
    for symbol, bars in market.items():
        pts = funding.fetch_series(symbol, "funding_rate", limit=len(bars) + 1100)
        fund_pts[symbol] = pts  # ascending list[AltDataPoint]

    # Pre-sort pts per symbol once (ascending) for an efficient PIT scan
    sorted_pts = {s: sorted(pts, key=lambda p: p.ts) for s, pts in fund_pts.items()}

    # build ts-ordered rank at each bar
    all_ts = sorted({b.ts.isoformat() for bars in market.values() for b in bars})
    out: dict[str, dict[str, dict[str, float]]] = {s: {feature: {}} for s in market}

    for ts_key in all_ts:
        # per-symbol: latest funding point available at this bar (PIT, ascending scan)
        levels: dict[str, float] = {}
        for symbol, pts in sorted_pts.items():
            val = None
            for pt in pts:
                if pt.ts.isoformat() <= ts_key:
                    val = pt.value
                else:
                    break
            if val is not None:
                levels[symbol] = val

        if len(levels) < 2:
            continue
        ordered = sorted(levels, key=lambda s: levels[s])
        m = len(ordered)
        for r_idx, s in enumerate(ordered):
            out[s][feature][ts_key] = r_idx / (m - 1)  # percentile [0, 1]

    return out


def _apply_funding_cost(
    metrics: BacktestMetrics,
    funding_bps_per_bar: float,
    direction: int,
) -> BacktestMetrics:
    """Subtract (long) or add (short) a daily funding cost from the net return.

    For a LONG perp (direction=+1): positive funding is a COST (longs pay); we subtract.
    For a SHORT perp (direction=-1): positive funding is INCOME (shorts receive); we add.
    The adjustment scales with the average hold length: cost = funding × num_trades × avg_hold.
    This is a conservative MODEL ESTIMATE layered on the backtest output, not a per-bar tweak.
    """
    if funding_bps_per_bar == 0.0 or metrics.num_trades == 0:
        return metrics
    funding_frac_per_bar = funding_bps_per_bar / 10000.0
    # Approximate cost: if the strategy holds for ~(oos_return/num_trades) bps per trade on average,
    # we scale by num_trades × avg_hold_days. We don't know hold length from BacktestMetrics directly,
    # so use a conservative 5-bar average (the mid of the dispersion spec's 2–7 day range).
    AVG_HOLD_BARS = 5
    total_funding_drag = funding_frac_per_bar * AVG_HOLD_BARS * metrics.num_trades
    sign = -1 if direction > 0 else +1  # long pays, short receives
    adj = sign * total_funding_drag

    new_return = float(metrics.oos_return) + adj
    return metrics.model_copy(update={"oos_return": Decimal(str(round(new_return, 8)))})


# ---------------------------------------------------------------------------
# Per-scenario runner
# ---------------------------------------------------------------------------


def _run_scenario(
    long_spec: StrategySpec,
    short_spec: StrategySpec,
    market: dict[str, list[Bar]],
    alt: dict,
    *,
    fee_bps: float,
    funding_bps_per_bar: float,
    label: str,
    venue: str,
    store: Store,
) -> ScenarioResult:
    gates = store.settings.gates
    fee = Decimal(str(fee_bps))

    lp, long_m = _best_variant(long_spec,  market, fee_bps=fee, alt=alt, store=store, gates=gates, label=f"{label}:long")
    sp, short_m = _best_variant(short_spec, market, fee_bps=fee, alt=alt, store=store, gates=gates, label=f"{label}:short")

    # Apply funding drag on top of the backtest result (model overlay, not per-bar; conservative)
    long_m  = _apply_funding_cost(long_m,  funding_bps_per_bar, direction=+1)
    short_m = _apply_funding_cost(short_m, funding_bps_per_bar, direction=-1)

    # Gross (friction-free, same signals, zero cost): for cost_ratio denominator
    long_g  = run_strategy_backtest(long_spec,  lp, market, fee_bps=Decimal("0"), slippage_bps=Decimal("0"), impact_bps=Decimal("0"), alt_by_symbol=alt)
    short_g = run_strategy_backtest(short_spec, sp, market, fee_bps=Decimal("0"), slippage_bps=Decimal("0"), impact_bps=Decimal("0"), alt_by_symbol=alt)

    def _cr(net: BacktestMetrics, gross: BacktestMetrics) -> float:
        g = float(gross.oos_return)
        n = float(net.oos_return)
        return round(max(0.0, n / g) if g > 0.0 else 0.0, 4)

    # Pair = 50/50 legs
    pair_net = (float(long_m.oos_return) + float(short_m.oos_return)) / 2.0
    pair_gross = (float(long_g.oos_return) + float(short_g.oos_return)) / 2.0
    pair_cr = round(max(0.0, pair_net / pair_gross) if pair_gross > 0.0 else 0.0, 4)
    pair_trades = long_m.num_trades + short_m.num_trades
    pair_max_dd = max(float(long_m.max_drawdown), float(short_m.max_drawdown))
    pair_sharpe = (float(long_m.sharpe) + float(short_m.sharpe)) / 2.0
    pair_skew = (float(long_m.skew) + float(short_m.skew)) / 2.0
    pair_kurt = (float(long_m.kurtosis) + float(short_m.kurtosis)) / 2.0

    return ScenarioResult(
        label=label, venue=venue, fee_bps=fee_bps, funding_bps_per_bar=funding_bps_per_bar,
        long_net=round(float(long_m.oos_return), 6),
        long_sharpe=round(float(long_m.sharpe), 4),
        long_skew=round(float(long_m.skew), 4),
        long_kurt=round(float(long_m.kurtosis), 4),
        long_max_dd=round(float(long_m.max_drawdown), 6),
        long_cost_ratio=_cr(long_m, long_g),
        long_trades=long_m.num_trades,
        short_net=round(float(short_m.oos_return), 6),
        short_sharpe=round(float(short_m.sharpe), 4),
        short_skew=round(float(short_m.skew), 4),
        short_kurt=round(float(short_m.kurtosis), 4),
        short_max_dd=round(float(short_m.max_drawdown), 6),
        short_cost_ratio=_cr(short_m, short_g),
        short_trades=short_m.num_trades,
        pair_net=round(pair_net, 6),
        pair_sharpe=round(pair_sharpe, 4),
        pair_skew=round(pair_skew, 4),
        pair_kurt=round(pair_kurt, 4),
        pair_max_dd=round(pair_max_dd, 6),
        pair_cost_ratio=pair_cr,
        pair_trades=pair_trades,
        fragile=pair_cr < COST_RATIO_FLOOR,
        bad_tail=pair_skew < SKEW_FLOOR,
        holds=pair_net > 0.0,
    )


# ---------------------------------------------------------------------------
# Main harness
# ---------------------------------------------------------------------------


def _load_dispersion_specs() -> tuple[StrategySpec, StrategySpec]:
    inbox = Path(__file__).resolve().parents[2] / "strategies" / "inbox"
    def _load(name: str) -> StrategySpec:
        return StrategySpec.model_validate(json.loads((inbox / name).read_text()))
    return (
        _load("xsec-funding-dispersion-long-leg.json"),
        _load("xsec-funding-dispersion-short-leg.json"),
    )


def run_perp_gate_sweep(
    market: dict[str, list[Bar]],
    funding: AltDataProvider,
    store: Store,
    *,
    data_source: str = "live-cached",
    scenarios: list[dict] | None = None,
) -> PerpSweepReport:
    """Run the funding-dispersion specs through the cost-scenario grid and return a PerpSweepReport.

    `market` = Binance USDT-M perp bars keyed by symbol (e.g. "BTCUSDT").
    `funding` = an offline-capable funding provider (CachedFundingRateProvider by default).

    NO gate-threshold changes — the scorer's PREREGISTERED_BAR is read-only. This module
    only sweeps COST assumptions and reports how the edge changes.
    """
    _scenarios = scenarios if scenarios is not None else SWEEP_SCENARIOS
    long_spec, short_spec = _load_dispersion_specs()

    # --- data depth honesty ---
    funding_points = {s: len(funding.fetch_series(s, "funding_rate", limit=2000)) for s in market}
    win_lo = win_hi = None
    for symbol, bars in market.items():
        if bars:
            win_lo = min(win_lo, bars[0].ts) if win_lo else bars[0].ts
            win_hi = max(win_hi, bars[-1].ts) if win_hi else bars[-1].ts
    window = f"{win_lo.date()}..{win_hi.date()}" if win_lo and win_hi else "n/a"

    if not any(funding_points.values()):
        return PerpSweepReport(
            verdict="INSUFFICIENT-DATA", data_source=data_source, window=window,
            funding_points=funding_points, gross_pair_return=0.0, gross_long_skew=0.0,
            notes=["funding cache empty — run fetch_and_cache_funding() (needs network) then re-run"],
        )

    # Build all alt features once (shared across scenarios — pure, no cost assumptions here)
    funding_alt = {}
    for symbol, bars in market.items():
        pts = funding.fetch_series(symbol, "funding_rate", limit=len(bars) + 1100)
        joined = align_asof(pts, bars)
        if joined:
            funding_alt[symbol] = {"funding_rate": joined}

    # xsec_funding_rank: cross-sectional percentile rank of funding rates across the universe
    rank_alt = _xsec_funding_rank_alt(market, funding)

    # xsec_momentum_rank: required by the vol_ceiling filter in the spec (the spec references it)
    lb_default = 3  # mid of rank_lookback param_space [1, 5]
    mom_rank_alt = _xsec_rank_alt(market, lb_default)

    alt = _merge_alt(funding_alt, rank_alt, mom_rank_alt)

    results: list[ScenarioResult] = []
    gross_pair_return = 0.0
    gross_long_skew = 0.0
    notes: list[str] = []

    for sc in _scenarios:
        result = _run_scenario(
            long_spec, short_spec, market, alt,
            fee_bps=sc["fee_bps"],
            funding_bps_per_bar=sc["funding_bps_per_bar"],
            label=sc["label"],
            venue=sc["venue"],
            store=store,
        )
        results.append(result)
        if sc["label"] == "gross_frictionless":
            gross_pair_return = result.pair_net
            gross_long_skew = result.long_skew

    # Verdict: the cheapest realistic scenario (KF 5 bps + no funding) must hold AND not be fragile
    kf_no_fund = next((r for r in results if r.label == "kf_perp_no_fund"), None)
    kf_typ_fund = next((r for r in results if r.label == "kf_perp_typ_fund"), None)
    verdict = _verdict(kf_no_fund, kf_typ_fund, results, gross_pair_return, notes)

    return PerpSweepReport(
        verdict=verdict, data_source=data_source, window=window,
        funding_points=funding_points, gross_pair_return=round(gross_pair_return, 6),
        gross_long_skew=round(gross_long_skew, 4),
        scenarios=results, notes=notes,
    )


def _verdict(
    best: "ScenarioResult | None",
    typical: "ScenarioResult | None",
    all_results: list[ScenarioResult],
    gross: float,
    notes: list[str],
) -> str:
    if best is None or gross <= 0.0:
        notes.append("no gross edge: dispersion thesis not confirmed on this data window")
        return "FAIL"
    fails: list[str] = []
    if not best.holds:
        fails.append(f"kf_no_fund pair_net={best.pair_net} <= 0")
    if best.fragile:
        fails.append(f"kf_no_fund cost_ratio={best.pair_cost_ratio} < {COST_RATIO_FLOOR} (fragile)")
    if best.bad_tail:
        fails.append(f"kf_no_fund pair_skew={best.pair_skew} < {SKEW_FLOOR} (bad left tail)")
    if typical and not typical.holds:
        fails.append(f"kf_typ_fund pair_net={typical.pair_net} <= 0 (doesn't survive typical funding cost)")
    if fails:
        notes.extend(fails)
        return "FAIL"
    return "PASS"


# ---------------------------------------------------------------------------
# Print helper
# ---------------------------------------------------------------------------


def print_report(report: PerpSweepReport) -> None:
    print("\n" + "=" * 80)
    print("PERP GATE SWEEP — funding-dispersion strategy cost surface")
    print("=" * 80)
    print(f"verdict       : {report.verdict}")
    print(f"data_source   : {report.data_source}")
    print(f"window        : {report.window}")
    print(f"gross pair ret: {report.gross_pair_return:+.4f}  (frictionless; long-leg skew={report.gross_long_skew:+.2f})")
    print(f"funding pts   : {', '.join(f'{s}:{n}' for s, n in sorted(report.funding_points.items()))}")
    if report.notes:
        for n in report.notes:
            print(f"  NOTE: {n}")
    print()
    hdr = f"{'label':<28} {'fee':>5} {'fund':>6} {'pair_ret':>8} {'sharpe':>7} {'skew':>6} {'kurt':>6} {'maxDD':>6} {'cr':>6} {'hold?':>5} {'flag'}"
    print(hdr)
    print("-" * len(hdr))
    for r in report.scenarios:
        flag = ""
        if r.fragile:
            flag += "FRAGILE "
        if r.bad_tail:
            flag += "BAD-TAIL "
        hold_str = "YES" if r.holds else "NO"
        print(
            f"{r.label:<28} {r.fee_bps:>5.1f} {r.funding_bps_per_bar:>6.1f}"
            f" {r.pair_net:>+8.4f} {r.pair_sharpe:>7.3f} {r.pair_skew:>+6.2f}"
            f" {r.pair_kurt:>6.2f} {r.pair_max_dd:>6.4f} {r.pair_cost_ratio:>6.3f}"
            f" {hold_str:>5}  {flag}"
        )
    print("=" * 80)
    print(
        "\nINTERPRETATION:"
        "\n  cost_ratio < 0.40  → fragile edge (fees eat >60% of gross)."
        "\n  skew < -2.0        → carry left tail (funding-flip + liquidation cascade risk)."
        f"\n  best cheap scenario (kf_no_fund): holds={next((r.holds for r in report.scenarios if r.label == 'kf_perp_no_fund'), '?')}"
        f"  fragile={next((r.fragile for r in report.scenarios if r.label == 'kf_perp_no_fund'), '?')}"
        f"  bad_tail={next((r.bad_tail for r in report.scenarios if r.label == 'kf_perp_no_fund'), '?')}"
    )


# ---------------------------------------------------------------------------
# CLI / Modal entrypoint
# ---------------------------------------------------------------------------


def _main() -> int:
    import tempfile

    from cosmu.config.settings import Settings
    from cosmu.data.universe import PERP_UNIVERSE

    # Use the offline cache (deterministic; no network). For a live run cache funding first via
    # cosmu.research.carry_ablation.fetch_and_cache_funding().
    funding = CachedFundingRateProvider()
    market_provider = BinanceSpotOHLCVProvider()
    symbols = list(PERP_UNIVERSE[:20])  # the wide 20-asset universe matching the dispersion spec
    market: dict[str, list[Bar]] = {}
    for sym in symbols:
        bars = market_provider.fetch_bars(sym, interval="1d", limit=800)
        if bars:
            market[sym] = bars

    if not market:
        print("[perp_gate_sweep] no market data — fetch bars first (BinanceSpotOHLCVProvider needs network)")
        return 1

    tmp = tempfile.mkdtemp(prefix="cosmu-perp-sweep-")
    store = Store(Settings(database_url=f"sqlite:///{tmp}/sweep.sqlite3"))
    report = run_perp_gate_sweep(market, funding, store)
    print_report(report)
    return 0 if report.verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(_main())
