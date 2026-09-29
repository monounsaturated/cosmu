# Phase-0 P0.6 carry/neutral ablation harness — offline, deterministic tests. No network, no live keys.
# Proves: (1) CachedFundingRateProvider reads a real-shaped cache and is empty-safe; (2) the PIT xsec rank is
# point-in-time and percentile-correct; (3) the harness runs all arms through the EXISTING scorer and emits a
# verdict; (4) empty funding => INSUFFICIENT-DATA (honest abstention, never a fake pass); (5) determinism.

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataPoint, CachedFundingRateProvider
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store
from cosmu.research.carry_ablation import (
    MIN_TRADES,
    _correlation,
    _xsec_rank_alt,
    load_specs,
    run_carry_ablation,
)


def _store() -> Store:
    tmp = tempfile.mkdtemp(prefix="cosmu-carry-test-")
    return Store(Settings(database_url=f"sqlite:///{tmp}/t.sqlite3", openrouter_api_key=None))


def _bars(prices: list[float], *, symbol_seed: float = 0.0) -> list[Bar]:
    t0 = datetime(2025, 1, 1, tzinfo=UTC)
    out: list[Bar] = []
    for i, p in enumerate(prices):
        d = Decimal(str(round(p + symbol_seed, 4)))
        out.append(Bar(ts=t0 + timedelta(days=i), open=d, high=d, low=d, close=d, volume=Decimal("1000000")))
    return out


class _SyntheticFunding:
    """A deterministic funding provider with a constant positive rate over the bar window (CI-only fixture)."""

    def __init__(self, bars: dict[str, list[Bar]], rate: float) -> None:
        self._by = {s: [AltDataPoint(ts=b.ts, available_at=b.ts, value=rate) for b in bb] for s, bb in bars.items()}

    def fetch_series(self, symbol: str, metric: str, *, limit: int):  # noqa: ANN201
        if metric != "funding_rate":
            return []
        return self._by.get(symbol, [])


class _EmptyFunding:
    def fetch_series(self, symbol: str, metric: str, *, limit: int):  # noqa: ANN201
        return []


# --------------------------------------------------------------------------- CachedFundingRateProvider


def test_cached_funding_reads_cache_and_is_empty_safe():
    tmp = Path(tempfile.mkdtemp())
    rows = [{"fundingTime": int(datetime(2025, 5, 1, tzinfo=UTC).timestamp() * 1000) + i * 8 * 3600 * 1000,
             "fundingRate": "0.0001"} for i in range(10)]
    (tmp / "BTCUSDT.json").write_text(json.dumps(rows))
    prov = CachedFundingRateProvider(cache_dir=tmp)
    pts = prov.fetch_series("BTCUSDT", "funding_rate", limit=1000)
    assert len(pts) == 10
    assert all(p.available_at == p.ts for p in pts)  # PIT: published == observed
    assert pts[0].ts < pts[-1].ts  # sorted ascending
    # missing symbol => empty (honest 'no data', never a fabricated rate)
    assert prov.fetch_series("MISSING", "funding_rate", limit=1000) == []
    # wrong metric => empty
    assert prov.fetch_series("BTCUSDT", "fear_greed", limit=1000) == []


# --------------------------------------------------------------------------- PIT xsec rank


def test_xsec_rank_is_point_in_time_and_percentile():
    # two symbols; A always outperforms B on trailing return => A ranks 1.0, B ranks 0.0
    market = {
        "AAA": _bars([100.0 * (1.02 ** i) for i in range(60)]),
        "BBB": _bars([100.0 * (1.005 ** i) for i in range(60)]),
    }
    out = _xsec_rank_alt(market, lookback=10)
    a_ranks = list(out["AAA"]["xsec_momentum_rank"].values())
    b_ranks = list(out["BBB"]["xsec_momentum_rank"].values())
    assert a_ranks and b_ranks
    assert all(r == 1.0 for r in a_ranks), "the faster-compounding symbol must rank top (1.0)"
    assert all(r == 0.0 for r in b_ranks), "the slower symbol must rank bottom (0.0)"
    # PIT: the first `lookback` bars have no trailing return => no rank emitted there
    first_key = market["AAA"][0].ts.isoformat()
    assert first_key not in out["AAA"]["xsec_momentum_rank"]


def test_correlation_bounds_and_neutrality():
    assert _correlation([1.0, -1.0, 1.0, -1.0], [1.0, -1.0, 1.0, -1.0]) == 1.0
    assert _correlation([1.0, -1.0, 1.0, -1.0], [-1.0, 1.0, -1.0, 1.0]) == -1.0
    assert _correlation([0.0, 0.0, 0.0], [1.0, 2.0, 3.0]) == 0.0  # constant => undefined => 0


# --------------------------------------------------------------------------- the harness


def _real_universe_bars() -> dict[str, list[Bar]]:
    # 120 bars across all 5 universe symbols, distinct paths so xsec ranking is non-degenerate
    rates = (1.012, 1.004, 0.996, 1.008, 1.0)
    syms = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
    return {s: _bars([100.0 * (r ** i) for i in range(120)], symbol_seed=j) for j, (s, r) in enumerate(zip(syms, rates, strict=True))}


def test_harness_runs_all_arms_and_emits_a_verdict():
    market = _real_universe_bars()
    funding = _SyntheticFunding(market, rate=0.0005)  # positive funding so the carry signal can enter
    specs = load_specs()
    report = run_carry_ablation(*specs, market, funding, _store(), data_source="synthetic")
    assert report.verdict in {"PASS", "FAIL", "INSUFFICIENT-DATA"}
    names = {a.name for a in report.arms}
    # the full ablation set must be present (when there is funding data)
    assert {"carry_short_perp", "carry_long_spot", "neutral_carry_pair", "xsec_neutral_pair", "buy_and_hold"} <= names
    for a in report.arms:
        assert -1.0 <= a.corr_to_btc <= 1.0
        assert a.cost_ratio <= 1.0001


def test_empty_funding_is_insufficient_data_not_a_pass():
    market = _real_universe_bars()
    report = run_carry_ablation(*load_specs(), market, _EmptyFunding(), _store(), data_source="synthetic")
    assert report.verdict == "INSUFFICIENT-DATA"
    assert "funding" in report.headline.lower()


def test_harness_is_deterministic():
    market = _real_universe_bars()
    funding = _SyntheticFunding(market, rate=0.0005)
    r1 = run_carry_ablation(*load_specs(), market, funding, _store(), data_source="synthetic")
    r2 = run_carry_ablation(*load_specs(), market, funding, _store(), data_source="synthetic")
    assert r1.verdict == r2.verdict
    assert [(a.name, a.net_return, a.num_trades) for a in r1.arms] == [(a.name, a.net_return, a.num_trades) for a in r2.arms]


def test_specs_load_with_correct_directions():
    carry_short, carry_long, xsec_long, xsec_short = load_specs()
    assert carry_short.direction == -1 and carry_short.funding_feature == "funding_rate"
    assert carry_long.direction == 1
    assert xsec_long.direction == 1 and xsec_short.direction == -1
