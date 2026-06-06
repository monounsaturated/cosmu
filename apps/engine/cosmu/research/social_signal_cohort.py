# intent: the Phase-0 SOCIAL-signal cohort harness — run the five LunarCrush social-signal specs (galaxy-score
# momentum breakout, social-sentiment divergence contrarian, social-volume collapse exit-filter, social-volume
# spike flat-price entry, cross-asset social rotation) through the EXISTING deterministic scorer + promote_cohort
# BH-FDR (q=0.10) on REAL Binance daily bars + REAL backfilled LunarCrush social history + PIT fees, as ONE
# cohort so the multiple-testing correction applies across the family. inputs: cached real daily bars + the
# on-disk LunarCrush JSONL store (offline-capable) + a Store for the shared trial ledger; outputs: a CohortReport.
# invariants: ZERO LLM calls; the scorer's statistical thresholds + promote_cohort q=0.10 are NOT changed here
# (we only INTERPRET); social metrics are joined point-in-time (align_asof on available_at = next-day, no
# look-ahead); every grid variant is recorded as a trial so deflation/FDR see the true count; deterministic for
# a fixed cache.
#
# Reuses carry_ablation's PIT data assembly + the xsec rank alt-join + the EXISTING Finder grid + scorer; the
# social alt-join (social_volume / social_sentiment / galaxy_score read from the AltDataStore) is the only new
# data seam. Mirrors funding_crowding_cohort.py — same shape, social features instead of funding.

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from cosmu.data.altdata import AltDataProvider, AltDataStore, StoreBackedAltProvider
from cosmu.data.backtest import _regime_labels, align_asof, run_strategy_backtest_detailed
from cosmu.data.market import Bar, BinanceSpotOHLCVProvider
from cosmu.knowledge.store import Store
from cosmu.master.cohort import Candidate, promote_cohort
from cosmu.master.scorer import score
from cosmu.master.trials import record_trial, trial_stats
from cosmu.research.carry_ablation import (
    _btc_daily_returns,
    _merge_alt,
    _real_market,
    _resolve_params,
    _xsec_rank_alt,
)
from cosmu.spine.venue import default_catalog
from cosmu.strategy.spec import StrategySpec

_SPECS = [
    "galaxy-score-momentum-breakout.json",
    "social-sentiment-divergence-contrarian.json",
    "social-volume-collapse-exit-filter.json",
    "social-volume-spike-flat-price-entry.json",
    "cross-asset-social-rotation.json",
    # Added once the four remaining LunarCrush fields (alt_rank et al.) were wired: the AltRank-improvement
    # long spec is part of the SAME cohort family, so the BH-FDR correction spans it too (no free pass for
    # adding a sixth test). It reads the newly-routed alt_rank metric.
    "alt-rank-improvement-long.json",
]

# LunarCrush semantic metrics joined as point-in-time alt features (feature_registry names). All seven hoarded
# coin time-series fields are read; the first three are the long-standing ingest metrics, the last four were
# banked-but-unwired until alt_rank/market_cap_usd/volume_24h_usd/price_usd were routed in store._STORE_PROVIDER_OF.
# Joining a metric a spec doesn't reference is harmless (the backtest just never reads it).
_SOCIAL_METRICS = (
    "social_volume", "social_sentiment", "galaxy_score",
    "alt_rank", "market_cap_usd", "volume_24h_usd", "price_usd",
)
# Fixed lookback the cross-asset-social-rotation spec's xsec_momentum_rank alt is precomputed at (mid of its
# rank_lb param range). The backtest reads a precomputed rank series directly; the per-variant rank_lb is not
# re-windowed for an alt feature (same approximation funding_crowding_cohort makes for xsec_momentum_rank).
_XSEC_RANK_LOOKBACK = 14


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
    reasons: list[str] = field(default_factory=list)


@dataclass
class CohortReport:
    verdict: str
    headline: str
    data_source: str
    window: str
    regimes_covered: dict[str, int]
    social_points: dict[str, int]
    fdr_q: float
    specs: list[SpecReport] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def load_specs() -> list[tuple[str, StrategySpec]]:
    import json
    from pathlib import Path

    inbox = Path(__file__).resolve().parents[2] / "strategies" / "inbox"
    return [(f, StrategySpec.model_validate(json.loads((inbox / f).read_text()))) for f in _SPECS]


