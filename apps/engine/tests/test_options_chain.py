"""chain.py — instrument-name parsing, book_summary → quotes, and order-book enrichment (offline, no network)."""

from __future__ import annotations

from datetime import date

from cosmu.options.chain import (
    OptionQuote,
    enrich_with_order_book,
    parse_book_summary,
    parse_instrument,
)


def test_parse_instrument_call_and_put():
    assert parse_instrument("BTC-25DEC26-58000-C") == ("BTC", date(2026, 12, 25), 58000.0, True)
    assert parse_instrument("ETH-3JUL26-2000-P") == ("ETH", date(2026, 7, 3), 2000.0, False)


def test_parse_instrument_rejects_non_options():
    assert parse_instrument("BTC-PERPETUAL") is None
    assert parse_instrument("BTC-25DEC26") is None
    assert parse_instrument("BTC-25XXX26-58000-C") is None  # bad month
    assert parse_instrument("BTC-25DEC26-58000-X") is None  # bad type


def test_parse_book_summary_filters_and_sorts():
    rows = [
        {"instrument_name": "BTC-3JUL26-60000-C", "bid_price": 0.05, "ask_price": 0.06, "mark_price": 0.055,
         "mark_iv": 44.0, "open_interest": 10.0, "volume": 1.0, "underlying_price": 61000.0},
        {"instrument_name": "BTC-3JUL26-50000-P", "bid_price": 0.0, "ask_price": 0.02, "mark_price": 0.01,
         "mark_iv": 55.0, "open_interest": 5.0, "volume": 0.0, "underlying_price": 61000.0},
        {"instrument_name": "BTC-PERPETUAL", "bid_price": 1, "ask_price": 2},  # not an option → skipped
        {"instrument_name": "ETH-3JUL26-2000-C", "bid_price": 0.1, "ask_price": 0.2},  # wrong currency → skipped
    ]
    quotes = parse_book_summary(rows, currency="BTC")
    assert [q.instrument for q in quotes] == ["BTC-3JUL26-50000-P", "BTC-3JUL26-60000-C"]  # sorted by strike
    put = quotes[0]
    assert put.bid_price is None  # 0.0 bid → unquoted side
    assert put.ask_price == 0.02
    assert put.mid_price is None  # one-sided → no honest mid
    call = quotes[1]
    assert call.mid_price == 0.055
    assert call.spread == 0.06 - 0.05
    assert call.is_two_sided


def test_enrich_with_order_book_splices_size_greeks_l2():
    q = OptionQuote(
        instrument="BTC-3JUL26-60000-C", currency="BTC", expiry=date(2026, 7, 3), strike=60000.0, is_call=True,
        bid_price=0.05, ask_price=0.06, mark_price=0.055, mark_iv=44.0, open_interest=10.0, volume=1.0,
        underlying_price=61000.0,
    )
    book = {
        "best_bid_price": 0.051, "best_ask_price": 0.059,
        "best_bid_amount": 12.0, "best_ask_amount": 7.0,
        "greeks": {"delta": 0.55, "gamma": 0.0001, "vega": 9.0, "theta": -80.0, "rho": 0.5},
        "bids": [[0.051, 12.0], [0.050, 30.0]], "asks": [[0.059, 7.0], [0.060, 20.0]],
    }
    e = enrich_with_order_book(q, book)
    assert e.bid_size == 12.0 and e.ask_size == 7.0
    assert e.bid_price == 0.051 and e.ask_price == 0.059  # order book overrides summary top-of-book
    assert e.greeks["delta"] == 0.55
    assert e.l2_bids == ((0.051, 12.0), (0.050, 30.0))
    # original is untouched (frozen / replace returns a copy)
    assert q.bid_size is None and q.greeks is None


def test_enrich_empty_book_is_noop():
    q = OptionQuote("BTC-3JUL26-60000-C", "BTC", date(2026, 7, 3), 60000.0, True, 0.05, 0.06, 0.055, 44.0,
                    10.0, 1.0, 61000.0)
    assert enrich_with_order_book(q, {}) is q or enrich_with_order_book(q, {}).bid_size is None
