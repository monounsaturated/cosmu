# intent: verify OkxFundingRateProvider and KrakenFuturesFundingRateProvider parse their
# respective API responses correctly, using canned _fetchers so no network is required.

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cosmu.data.altdata import KrakenFuturesFundingRateProvider, OkxFundingRateProvider
from cosmu.ingest.run import KRAKEN_FUTURES_UNIVERSE, OKX_PERP_UNIVERSE


def _make_row(funding_time_ms: int, realized_rate: str) -> dict:
    return {"fundingTime": str(funding_time_ms), "realizedRate": realized_rate, "instId": "BTC-USDT-SWAP"}


# Three funding events at OKX 8-hour cadence within the last 7 days — ensures they survive the
# start_ms filter in fetch_series (which defaults to `now - (limit/3 + 2)` days).
import time as _time
_NOW_MS = int(_time.time() * 1000)
_FT3 = _NOW_MS - 8 * 3600 * 1000        # 8 h ago
_FT2 = _NOW_MS - 16 * 3600 * 1000       # 16 h ago
_FT1 = _NOW_MS - 24 * 3600 * 1000       # 24 h ago

_CANNED = [
    _make_row(_FT3, "0.0001500"),
    _make_row(_FT2, "0.0000800"),
    _make_row(_FT1, "-0.0000200"),
]


def test_fetch_series_parses_canned_response() -> None:
    """Provider converts OKX JSON rows into correct AltDataPoints (ts, available_at, value)."""
    pages = [_CANNED, []]  # one page of 3 rows, then empty = done

    def fetcher(url: str) -> list:  # noqa: ARG001
        return pages.pop(0) if pages else []

    provider = OkxFundingRateProvider(_fetcher=fetcher)
    pts = provider.fetch_series("BTC-USDT-SWAP", "funding_rate", limit=100)

    assert len(pts) == 3
    # Ascending order by ts
    assert pts[0].ts < pts[1].ts < pts[2].ts
    # Values parsed correctly
    assert abs(pts[0].value - (-0.00002)) < 1e-10
    assert abs(pts[1].value - 0.00008) < 1e-10
    assert abs(pts[2].value - 0.00015) < 1e-10
    # available_at == ts (no publication lag for funding rate — it IS the observation)
    for p in pts:
        assert p.available_at == p.ts


def test_fetch_series_ignores_unknown_metric() -> None:
    provider = OkxFundingRateProvider(_fetcher=lambda url: _CANNED)
    assert provider.fetch_series("BTC-USDT-SWAP", "open_interest", limit=10) == []


def test_fetch_series_returns_empty_on_network_error() -> None:
    def bad_fetcher(url: str) -> list:  # noqa: ARG001
        raise ConnectionError("network down")

    provider = OkxFundingRateProvider(_fetcher=bad_fetcher)
    # Should not raise — graceful degradation
    pts = provider.fetch_series("BTC-USDT-SWAP", "funding_rate", limit=10)
    assert pts == []


def test_fetch_history_deduplicates_rows() -> None:
    """Duplicate fundingTime entries (overlapping pages) are collapsed to one point."""
    dup_page = [_make_row(_FT1, "0.0001"), _make_row(_FT1, "0.0001")]
    pages = [dup_page, []]

    def fetcher(url: str) -> list:  # noqa: ARG001
        return pages.pop(0) if pages else []

    provider = OkxFundingRateProvider(_fetcher=fetcher)
    # start_ms=0 means collect everything; timestamps are recent so they won't be filtered
    pts = provider.fetch_history("BTC-USDT-SWAP", start_ms=0)
    assert len(pts) == 1


def test_okx_perp_universe_has_20_assets() -> None:
    """Universe constant must contain exactly 20 OKX SWAP symbols for the dispersion strategy."""
    assert len(OKX_PERP_UNIVERSE) == 20
    for sym in OKX_PERP_UNIVERSE:
        assert sym.endswith("-USDT-SWAP"), f"bad symbol format: {sym}"


def test_okx_perp_universe_in_catalog() -> None:
    """Every symbol in OKX_PERP_UNIVERSE must have an Instrument entry in the venue catalog."""
    from cosmu.spine.venue import default_catalog

    cat = default_catalog()
    okx_symbols = {i.symbol for i in cat.instruments if i.venue_id == "okx"}
    for sym in OKX_PERP_UNIVERSE:
        assert sym in okx_symbols, f"{sym} missing from okx catalog instruments"


# ---------------------------------------------------------------------------
# Kraken Futures funding rate provider tests
# ---------------------------------------------------------------------------

def _make_kf_row(ts_ms: int, rate: str) -> dict:
    return {"timestamp": ts_ms, "fundingRate": rate, "symbol": "PF_XBTUSD"}


_KF_NOW_MS = _NOW_MS - 3600 * 1000       # 1 h ago
_KF_ROWS = [
    _make_kf_row(_NOW_MS - 7200 * 1000, "-0.0002"),
    _make_kf_row(_NOW_MS - 3600 * 1000, "0.0001"),
    _make_kf_row(_NOW_MS,               "0.0003"),
]


def test_kraken_futures_fetch_series_parses_canned() -> None:
    """KrakenFuturesFundingRateProvider converts JSON rows into correct AltDataPoints."""
    calls: list[str] = []

    def fetcher(url: str) -> list:
        calls.append(url)
        return _KF_ROWS

    provider = KrakenFuturesFundingRateProvider(_fetcher=fetcher)
    pts = provider.fetch_series("PF_XBTUSD", "funding_rate", limit=100)

    assert len(pts) == 3
    assert pts[0].ts < pts[1].ts < pts[2].ts
    assert abs(pts[0].value - (-0.0002)) < 1e-10
    assert abs(pts[1].value - 0.0001) < 1e-10
    assert abs(pts[2].value - 0.0003) < 1e-10
    for p in pts:
        assert p.available_at == p.ts
    assert "PF_XBTUSD" in calls[0]


def test_kraken_futures_ignores_unknown_metric() -> None:
    provider = KrakenFuturesFundingRateProvider(_fetcher=lambda url: _KF_ROWS)
    assert provider.fetch_series("PF_XBTUSD", "open_interest", limit=10) == []


def test_kraken_futures_graceful_on_network_error() -> None:
    def bad(url: str) -> list:  # noqa: ARG001
        raise ConnectionError("network down")

    provider = KrakenFuturesFundingRateProvider(_fetcher=bad)
    pts = provider.fetch_series("PF_XBTUSD", "funding_rate", limit=10)
    assert pts == []


def test_kraken_futures_universe_in_catalog() -> None:
    """Every symbol in KRAKEN_FUTURES_UNIVERSE must have an Instrument in the catalog."""
    from cosmu.spine.venue import default_catalog

    cat = default_catalog()
    kf_symbols = {i.symbol for i in cat.instruments if i.venue_id == "kraken_futures"}
    for sym in KRAKEN_FUTURES_UNIVERSE:
        assert sym in kf_symbols, f"{sym} missing from kraken_futures catalog instruments"