def _social_alt(
    market: dict[str, list[Bar]], provider: AltDataProvider
) -> dict[str, dict[str, dict[str, float]]]:
    """Build the PIT social alt-data join feeding run_strategy_backtest: symbol -> {metric: {bar.ts: value}}.

    LunarCrush daily social buckets carry available_at = ts + 1 day (a day's social data is known only once the
    day closes). align_asof gives each bar the LATEST value whose available_at <= bar.ts — strictly point-in-time,
    no look-ahead. A symbol/metric with no history simply gets no entry (the feature reads None — honest absence)."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for symbol, bars in market.items():
        feats: dict[str, dict[str, float]] = {}
        for metric in _SOCIAL_METRICS:
            pts = provider.fetch_series(symbol, metric, limit=len(bars) + 2400)
            joined = align_asof(pts, bars)
            if joined:
                feats[metric] = joined
        if feats:
            out[symbol] = feats
    return out


def _clip_to_social_window(
    market: dict[str, list[Bar]], provider: AltDataProvider
) -> dict[str, list[Bar]]:
    """Restrict bars to the window where REAL social history exists (union across symbols/metrics), so the cohort
    is judged only where the signal could actually have been read."""
    lo: datetime | None = None
    hi: datetime | None = None
    for symbol in market:
        for metric in _SOCIAL_METRICS:
            pts = provider.fetch_series(symbol, metric, limit=4000)
            if not pts:
                continue
            lo = min(lo, pts[0].available_at) if lo else pts[0].available_at
            hi = max(hi, pts[-1].available_at) if hi else pts[-1].available_at
    if lo is None or hi is None:
        return market
    return {s: [b for b in bars if lo <= b.ts <= hi] for s, bars in market.items()}


def _spec_best(
    spec: StrategySpec,
    market: dict[str, list[Bar]],
    *,
    fee_bps: Decimal,
    alt: dict,
    store: Store,
    gates,  # noqa: ANN001
    label: str,
):
    """Finder-faithful: build the spec's coarse param GRID, screen every variant on REAL bars/social/fees,
    RECORD each as a trial (so deflation/FDR see the true count), and return the gate-best variant's params,
    its detailed result, and the per-variant validation-return streams (for a real CSCV-PBO)."""
    from cosmu.lab.finder import build_grid
    from cosmu.master.scorer import (
        cscv_pbo,  # noqa: F401 — kept local to mirror funding cohort import shape
    )

    grid = build_grid(spec, max_variants=64)
    best_params = _resolve_params(spec)
    best_result = None
    best_key = (-1, -1.0)
    most_trades = -1
    most_trading = None
    variant_streams: list[list[float]] = []
    for variant in grid:
        res = run_strategy_backtest_detailed(spec, variant.params, market, fee_bps=fee_bps, alt_by_symbol=alt)
        m = res.metrics
        record_trial(store, float(m.sharpe_per_obs), source="social_signal", label=f"{label}:{variant.config_tag}")
        v = score(m, gates, trials=trial_stats(store))
        if res.val_returns:
            variant_streams.append(res.val_returns)
        key = (1 if v.passed else 0, float(v.deflated_sharpe_prob))
        if key > best_key or best_result is None or (key == best_key and m.num_trades > best_result.metrics.num_trades):
            best_key, best_params, best_result = key, variant.params, res
        if m.num_trades > most_trades:
            most_trades = m.num_trades
            most_trading = (variant.params, res)
    if best_result is not None and best_result.metrics.num_trades == 0 and most_trades > 0 and most_trading:
        best_params, best_result = most_trading
    if best_result is None:
        best_result = run_strategy_backtest_detailed(spec, best_params, market, fee_bps=fee_bps, alt_by_symbol=alt)
    return best_params, best_result, variant_streams


def run_cohort(
    specs: list[tuple[str, StrategySpec]],
    market: dict[str, list[Bar]],
    provider: AltDataProvider,
    store: Store,
    *,
    data_source: str = "live-cached",
    fdr_q: float = 0.10,
    override_alt: dict[str, dict[str, dict[str, float]]] | None = None,
) -> CohortReport:
    from cosmu.master.scorer import cscv_pbo

    gates = store.settings.gates
    fee_bps = default_catalog().venue("binance").taker_fee_bps
    _ = _btc_daily_returns(market)  # (kept for parity; corr-to-BTC is N/A for these directional long-only books)

    social_points = {
        s: sum(len(provider.fetch_series(s, mtr, limit=4000)) for mtr in _SOCIAL_METRICS) for s in market
    }
    regimes_covered: dict[str, int] = {}
    win_lo = win_hi = None
    for _symbol, bars in market.items():
        closes = [float(b.close) for b in bars]
        for r in _regime_labels(closes):
            regimes_covered[r] = regimes_covered.get(r, 0) + 1
        if bars:
            win_lo = min(win_lo, bars[0].ts) if win_lo else bars[0].ts
            win_hi = max(win_hi, bars[-1].ts) if win_hi else bars[-1].ts
    window = f"{win_lo.date()}..{win_hi.date()}" if win_lo and win_hi else "n/a"

    # override_alt lets a caller supply a DERIVED (e.g. normalized) social join instead of the raw-level one —
    # the only seam the non-obvious cohort changes; everything downstream (grid, scorer, FDR) is identical.
    social_alt = override_alt if override_alt is not None else _social_alt(market, provider)
    notes: list[str] = []
    if not social_alt or all(v == 0 for v in social_points.values()):
        return CohortReport("INSUFFICIENT-DATA", "no real social history in cache", data_source, window,
                            regimes_covered, social_points, fdr_q,
                            notes=["LunarCrush JSONL cache empty — run the backfill then re-run"])

    # xsec rank alt needed for cross-asset-social-rotation; merge with social alt for all specs (harmless extra).
    rank_alt = _xsec_rank_alt(market, _XSEC_RANK_LOOKBACK)
    alt = _merge_alt(social_alt, rank_alt)

    candidates: list[Candidate] = []
    reports: list[SpecReport] = []
    for fname, spec in specs:
        sid = fname.replace(".json", "")
        params, res, streams = _spec_best(spec, market, fee_bps=fee_bps, alt=alt, store=store, gates=gates, label=sid)
        m = res.metrics
        # gross = SAME signals, ZERO transaction cost (fee/slip/impact = 0) → cost_ratio = net/gross
        gross = run_strategy_backtest_detailed(spec, params, market, fee_bps=Decimal("0"), slippage_bps=Decimal("0"),
                                               impact_bps=Decimal("0"), alt_by_symbol=alt).metrics
        net_return = float(m.oos_return)
        gross_return = float(gross.oos_return)
        cost_ratio = float(m.cost_ratio)
        if cost_ratio == 0.0 and gross_return:
            cost_ratio = net_return / gross_return
        usable = [s for s in streams if s]
        pbo = cscv_pbo(usable) if len(usable) >= 2 else float(m.pbo)
        var = statistics.pvariance(res.val_returns) if len(res.val_returns) > 1 else 1.0
        candidates.append(Candidate(id=sid, metrics=m, net_profit=net_return, source="social_signal",
                                    label=sid, return_variance=var or 1.0))
        reports.append(SpecReport(
            name=sid, net_return=round(net_return, 6), gross_return=round(gross_return, 6),
            cost_ratio=round(cost_ratio, 4),
            deflated_sharpe_prob=round(float(score(m, gates, trials=trial_stats(store)).deflated_sharpe_prob), 6),
            cscv_pbo=round(pbo, 6),
            regimes_positive=sum(1 for v in m.regime_returns.values() if v > 0),
            num_trades=m.num_trades, max_drawdown=round(float(m.max_drawdown), 6),
            skew=round(float(m.skew), 4), gate_passed=False,
        ))

    # COHORT BH-FDR across the family — ledger already holds every grid variant, so register=False + the shared
    # trial_stats so deflation/FDR see the true (grid-inflated) count, not just the 5 representatives.
    promotions = promote_cohort(store, candidates, gates, fdr_q=fdr_q, register=False, trials=trial_stats(store))
    by_id = {p.candidate_id: p for p in promotions}
    for r in reports:
        p = by_id.get(r.name)
        if p:
            r.survived_fdr = p.survived_fdr
            r.promoted = p.promoted
            r.gate_passed = p.promoted  # promoted == passes per-candidate stats gate AND survives FDR
            r.reasons = p.reasons

    promoted = [r for r in reports if r.promoted]
    if promoted:
        verdict = "PASS"
        headline = f"{len(promoted)} spec(s) survived the cohort gate + BH-FDR (q={fdr_q}): " + ", ".join(r.name for r in promoted)
    else:
        verdict = "FAIL"
        best = max(reports, key=lambda r: r.deflated_sharpe_prob) if reports else None
        headline = (f"no spec survived the cohort gate + BH-FDR (q={fdr_q}); best DSR {best.deflated_sharpe_prob} ({best.name})"
                    if best else "no candidates")
    return CohortReport(verdict, headline, data_source, window, regimes_covered, social_points, fdr_q,
                        specs=reports, notes=notes)


def _main() -> int:
    import tempfile

    from cosmu.config.settings import Settings

    tmp = tempfile.mkdtemp(prefix="cosmu-social-")
    store = Store(Settings(database_url=f"sqlite:///{tmp}/social.sqlite3", openrouter_api_key=None))
    specs = load_specs()
    provider = StoreBackedAltProvider(AltDataStore(".cosmu/altdata"))
    market = _clip_to_social_window(_real_market(BinanceSpotOHLCVProvider()), provider)
    report = run_cohort(specs, market, provider, store)

    print(f"PHASE-0 SOCIAL-SIGNAL COHORT — {report.verdict}")
    print(f"  data_source={report.data_source}  window={report.window}  regimes={report.regimes_covered}")
    print(f"  social symbols with data: {sum(1 for v in report.social_points.values() if v)}/{len(report.social_points)} "
          f"(max points/symbol={max(report.social_points.values(), default=0)})")
    print(f"  cohort BH-FDR q={report.fdr_q}")
    for a in report.specs:
        flag = "PROMOTED" if a.promoted else ("fdr-only" if a.survived_fdr else "stop")
        print(f"  [{flag:>8}] {a.name:<42} net={a.net_return:+.4f} gross={a.gross_return:+.4f} "
              f"cost_ratio={a.cost_ratio:.3f} dsr={a.deflated_sharpe_prob:.3f} pbo={a.cscv_pbo:.3f} "
              f"reg+={a.regimes_positive} trades={a.num_trades} maxDD={a.max_drawdown:.3f} skew={a.skew:+.2f} "
              f"fdr={'Y' if a.survived_fdr else 'N'}")
        if a.reasons:
            print(f"             reasons: {', '.join(a.reasons)}")
    for n in report.notes:
        print(f"  note: {n}")
    print(f"  HEADLINE: {report.headline}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
