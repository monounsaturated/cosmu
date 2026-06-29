# Event-monitor tests: offline (injected Gamma `_fetcher`, network blocked by conftest), forward-hoarding into a
# tmp JSONL AltDataStore. Proves the watchlist match, polarity inference, the PIT stamp, append-only idempotency,
# and cross-poll move detection.

from __future__ import annotations

from datetime import UTC, datetime

from cosmu.correlate.monitor import (
    MONITOR_METRIC,
    MONITOR_PROVIDER,
    PolymarketEventMonitor,
)
from cosmu.data.altdata import AltDataStore

_T1 = datetime(2026, 6, 28, 12, tzinfo=UTC)
_T2 = datetime(2026, 6, 29, 12, tzinfo=UTC)


def _markets(hormuz_yes: float) -> list[dict]:
    """A canned Gamma `/markets` payload: a Hormuz market (watched, oil), an NBA market (NOT on the watchlist),
    a Solana-ETF market (watched, crypto), and a thin market with no readable price."""
    return [
        {
            "id": "1", "conditionId": "0xhormuz",
            "question": "Will the Strait of Hormuz close before August 2026?",
            "outcomes": '["Yes","No"]',
            "outcomePrices": f'["{hormuz_yes}","{round(1 - hormuz_yes, 4)}"]',
            "active": True, "closed": False,
        },
        {
            "id": "2", "conditionId": "0xnba", "question": "Will the Lakers win the title?",
            "outcomes": '["Yes","No"]', "outcomePrices": '["0.20","0.80"]',
            "active": True, "closed": False,
        },
        {
            "id": "3", "conditionId": "0xsol",
            "question": "Will the SEC approve a Solana ETF before December 2026?",
            "outcomes": '["Yes","No"]', "outcomePrices": '["0.45","0.55"]',
            "active": True, "closed": False,
        },
        {
            "id": "4", "conditionId": "0xthin", "question": "Will oil cross $100 before July?",
            "active": True, "closed": False,  # no prices / lastTradePrice → unreadable → skipped
        },
    ]


def _fetcher_at(hormuz_yes: float):
    def f(url: str):
        if "/markets?" in url:
            return _markets(hormuz_yes)
        return []  # the per-tag /events scans return nothing in the test
    return f


def test_scan_matches_watchlist_and_infers_polarity() -> None:
    mon = PolymarketEventMonitor(_fetcher=_fetcher_at(0.30))
    obs = mon.scan(as_of=_T1)
    # NBA (no event type) + thin (no price) are filtered; Hormuz + Solana remain.
    assert [o.event_type for o in obs] == ["middle_east_oil", "crypto_etf_regulation"]
    hormuz, sol = obs
    assert hormuz.condition_id == "0xhormuz"
    assert hormuz.yes_prob == 0.30
    assert hormuz.polarity == 1  # "close" → risk RISING
    # the live snapshot is knowable exactly when polled.
    assert hormuz.ts == _T1 and hormuz.available_at == _T1
    assert sol.event_type == "crypto_etf_regulation" and sol.yes_prob == 0.45 and sol.polarity == 1


def test_poll_and_hoard_is_append_only_idempotent(tmp_path) -> None:
    store = AltDataStore(tmp_path)
    mon = PolymarketEventMonitor(_fetcher=_fetcher_at(0.30))
    res1 = mon.poll_and_hoard(store, as_of=_T1)
    assert res1.written == 2          # hormuz + sol hoarded (nba/thin filtered out)
    assert res1.moves == []           # one point each → no move yet
    # Re-poll at the SAME instant → append_dedup makes it a no-op.
    assert mon.poll_and_hoard(store, as_of=_T1).written == 0
    # The hoarded point carries the PIT stamp (available_at == ts == poll time).
    pts = store.read_all(MONITOR_PROVIDER, "0xhormuz", MONITOR_METRIC)
    assert len(pts) == 1 and pts[0].ts == _T1 and pts[0].available_at == _T1 and pts[0].value == 0.30


def test_cross_poll_move_is_detected(tmp_path) -> None:
    store = AltDataStore(tmp_path)
    PolymarketEventMonitor(_fetcher=_fetcher_at(0.30)).poll_and_hoard(store, as_of=_T1)
    # Second poll: Hormuz odds jumped 0.30 → 0.45 (a 15pp catalyst); Solana unchanged at 0.45.
    res2 = PolymarketEventMonitor(_fetcher=_fetcher_at(0.45)).poll_and_hoard(store, as_of=_T2)
    assert res2.written == 2  # a new ts for each market
    assert len(res2.moves) == 1
    mv = res2.moves[0]
    assert mv.observation.event_type == "middle_east_oil"
    assert abs(mv.move.delta - 0.15) < 1e-9
    assert mv.move.prev_prob == 0.30 and mv.move.prob == 0.45


def test_subthreshold_move_is_not_flagged(tmp_path) -> None:
    store = AltDataStore(tmp_path)
    PolymarketEventMonitor(_fetcher=_fetcher_at(0.30)).poll_and_hoard(store, as_of=_T1)
    # A 2pp drift (0.30 → 0.32) is below the 5pp default → not a flagged move.
    res2 = PolymarketEventMonitor(_fetcher=_fetcher_at(0.32)).poll_and_hoard(store, as_of=_T2)
    assert all(m.observation.condition_id != "0xhormuz" for m in res2.moves)


def test_dead_fetch_never_aborts() -> None:
    def _boom(url: str):
        raise RuntimeError("network down")

    # Every discovery path raises → scan returns nothing, never propagates the error.
    assert PolymarketEventMonitor(_fetcher=_boom).scan(as_of=_T1) == []
