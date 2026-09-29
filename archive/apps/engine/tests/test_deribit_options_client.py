"""deribit_client.py — offline parse of the JSON-RPC envelopes from the four public endpoints; failures degrade."""

from __future__ import annotations

from cosmu.options.deribit_client import DeribitClient


def _fetcher(routes: dict):
    """Return a _fetcher that matches a URL by substring → canned payload (or raises for a 'dead' route)."""
    def fetch(url: str) -> dict:
        for needle, payload in routes.items():
            if needle in url:
                if isinstance(payload, Exception):
                    raise payload
                return payload
        return {}
    return fetch


def test_index_price():
    c = DeribitClient(_fetcher=_fetcher({"get_index_price": {"result": {"index_price": 60150.5}}}))
    assert c.index_price("BTC") == 60150.5
    assert c.index_price("DOGE") is None  # no index name mapped


def test_index_price_rejects_nonpositive():
    c = DeribitClient(_fetcher=_fetcher({"get_index_price": {"result": {"index_price": 0}}}))
    assert c.index_price("BTC") is None


def test_dvol_rows():
    payload = {"result": {"data": [[1782000000000, 39.85, 41.76, 39.05, 41.76],
                                    [1782086400000, 41.76, 41.76, 39.41, 40.41]]}}
    c = DeribitClient(_fetcher=_fetcher({"get_volatility_index_data": payload}))
    rows = c.dvol("BTC", start_ms=1, end_ms=2)
    assert len(rows) == 2 and rows[-1][4] == 40.41


def test_book_summary_filters_non_dicts():
    payload = {"result": [{"instrument_name": "BTC-3JUL26-60000-C", "bid_price": 0.05}, "junk", 42]}
    c = DeribitClient(_fetcher=_fetcher({"get_book_summary_by_currency": payload}))
    rows = c.book_summary("BTC")
    assert len(rows) == 1 and rows[0]["instrument_name"] == "BTC-3JUL26-60000-C"


def test_order_book():
    payload = {"result": {"bids": [[0.05, 10.0]], "asks": [[0.06, 8.0]], "best_bid_amount": 10.0,
                          "greeks": {"delta": 0.5}}}
    c = DeribitClient(_fetcher=_fetcher({"get_order_book": payload}))
    ob = c.order_book("BTC-3JUL26-60000-C")
    assert ob["bids"] == [[0.05, 10.0]] and ob["greeks"]["delta"] == 0.5


def test_dead_fetch_degrades_to_empty():
    c = DeribitClient(_fetcher=_fetcher({"get_index_price": RuntimeError("network dead")}))
    assert c.index_price("BTC") is None  # one dead call never raises
    assert c.book_summary("BTC") == []   # unmatched route → {} → []
    assert c.order_book("X") == {}
