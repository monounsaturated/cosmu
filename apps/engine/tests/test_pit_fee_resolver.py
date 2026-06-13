# The Gate's _simulate read the PIT taker fee from the store ONCE PER BAR (gate.py _pit_fee → read_pit_fee →
# read_asof → a fresh DB connection every call). Across the cross-asset ablation that opened thousands of
# connections and HUNG the engine suite under parallel I/O. read_pit_fee_resolver reads the fee series ONCE and
# resolves each bar's as_of in memory. These tests pin it as PIT-IDENTICAL to per-as_of read_pit_fee (the gate's
# cost model must not change by a single bp), including across a mid-window vendor revision, and prove _simulate
# no longer opens a connection per bar.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.config.settings import Settings
from cosmu.data.altdata import read_pit_fee, read_pit_fee_resolver
from cosmu.data.providers._types import AltDataPoint
from cosmu.data.providers.store import PgAltDataStore
from cosmu.knowledge.store import Store

_VENUE, _SYMBOL, _METRIC = "binance", "BTCUSDT", "venue_fees_taker"
_FB = 7.5  # arbitrary fallback bps


def _store(tmp_path) -> Store:
    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/fee.sqlite3", openrouter_api_key=None))
    store.migrate()
    return store


def _append(store: Store, points: list[AltDataPoint]) -> None:
    PgAltDataStore(store).append("venue_fees", f"{_VENUE}:{_SYMBOL}", _METRIC, points)


def test_resolver_is_byte_identical_to_per_asof_read_pit_fee_across_a_revision(tmp_path):
    store = _store(tmp_path)
    jan, feb, mar = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC)
    _append(store, [
        AltDataPoint(ts=jan, available_at=jan, value=10.0),
        AltDataPoint(ts=feb, available_at=feb, value=12.0),
        AltDataPoint(ts=feb, available_at=mar, value=9.0),   # REVISION of the Feb observation, learned in Mar
    ])
    resolve = read_pit_fee_resolver(store, _VENUE, _SYMBOL, _METRIC, fallback_bps=_FB)
    # Walk a year of daily as_of values: the resolver must match read_pit_fee EXACTLY at every one — before any
    # data (fallback), at each release, and across the revision boundary (Feb value 12 -> revised 9 after Mar 1).
    for d in range(-5, 90):
        as_of = jan + timedelta(days=d)
        assert resolve(as_of) == read_pit_fee(store, _VENUE, _SYMBOL, _METRIC, as_of, fallback_bps=_FB), f"day {d}"
    # Spot-check the revision is actually exercised (not all-fallback): pre-Mar Feb fee is 12, post-Mar it's 9.
    assert resolve(feb + timedelta(days=10)) == 12.0
    assert resolve(mar + timedelta(days=10)) == 9.0


def test_resolver_empty_series_returns_fallback_for_every_asof(tmp_path):
    store = _store(tmp_path)  # no venue_fees rows
    resolve = read_pit_fee_resolver(store, _VENUE, _SYMBOL, _METRIC, fallback_bps=_FB)
    for d in range(0, 30):
        as_of = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=d)
        assert resolve(as_of) == _FB == read_pit_fee(store, _VENUE, _SYMBOL, _METRIC, as_of, fallback_bps=_FB)


def test_gate_simulate_no_longer_opens_a_connection_per_bar(tmp_path):
    """REGRESSION: _simulate must read the fee series ONCE, not once per bar. We count Store._open calls across
    a 400-bar simulation and assert it's O(1), not O(bars) — the actual fix for the suite hang."""
    from decimal import Decimal

    from cosmu.data.market import Bar
    from cosmu.research import gate as gate_mod

    store = _store(tmp_path)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    bars = [Bar(ts=base + timedelta(days=i), open=Decimal("100"), high=Decimal("101"),
                low=Decimal("99"), close=Decimal("100"), volume=Decimal("1000")) for i in range(400)]
    signal = [i % 5 == 0 for i in range(400)]

    opens = {"n": 0}
    original_open = Store._open

    def counting_open(self, *a, **k):
        opens["n"] += 1
        return original_open(self, *a, **k)

    Store._open = counting_open
    try:
        gate_mod._simulate(bars, signal, gate_mod.SignalParams(14, 1.0, 5),
                           store=store, venue_id=_VENUE, symbol=_SYMBOL)
    finally:
        Store._open = original_open
    # One read_all for the fee series (+ a small constant for any other reads) — NOT ~400 (one per bar).
    assert opens["n"] <= 5, f"expected O(1) store opens, got {opens['n']}"
