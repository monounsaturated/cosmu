# intent: verify the perp cost sweep module parses, builds alt features, and returns a PerpSweepReport
# with the correct structure — offline (no network, no real bar data required).

from __future__ import annotations

import random
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataPoint, FixtureAltDataProvider
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store
from cosmu.research.perp_gate_sweep import (
    COST_RATIO_FLOOR,
    SWEEP_SCENARIOS,
    PerpSweepReport,
    ScenarioResult,
    _apply_funding_cost,
    _xsec_funding_rank_alt,
    run_perp_gate_sweep,
)


# ---------------------------------------------------------------------------
# Synthetic helpers
# ---------------------------------------------------------------------------

_BASE = datetime(2023, 1, 1, tzinfo=UTC)
_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT")


def _make_bars(symbol: str, n: int = 300, seed: int = 0) -> list[Bar]:
    rng = random.Random(f"{symbol}-{seed}")
    p = {"BTCUSDT": 30000.0, "ETHUSDT": 2000.0}.get(symbol, 1.0 + rng.random() * 99)
    bars: list[Bar] = []
    for i in range(n):
        ret = rng.gauss(0.0003, 0.012)
        p *= 1 + ret
        ts = _BASE + timedelta(days=i)
        bars.append(Bar(
            ts=ts, open=Decimal(str(round(p * 0.999, 4))),
            high=Decimal(str(round(p * 1.005, 4))),
            low=Decimal(str(round(p * 0.994, 4))),
            close=Decimal(str(round(p, 4))),
            volume=Decimal("1000"),
        ))
    return bars


def _make_funding_provider(symbols: tuple[str, ...], n_points: int = 300) -> FixtureAltDataProvider:
    """Synthetic funding rates: ~0.01%/8h with per-symbol variation so cross-sectional rank is non-trivial."""
    rng = random.Random("funding-fixture")
    series: dict[tuple[str, str], list[AltDataPoint]] = {}
    for sym in symbols:
        pts: list[AltDataPoint] = []
        base_rate = rng.uniform(-0.0001, 0.0003)
        for i in range(n_points):
            ts = _BASE + timedelta(hours=i * 8)
            rate = base_rate + rng.gauss(0, 0.00005)
            pts.append(AltDataPoint(ts=ts, available_at=ts, value=rate))
        series[(sym, "funding_rate")] = pts
    return FixtureAltDataProvider(series)


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

def test_sweep_scenarios_preregistered() -> None:
    """The 7 pre-registered scenarios are present and span the expected fee/funding range."""
    assert len(SWEEP_SCENARIOS) == 7
    labels = {sc["label"] for sc in SWEEP_SCENARIOS}
    assert "gross_frictionless" in labels
    assert "kf_perp_no_fund" in labels
    assert "kf_perp_typ_fund" in labels
    assert "okx_perp_typ_fund" in labels


def test_apply_funding_cost_long_pays_positive_funding() -> None:
    """A long position PAYS positive funding — net return decreases."""
    from cosmu.master.scorer import BacktestMetrics

    m = BacktestMetrics(
        oos_return=Decimal("0.05"), sharpe=Decimal("1.5"), sortino=Decimal("0"),
        max_drawdown=Decimal("0.05"), win_rate=Decimal("0.6"), num_trades=10,
        sharpe_per_obs=Decimal("0.1"), skew=Decimal("-0.5"), kurtosis=Decimal("3.0"),
        n_obs=100, pbo=Decimal("0"), trials_counted=1, folds_positive_pct=Decimal("0.6"),
        holdout_deflated_sharpe=Decimal("0.5"), regime_returns={}, cost_ratio=Decimal("0.8"),
    )
    adjusted = _apply_funding_cost(m, funding_bps_per_bar=3.0, direction=+1)
    assert float(adjusted.oos_return) < float(m.oos_return)


def test_apply_funding_cost_short_receives_positive_funding() -> None:
    """A short position RECEIVES positive funding — net return increases."""
    from cosmu.master.scorer import BacktestMetrics

    m = BacktestMetrics(
        oos_return=Decimal("0.02"), sharpe=Decimal("0.8"), sortino=Decimal("0"),
        max_drawdown=Decimal("0.04"), win_rate=Decimal("0.5"), num_trades=8,
        sharpe_per_obs=Decimal("0.05"), skew=Decimal("0.2"), kurtosis=Decimal("3.0"),
        n_obs=80, pbo=Decimal("0"), trials_counted=1, folds_positive_pct=Decimal("0.5"),
        holdout_deflated_sharpe=Decimal("0.4"), regime_returns={}, cost_ratio=Decimal("0.7"),
    )
    adjusted = _apply_funding_cost(m, funding_bps_per_bar=3.0, direction=-1)
    assert float(adjusted.oos_return) > float(m.oos_return)


