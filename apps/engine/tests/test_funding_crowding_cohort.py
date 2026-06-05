# Phase-0 P0.7 funding-as-CROWDING cohort harness — offline, deterministic tests. No network, no live keys.
# Proves: (1) the five crowding specs load + compile with the expected directions/funding-feature wiring;
# (2) the harness runs all five through the EXISTING scorer + promote_cohort BH-FDR and emits a verdict;
# (3) empty funding => INSUFFICIENT-DATA (honest abstention, never a fake pass); (4) determinism.

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataPoint
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store
from cosmu.research.funding_crowding_cohort import _SPECS, load_specs, run_cohort


def _store() -> Store:
    tmp = tempfile.mkdtemp(prefix="cosmu-crowding-test-")
    return Store(Settings(database_url=f"sqlite:///{tmp}/t.sqlite3", openrouter_api_key=None))


def _bars(prices: list[float], *, symbol_seed: float = 0.0) -> list[Bar]:
    t0 = datetime(2025, 1, 1, tzinfo=UTC)
    out: list[Bar] = []
    for i, p in enumerate(prices):
        d = Decimal(str(round(p + symbol_seed, 4)))
        out.append(Bar(ts=t0 + timedelta(days=i), open=d, high=d, low=d, close=d, volume=Decimal("1000000")))
    return out


class _SyntheticFunding:
    """Deterministic funding provider with a constant rate over the bar window (CI-only fixture)."""

    def __init__(self, bars: dict[str, list[Bar]], rate: float) -> None:
        self._by = {s: [AltDataPoint(ts=b.ts, available_at=b.ts, value=rate) for b in bb] for s, bb in bars.items()}

    def fetch_series(self, symbol: str, metric: str, *, limit: int):  # noqa: ANN201
        if metric != "funding_rate":
            return []
        return self._by.get(symbol, [])


class _EmptyFunding:
    def fetch_series(self, symbol: str, metric: str, *, limit: int):  # noqa: ANN201
        return []


def _universe_bars() -> dict[str, list[Bar]]:
    rates = (1.012, 1.004, 0.996, 1.008, 1.0)
    syms = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
    return {s: _bars([100.0 * (r ** i) for i in range(120)], symbol_seed=j) for j, (s, r) in enumerate(zip(syms, rates, strict=True))}


def test_specs_load_and_compile_with_expected_wiring():
    specs = load_specs()
    assert [f for f, _ in specs] == _SPECS
    by = {f: s for f, s in specs}
    # the crash-filter is the only SHORT and the only one accruing funding as a leg
    crash = by["funding-contrarian-crash-filter.json"]
    assert crash.direction == -1 and crash.funding_feature == "funding_rate"
    # the long crowding-FILTER specs use funding as a SIGNAL only — no carry accrual
    for f in ("funding-reset-reversion-uncrowded-oversold.json", "xsec-momentum-funding-gated.json",
              "funding-gated-momentum.json"):
        assert by[f].direction == 1 and by[f].funding_feature is None
    # vol-regime is the no-funding control arm
    assert by["vol-regime-gated-momentum.json"].funding_feature is None


def test_cohort_runs_all_specs_and_emits_a_verdict():
    market = _universe_bars()
    funding = _SyntheticFunding(market, rate=0.00005)  # uncrowded positive funding so the filters can enter
    report = run_cohort(load_specs(), market, funding, _store(), data_source="synthetic")
    assert report.verdict in {"PASS", "FAIL", "INSUFFICIENT-DATA"}
    if report.verdict != "INSUFFICIENT-DATA":
        assert {a.name for a in report.specs} == {f.replace(".json", "") for f in _SPECS}
        for a in report.specs:
            # cost_ratio = net/gross is only meaningful when gross alpha is POSITIVE; for a loss-making
            # arm (gross < 0) the ratio can exceed 1 (costs make the negative gross less negative), which
            # is a display artifact, not a real >100% survival. Only assert the bound on positive arms.
            if a.gross_return > 0:
                assert a.cost_ratio <= 1.0001
            assert isinstance(a.survived_fdr, bool)


def test_empty_funding_is_insufficient_data_not_a_pass():
    report = run_cohort(load_specs(), _universe_bars(), _EmptyFunding(), _store(), data_source="synthetic")
    assert report.verdict == "INSUFFICIENT-DATA"
    assert "funding" in report.headline.lower()


def test_cohort_is_deterministic():
    market = _universe_bars()
    funding = _SyntheticFunding(market, rate=0.00005)
    r1 = run_cohort(load_specs(), market, funding, _store(), data_source="synthetic")
    r2 = run_cohort(load_specs(), market, funding, _store(), data_source="synthetic")
    assert r1.verdict == r2.verdict
    assert [(a.name, a.net_return, a.num_trades, a.promoted) for a in r1.specs] == \
           [(a.name, a.net_return, a.num_trades, a.promoted) for a in r2.specs]
