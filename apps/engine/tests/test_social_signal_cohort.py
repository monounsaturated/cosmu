# Social-signal cohort + LunarCrush wiring — offline, deterministic tests. No network, no live keys, no DB.
# Proves:
#   (1) all SEVEN hoarded LunarCrush metrics route through StoreBackedAltProvider and round-trip store->read
#       point-in-time (the gate's per-bar as-of join sees the full revision trail; no future value leaks back);
#   (2) the BTC<->BTCUSDT symbol-key fallback makes the bulk hoard (coin-keyed) readable by the backtest
#       (pair-keyed), while an EXACT key still wins (no silent re-route);
#   (3) the four newly-wired metrics (alt_rank/market_cap_usd/volume_24h_usd/price_usd) are in the registry
#       AND the provider route;
#   (4) the social-signal cohort runs all specs through the EXISTING scorer + promote_cohort BH-FDR on
#       synthetic bars+social and emits a Gate verdict (PASS/FAIL/INSUFFICIENT-DATA);
#   (5) empty social => INSUFFICIENT-DATA (honest abstention, never a fake pass); (6) determinism.

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.feature_registry import feature_names
from cosmu.config.settings import Settings
from cosmu.data.altdata import AltDataPoint, AltDataStore, StoreBackedAltProvider
from cosmu.data.market import Bar
from cosmu.data.providers.store import _STORE_PROVIDER_OF
from cosmu.knowledge.store import Store
from cosmu.research.social_signal_cohort import (
    _SOCIAL_METRICS,
    _SPECS,
    load_specs,
    run_cohort,
)

# The seven LunarCrush coin time-series fields the bulk hoard (scripts/lunarcrush_max_extract.py) writes.
_SEVEN = (
    "social_volume", "social_sentiment", "galaxy_score",
    "alt_rank", "market_cap_usd", "volume_24h_usd", "price_usd",
)
_T0 = datetime(2025, 1, 1, tzinfo=UTC)


def _store() -> Store:
    tmp = tempfile.mkdtemp(prefix="cosmu-social-test-")
    return Store(Settings(database_url=f"sqlite:///{tmp}/t.sqlite3", openrouter_api_key=None))