def test_apply_funding_cost_zero_bps_no_change() -> None:
    """Zero funding bps leaves the metric unchanged."""
    from cosmu.master.scorer import BacktestMetrics

    m = BacktestMetrics(
        oos_return=Decimal("0.05"), sharpe=Decimal("1.5"), sortino=Decimal("0"),
        max_drawdown=Decimal("0.05"), win_rate=Decimal("0.6"), num_trades=10,
        sharpe_per_obs=Decimal("0.1"), skew=Decimal("-0.5"), kurtosis=Decimal("3.0"),
        n_obs=100, pbo=Decimal("0"), trials_counted=1, folds_positive_pct=Decimal("0.6"),
        holdout_deflated_sharpe=Decimal("0.5"), regime_returns={}, cost_ratio=Decimal("0.8"),
    )
    adjusted = _apply_funding_cost(m, funding_bps_per_bar=0.0, direction=+1)
    assert float(adjusted.oos_return) == float(m.oos_return)


def test_xsec_funding_rank_produces_zero_to_one() -> None:
    """Cross-sectional funding rank values must lie in [0, 1] at every bar."""
    market = {s: _make_bars(s, n=60) for s in _SYMBOLS}
    provider = _make_funding_provider(_SYMBOLS)
    rank_alt = _xsec_funding_rank_alt(market, provider)

    for symbol, feats in rank_alt.items():
        ranks = feats.get("xsec_funding_rank", {})
        for ts_key, rank in ranks.items():
            assert 0.0 <= rank <= 1.0, f"{symbol}@{ts_key}: rank={rank} out of [0,1]"


def test_xsec_funding_rank_spans_full_range() -> None:
    """With 5 symbols per bar, the rank distribution should include both 0.0 and 1.0."""
    market = {s: _make_bars(s, n=100) for s in _SYMBOLS}
    provider = _make_funding_provider(_SYMBOLS)
    rank_alt = _xsec_funding_rank_alt(market, provider)

    all_ranks: list[float] = [
        v
        for feats in rank_alt.values()
        for v in feats.get("xsec_funding_rank", {}).values()
    ]
    assert any(r < 0.1 for r in all_ranks), "no low-rank values found"
    assert any(r > 0.9 for r in all_ranks), "no high-rank values found"


def test_run_perp_gate_sweep_returns_report_on_no_funding() -> None:
    """Empty funding data → INSUFFICIENT-DATA verdict (not a crash, not a fake pass)."""
    market = {s: _make_bars(s, n=300) for s in _SYMBOLS}
    empty_funding = FixtureAltDataProvider({})  # no funding data

    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Settings(database_url=f"sqlite:///{tmp}/test.sqlite3"))
        report = run_perp_gate_sweep(market, empty_funding, store, data_source="synthetic")

    assert isinstance(report, PerpSweepReport)
    assert report.verdict == "INSUFFICIENT-DATA"
    assert report.scenarios == []


def test_run_perp_gate_sweep_with_synthetic_funding_runs_without_error() -> None:
    """With synthetic bars + funding, the sweep runs to completion (no crash). Verdict may be
    FAIL/PASS/INSUFFICIENT-DATA depending on the synthetic edge — we only assert no exception."""
    market = {s: _make_bars(s, n=300) for s in _SYMBOLS}
    provider = _make_funding_provider(_SYMBOLS)

    # Use a minimal 2-scenario subset to keep the test fast
    fast_scenarios = [
        sc for sc in SWEEP_SCENARIOS
        if sc["label"] in ("gross_frictionless", "kf_perp_no_fund")
    ]

    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Settings(database_url=f"sqlite:///{tmp}/test.sqlite3"))
        report = run_perp_gate_sweep(
            market, provider, store, data_source="synthetic", scenarios=fast_scenarios
        )

    assert isinstance(report, PerpSweepReport)
    assert report.verdict in ("PASS", "FAIL", "INSUFFICIENT-DATA")
    # If we ran any scenarios, each has the right structure
    for sc in report.scenarios:
        assert isinstance(sc, ScenarioResult)
        assert sc.pair_cost_ratio >= 0.0
        assert isinstance(sc.holds, bool)
        assert isinstance(sc.fragile, bool)
        assert isinstance(sc.bad_tail, bool)
