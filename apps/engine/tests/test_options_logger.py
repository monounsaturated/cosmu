"""logger.py + sink.py — the forward-only poll: PIT capture stamp, order-book enrichment of the long tail,
append-only JSONL (never overwritten), long-tail selection."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from cosmu.options.logger import DeribitOptionsLogger, select_long_tail
from cosmu.options.sink import LocalJsonlSink

_NOW = datetime(2026, 6, 29, 12, 0, tzinfo=UTC)


class _FakeClient:
    """Canned Deribit client: a 3-instrument BTC chain with distinct open interest (to test long-tail selection),
    one of which carries an order book (the enriched one)."""

    def index_price(self, currency: str):
        return 60000.0

    def dvol(self, currency: str, *, start_ms: int, end_ms: int, resolution: int = 86400):
        return [[start_ms, 40.0, 41.0, 39.0, 42.5]]

    def book_summary(self, currency: str):
        return [
            {"instrument_name": "BTC-3JUL26-60000-C", "bid_price": 0.05, "ask_price": 0.06, "mark_iv": 44.0,
             "open_interest": 500.0, "underlying_price": 60100.0},  # high OI → NOT in the long tail
            {"instrument_name": "BTC-3JUL26-80000-C", "bid_price": 0.001, "ask_price": 0.002, "mark_iv": 70.0,
             "open_interest": 2.0, "underlying_price": 60100.0},     # low OI → long tail (enriched first)
            {"instrument_name": "BTC-3JUL26-40000-P", "bid_price": 0.001, "ask_price": 0.0015, "mark_iv": 80.0,
             "open_interest": 5.0, "underlying_price": 60100.0},
        ]

    def order_book(self, instrument: str, *, depth: int = 5):
        return {"best_bid_amount": 12.0, "best_ask_amount": 7.0,
                "greeks": {"delta": 0.1, "gamma": 0.0, "vega": 1.0, "theta": -1.0, "rho": 0.0},
                "bids": [[0.001, 12.0]], "asks": [[0.002, 7.0]]}


def test_select_long_tail_picks_lowest_oi():
    from cosmu.options.chain import parse_book_summary
    quotes = parse_book_summary(_FakeClient().book_summary("BTC"), currency="BTC")
    picked = select_long_tail(quotes, 1)
    assert picked == ["BTC-3JUL26-80000-C"]  # OI=2 is the smallest


def test_poll_stamps_pit_capture_and_enriches_long_tail(tmp_path):
    sink = LocalJsonlSink(tmp_path)
    logger = DeribitOptionsLogger(_FakeClient(), sink, currencies=("BTC",), max_books_per_currency=1,
                                  clock=lambda: _NOW)
    results = logger.poll_once()
    assert len(results) == 1
    r = results[0]
    assert r.snapshot.capture_ts == _NOW           # PIT: WE stamp the time, not Deribit
    assert r.snapshot.index_price == 60000.0
    assert r.snapshot.dvol == 42.5                 # last DVOL close
    assert r.n_quotes == 3 and r.n_enriched == 1   # only the long-tail instrument got an order book
    assert r.n_written == 3
    enriched = [q for q in r.snapshot.quotes if q.bid_size is not None]
    assert len(enriched) == 1 and enriched[0].instrument == "BTC-3JUL26-80000-C"
    assert enriched[0].greeks["delta"] == 0.1


def test_sink_is_append_only(tmp_path):
    sink = LocalJsonlSink(tmp_path)
    logger = DeribitOptionsLogger(_FakeClient(), sink, currencies=("BTC",), max_books_per_currency=1,
                                  clock=lambda: _NOW)
    logger.poll_once()
    logger.poll_once()  # a second poll APPENDS, never overwrites
    path = sink.path_for("BTC", "2026-06-29")
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 6  # 3 rows × 2 polls
    row = json.loads(lines[0])
    assert row["capture_ts"].startswith("2026-06-29T12:00") and row["currency"] == "BTC"
    assert row["strike"] == 40000.0 and row["option_type"] == "P"  # rows are sorted by (expiry, strike)


def test_no_sink_dry_poll_writes_nothing(tmp_path):
    logger = DeribitOptionsLogger(_FakeClient(), None, currencies=("BTC",), clock=lambda: _NOW)
    r = logger.poll_once()[0]
    assert r.n_written == 0 and r.n_quotes == 3  # parse-only smoke