def _points(n: int, base: float, *, available_lag_days: int = 1) -> list[AltDataPoint]:
    """n daily points; available_at = ts + lag (next-day social bucket — point-in-time, no look-ahead)."""
    return [
        AltDataPoint(
            ts=_T0 + timedelta(days=i),
            available_at=_T0 + timedelta(days=i + available_lag_days),
            value=base + i,
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# (1)+(3) routing + round-trip for all seven metrics
# ---------------------------------------------------------------------------

def test_all_seven_lunarcrush_metrics_route_to_lunarcrush():
    for m in _SEVEN:
        assert _STORE_PROVIDER_OF.get(m) == "lunarcrush", f"{m} not routed to lunarcrush"


def test_four_new_metrics_are_registered_and_routed():
    new = ("alt_rank", "market_cap_usd", "volume_24h_usd", "price_usd")
    names = feature_names()
    for m in new:
        assert m in names, f"{m} missing from feature_registry"
        assert _STORE_PROVIDER_OF[m] == "lunarcrush"


def test_seven_metrics_roundtrip_store_to_read_point_in_time(tmp_path):
    """Each metric written under the coin id round-trips through StoreBackedAltProvider read by the pair, and the
    as-of revision trail is preserved in availability order (the gate's per-bar join does the PIT selection)."""
    store = AltDataStore(tmp_path / "alt")
    for i, m in enumerate(_SEVEN):
        store.append("lunarcrush", "BTC", m, _points(5, base=float(i * 1000)))

    prov = StoreBackedAltProvider(store)
    for i, m in enumerate(_SEVEN):
        pts = prov.fetch_series("BTCUSDT", m, limit=100)  # backtest keys by the pair; hoard keyed by the coin
        assert len(pts) == 5, f"{m} did not round-trip"
        assert [p.value for p in pts] == [float(i * 1000) + j for j in range(5)]
        # point-in-time: every point's available_at is strictly after its ts (next-day social bucket)
        assert all(p.available_at > p.ts for p in pts)
        # full revision trail comes back ordered by availability (read_all contract)
        assert pts == sorted(pts, key=lambda p: (p.available_at, p.ts))


def test_symbol_key_fallback_only_fires_when_exact_key_is_empty(tmp_path):
    """An EXACT pair key always wins; the coin-form fallback only fires when the exact key found nothing —
    so a series legitimately stored under the pair is never silently re-routed to the coin form."""
    store = AltDataStore(tmp_path / "alt")
    # social_volume under BOTH forms with DIFFERENT values; alt_rank ONLY under the coin form.
    store.append("lunarcrush", "BTCUSDT", "social_volume", _points(3, base=10.0))
    store.append("lunarcrush", "BTC", "social_volume", _points(3, base=999.0))
    store.append("lunarcrush", "BTC", "alt_rank", _points(3, base=5.0))

    prov = StoreBackedAltProvider(store)
    exact = prov.fetch_series("BTCUSDT", "social_volume", limit=100)
    assert [p.value for p in exact] == [10.0, 11.0, 12.0], "exact pair key must win over the coin fallback"
    fell_back = prov.fetch_series("BTCUSDT", "alt_rank", limit=100)
    assert [p.value for p in fell_back] == [5.0, 6.0, 7.0], "coin-form fallback must serve the hoarded data"


def test_missing_metric_is_honest_empty_not_fabricated(tmp_path):
    store = AltDataStore(tmp_path / "alt")
    prov = StoreBackedAltProvider(store)
    assert prov.fetch_series("ETHUSDT", "alt_rank", limit=100) == []  # no data -> honest absence


# ---------------------------------------------------------------------------
# (4)+(5)+(6) the cohort runs end-to-end and emits a Gate verdict, offline
# ---------------------------------------------------------------------------

def _bars(prices: list[float], *, seed: float = 0.0) -> list[Bar]:
    out: list[Bar] = []
    for i, p in enumerate(prices):
        d = Decimal(str(round(p + seed, 4)))
        out.append(Bar(ts=_T0 + timedelta(days=i), open=d, high=d, low=d, close=d, volume=Decimal("1000000")))
    return out


def _universe_bars() -> dict[str, list[Bar]]:
    rates = (1.012, 1.004, 0.996, 1.008, 1.0)
    syms = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")
    return {s: _bars([100.0 * (r ** i) for i in range(120)], seed=j) for j, (s, r) in enumerate(zip(syms, rates, strict=True))}


class _SyntheticSocial:
    """Deterministic social provider keyed by the BACKTEST symbol (BTCUSDT). Emits all seven metrics with the
    same next-day availability the real LunarCrush hoard carries — so the cohort's PIT as-of join behaves
    exactly as it would on the real data. CI-only fixture (no network, no key)."""

    def __init__(self, bars: dict[str, list[Bar]]) -> None:
        self._bars = bars

    def fetch_series(self, symbol: str, metric: str, *, limit: int):  # noqa: ANN201
        bars = self._bars.get(symbol)
        if bars is None or metric not in _SOCIAL_METRICS:
            return []
        out = []
        for i, b in enumerate(bars):
            # social_volume oscillates so accel/threshold conditions can both fire and clear; others are level-ish.
            base = {
                "social_volume": 1000.0 + (i % 7) * 500.0,
                "social_sentiment": 55.0 + (i % 5),
                "galaxy_score": 60.0 + (i % 11),
                "alt_rank": 200.0 - (i % 13) * 10.0,
                "market_cap_usd": 1e9 + i * 1e6,
                "volume_24h_usd": 5e7 + (i % 9) * 1e6,
                "price_usd": float(b.close),
            }[metric]
            out.append(AltDataPoint(ts=b.ts, available_at=b.ts + timedelta(days=1), value=base))
        return out[-limit:]


class _EmptySocial:
    def fetch_series(self, symbol: str, metric: str, *, limit: int):  # noqa: ANN201
        return []


def test_specs_load_and_compile():
    specs = load_specs()
    assert [f for f, _ in specs] == _SPECS
    # the newly-authored alt_rank spec is part of the cohort family and references the newly-wired metric
    by = {f: s for f, s in specs}
    alt_spec = by["alt-rank-improvement-long.json"]
    assert alt_spec.direction == 1  # spot-only -> long-only
    used = {c.feature.name for c in [*alt_spec.entry, *alt_spec.exit.signal_exits]}
    assert "alt_rank" in used


def test_cohort_runs_all_specs_and_emits_a_verdict():
    market = _universe_bars()
    provider = _SyntheticSocial(market)
    report = run_cohort(load_specs(), market, provider, _store(), data_source="synthetic")
    assert report.verdict in {"PASS", "FAIL", "INSUFFICIENT-DATA"}
    if report.verdict != "INSUFFICIENT-DATA":
        assert {a.name for a in report.specs} == {f.replace(".json", "") for f in _SPECS}
        for a in report.specs:
            if a.gross_return > 0:
                assert a.cost_ratio <= 1.0001  # net <= gross on a profitable arm (display artifact otherwise)
            assert isinstance(a.survived_fdr, bool)
            assert 0.0 <= a.deflated_sharpe_prob <= 1.0
            assert 0.0 <= a.cscv_pbo <= 1.0


def test_empty_social_is_insufficient_data_not_a_pass():
    report = run_cohort(load_specs(), _universe_bars(), _EmptySocial(), _store(), data_source="synthetic")
    assert report.verdict == "INSUFFICIENT-DATA"
    assert "social" in report.headline.lower()


def test_cohort_is_deterministic():
    market = _universe_bars()
    r1 = run_cohort(load_specs(), market, _SyntheticSocial(market), _store(), data_source="syn")
    r2 = run_cohort(load_specs(), market, _SyntheticSocial(market), _store(), data_source="syn")
    assert r1.verdict == r2.verdict
    assert [(a.name, a.net_return, a.num_trades, a.promoted) for a in r1.specs] == \
           [(a.name, a.net_return, a.num_trades, a.promoted) for a in r2.specs]
