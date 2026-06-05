# intent: prove the bar backfiller fetches WITHOUT ccxt via the keyless Binance REST fallback, so
# `manage_data backfill bars` works on a box where ccxt isn't installed (the silent-zero trap is gone).
# Offline + deterministic: no network — the ccxt and REST seams are stubbed.

from __future__ import annotations

from cosmu.ingest.bars import CcxtBarBackfiller, _klines_to_ohlcv


def test_klines_to_ohlcv_shapes_rest_rows_like_ccxt() -> None:
    # Binance REST kline rows carry string OHLCV + extra trailing fields; only the first 6 matter.
    klines = [[1_700_000_000_000, "100.5", "101.0", "99.0", "100.0", "12.5", 1_700_000_059_999, "0"]]
    assert _klines_to_ohlcv(klines) == [[1_700_000_000_000, 100.5, 101.0, 99.0, 100.0, 12.5]]


def test_binance_falls_back_to_rest_when_ccxt_empty(monkeypatch) -> None:
    bf = CcxtBarBackfiller(exchange_id="binance")
    monkeypatch.setattr(bf, "_fetch_ccxt", lambda *a, **k: [])  # simulate no ccxt
    canned = [[1_700_000_000_000, "1", "2", "0.5", "1.5", "10", 1_700_000_059_999]]
    monkeypatch.setattr(bf, "_fetch_rest_binance", lambda *a, **k: _klines_to_ohlcv(canned))
    assert bf._fetch("BTCUSDT", "1d", 1_700_000_000_000, 720) == [[1_700_000_000_000, 1.0, 2.0, 0.5, 1.5, 10.0]]


def test_ccxt_result_short_circuits_rest(monkeypatch) -> None:
    bf = CcxtBarBackfiller(exchange_id="binance")
    monkeypatch.setattr(bf, "_fetch_ccxt", lambda *a, **k: [[1, 2.0, 3.0, 1.0, 2.5, 9.0]])
    called = {"rest": False}
    monkeypatch.setattr(bf, "_fetch_rest_binance", lambda *a, **k: called.__setitem__("rest", True) or [])
    assert bf._fetch("BTCUSDT", "1d", 0, 720) == [[1, 2.0, 3.0, 1.0, 2.5, 9.0]]
    assert called["rest"] is False  # ccxt hit → no REST call


def test_non_binance_stays_ccxt_only(monkeypatch) -> None:
    bf = CcxtBarBackfiller(exchange_id="kraken")
    monkeypatch.setattr(bf, "_fetch_ccxt", lambda *a, **k: [])
    called = {"rest": False}
    monkeypatch.setattr(bf, "_fetch_rest_binance", lambda *a, **k: called.__setitem__("rest", True) or [["x"]])
    assert bf._fetch("BTCUSDT", "1d", 0, 10) == []  # no Binance REST fallback for other venues
    assert called["rest"] is False
