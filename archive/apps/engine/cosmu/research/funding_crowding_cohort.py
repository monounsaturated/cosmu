# intent: the Phase-0 funding-as-CROWDING/POSITIONING cohort harness — run the five funding-crowding specs
# (contrarian crash-filter, reset reversion, xsec momentum funding-gated, vol-regime-gated momentum, funding-gated
# momentum) through the EXISTING deterministic scorer + promote_cohort BH-FDR (q=0.10) on REAL Binance bars +
# REAL funding + PIT fees, as ONE cohort so the multiple-testing correction applies across the family. inputs:
# cached real daily bars + cached real funding (offline-capable) + a Store for the shared trial ledger; outputs:
# a CohortReport. invariants: ZERO LLM calls; the scorer's statistical thresholds + promote_cohort q=0.10 are
# NOT changed here (we only INTERPRET); funding + fees are point-in-time (no look-ahead); funding here is a
# SIGNAL/FILTER (funding_feature null on the momentum specs — no carry accrual), NOT a premium to harvest; every
# grid variant is recorded as a trial so deflation/FDR see the true count; deterministic for a fixed cache.
#
# Reuses carry_ablation's PIT data assembly (real bars clipped to the funding window, funding alt-join, xsec rank
# alt-join) and the EXISTING Finder grid + scorer; the only new piece is routing the five DISTINCT gate-best
# candidates through cohort.promote_cohort (BH-FDR across the family).

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from decimal import Decimal

from cosmu.data.altdata import AltDataProvider, CachedFundingRateProvider
from cosmu.data.backtest import _regime_labels, run_strategy_backtest_detailed
from cosmu.data.market import Bar, default_crypto_reference
from cosmu.knowledge.store import Store
from cosmu.master.cohort import Candidate, promote_cohort
from cosmu.master.scorer import cscv_pbo, score
from cosmu.master.trials import record_trial, trial_stats
from cosmu.master.verdict_log import durable_persist
from cosmu.spine.venue import default_catalog
from cosmu.strategy.spec import StrategySpec
from cosmu.research.carry_ablation import (
    _clip_to_funding_window,
    _funding_alt,
    _merge_alt,
    _real_market,
    _resolve_params,
    _xsec_rank_alt,
)

_SPECS = [
    "funding-contrarian-crash-filter.json",
    "funding-reset-reversion-uncrowded-oversold.json",
    "xsec-momentum-funding-gated.json",
    "vol-regime-gated-momentum.json",
    "funding-gated-momentum.json",
]


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
    corr_to_btc: float
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
    funding_points: dict[str, int]
    fdr_q: float
    specs: list[SpecReport] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def load_specs() -> list[tuple[str, StrategySpec]]:
    import json
    from pathlib import Path

    inbox = Path(__file__).resolve().parents[2] / "strategies" / "inbox"
    return [(f, StrategySpec.model_validate(json.loads((inbox / f).read_text()))) for f in _SPECS]


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
    """Finder-faithful: build the spec's coarse param GRID, screen every variant on REAL bars/funding/fees,
    RECORD each as a trial (so deflation/FDR see the true count), and return the gate-best variant's params,
    its detailed result, and the list of per-variant validation-return streams (for a real CSCV-PBO)."""
    from cosmu.lab.finder import build_grid

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
        record_trial(store, float(m.sharpe_per_obs), source="funding_crowding", label=f"{label}:{variant.config_tag}")
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
    funding: AltDataProvider,
    store: Store,
    *,
    data_source: str = "live-cached",
    fdr_q: float = 0.10,
    persist: bool = False,
) -> CohortReport:
    """`persist=True` records the cohort verdict to durable experiment-memory (gate_verdicts) via the real
    configured store — _main sets it on real runs; tests leave it False so they never touch the durable store."""
    gates = store.settings.gates
    fee_bps = default_catalog().venue("binance").taker_fee_bps

    funding_points = {s: len(funding.fetch_series(s, "funding_rate", limit=3000)) for s in market}
    regimes_covered: dict[str, int] = {}
    win_lo = win_hi = None
    for symbol, bars in market.items():
        closes = [float(b.close) for b in bars]
        for r in _regime_labels(closes):
            regimes_covered[r] = regimes_covered.get(r, 0) + 1
        if bars:
            win_lo = min(win_lo, bars[0].ts) if win_lo else bars[0].ts
            win_hi = max(win_hi, bars[-1].ts) if win_hi else bars[-1].ts
    window = f"{win_lo.date()}..{win_hi.date()}" if win_lo and win_hi else "n/a"

    funding_alt = _funding_alt(market, funding)
    notes: list[str] = []
    if not funding_alt or all(v == 0 for v in funding_points.values()):
        return CohortReport("INSUFFICIENT-DATA", "no real funding history in cache", data_source, window,
                            regimes_covered, funding_points, fdr_q,
                            notes=["funding cache empty — materialize from DB / run backfill_funding then re-run"])

    # xsec rank alt needed for the xsec-momentum spec; merge with funding alt for all specs (harmless extra feature)
    rank_alt = _xsec_rank_alt(market, 30)
    alt = _merge_alt(funding_alt, rank_alt)

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
        # real CSCV-PBO across this spec's own grid variant streams (a legitimate config population)
        usable = [s for s in streams if s]
        pbo = cscv_pbo(usable) if len(usable) >= 2 else float(m.pbo)
        # corr-to-BTC is only a meaningful gate criterion for a DELTA-NEUTRAL pair (it tests that beta cancels).
        # These specs are long-only/single-direction DIRECTIONAL books, so a ~1 corr-to-BTC is EXPECTED, not a
        # flaw — the criterion does not apply. `res.val_returns` is moreover a pooled multi-symbol stream, so a
        # single-series Pearson vs BTC is undefined here; we report it as not-applicable rather than a misleading
        # number. (Directionality is captured by the regime+ / beats-buy-and-hold criteria instead.)
        corr = float("nan")
        var = statistics.pvariance(res.val_returns) if len(res.val_returns) > 1 else 1.0
        candidates.append(Candidate(id=sid, metrics=m, net_profit=net_return, source="funding_crowding",
                                    label=sid, return_variance=var or 1.0))
        reports.append(SpecReport(
            name=sid, net_return=round(net_return, 6), gross_return=round(gross_return, 6),
            cost_ratio=round(cost_ratio, 4), deflated_sharpe_prob=round(float(score(m, gates, trials=trial_stats(store)).deflated_sharpe_prob), 6),
            cscv_pbo=round(pbo, 6),
            regimes_positive=sum(1 for v in m.regime_returns.values() if v > 0),
            num_trades=m.num_trades, max_drawdown=round(float(m.max_drawdown), 6),
            skew=round(float(m.skew), 4), corr_to_btc=round(corr, 4), gate_passed=False,
        ))

    # COHORT BH-FDR across the family — ledger already holds every grid variant, so register=False + the shared
    # trial_stats so deflation/FDR see the true (grid-inflated) count, not just the 5 representatives.
    persist_spec = durable_persist(
        run_id=f"funding-crowding-{data_source}",
        hypothesis="a funding-as-crowding/positioning signal carries a gate-clearing edge on Binance spot (vs momentum)",
        source="research/funding_crowding", data_source=data_source, fdr_q=fdr_q,
    ) if persist else None
    promotions = promote_cohort(store, candidates, gates, fdr_q=fdr_q, register=False, trials=trial_stats(store), persist=persist_spec)
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
    return CohortReport(verdict, headline, data_source, window, regimes_covered, funding_points, fdr_q,
                        specs=reports, notes=notes)


def _main() -> int:
    import tempfile

    from cosmu.config.settings import Settings

    tmp = tempfile.mkdtemp(prefix="cosmu-crowding-")
    store = Store(Settings(database_url=f"sqlite:///{tmp}/crowding.sqlite3", openrouter_api_key=None))
    specs = load_specs()
    funding = CachedFundingRateProvider()
    market = _clip_to_funding_window(_real_market(default_crypto_reference()), funding)
    report = run_cohort(specs, market, funding, store, persist=True)

    print(f"PHASE-0 FUNDING-CROWDING COHORT — {report.verdict}")
    print(f"  data_source={report.data_source}  window={report.window}  regimes={report.regimes_covered}")
    print(f"  funding symbols with data: {sum(1 for v in report.funding_points.values() if v)}/{len(report.funding_points)} "
          f"(max points/symbol={max(report.funding_points.values(), default=0)})")
    print(f"  cohort BH-FDR q={report.fdr_q}")
    for a in report.specs:
        flag = "PROMOTED" if a.promoted else ("fdr-only" if a.survived_fdr else "stop")
        corr = "n/a" if a.corr_to_btc != a.corr_to_btc else f"{a.corr_to_btc:+.3f}"  # NaN check
        print(f"  [{flag:>8}] {a.name:<46} net={a.net_return:+.4f} gross={a.gross_return:+.4f} "
              f"cost_ratio={a.cost_ratio:.3f} dsr={a.deflated_sharpe_prob:.3f} pbo={a.cscv_pbo:.3f} "
              f"reg+={a.regimes_positive} trades={a.num_trades} maxDD={a.max_drawdown:.3f} skew={a.skew:+.2f} "
              f"corrBTC={corr} fdr={'Y' if a.survived_fdr else 'N'}")
        if a.reasons:
            print(f"             reasons: {', '.join(a.reasons)}")
    for n in report.notes:
        print(f"  note: {n}")
    print(f"  HEADLINE: {report.headline}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
