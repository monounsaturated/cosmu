"""DeribitDvolProvider — offline tests with a canned volatility_index_data fixture (no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.data.altdata import AltDataStore, DeribitDvolProvider, _points_from_deribit_dvol

_T0 = datetime(2024, 1, 1, tzinfo=UTC)

# Deribit get_volatility_index_data: [ts_ms, open, high, low, close]
FIXTURE = {
    "result": {
        "data": [
            [int(_T0.timestamp()) * 1000, 60.0, 65.0, 58.0, 62.0],
            [int((_T0 + timedelta(days=1)).timestamp()) * 1000, 62.0, 68.0, 61.0, 65.5],
            [int((_T0 + timedelta(days=2)).timestamp()) * 1000, 65.5, 70.0, 64.0, 67.2],
        ]
    }
}


def _provider() -> DeribitDvolProvider:
    return DeribitDvolProvider(_fetcher=lambda url: FIXTURE)


def test_parse_dvol_close_and_ascending_order():
    pts = _points_from_deribit_dvol(FIXTURE, limit=1000)
    assert len(pts) == 3
    assert pts[0].ts == _T0
    assert pts[0].value == 62.0   # close column
    assert pts[1].value == 65.5
    assert pts[2].value == 67.2
    assert [p.ts for p in pts] == sorted(p.ts for p in pts)


def test_point_in_time_is_next_day():
    """Daily bar opens at midnight UTC; finalized at day-end → available_at = ts + 1 day (no look-ahead)."""
    pts = _points_from_deribit_dvol(FIXTURE, limit=1000)
    for pt in pts:
        assert pt.available_at == pt.ts + timedelta(days=1)
        assert pt.available_at > pt.ts  # never look-ahead


def test_wrong_metric_returns_empty():
    p = _provider()
    assert p.fetch_series("BTCUSDT", "not_dvol", limit=10) == []


def test_unknown_symbol_returns_empty():
    p = _provider()
    # Deribit DVOL only exists for BTC and ETH
    assert p.fetch_series("SOLUSDT", "dvol", limit=10) == []
    assert p.fetch_series("DOGEUSDT", "dvol", limit=10) == []


def test_btc_and_eth_are_supported():
    """Both BTC and ETH map to valid Deribit currency codes."""
    p = _provider()
    assert p.fetch_series("BTCUSDT", "dvol", limit=10) != []
    assert p.fetch_series("ETHUSDT", "dvol", limit=10) != []


def test_respects_limit():
    pts = _points_from_deribit_dvol(FIXTURE, limit=2)
    assert len(pts) == 2
    assert pts[-1].ts == _T0 + timedelta(days=2)


def test_fetch_failure_returns_empty():
    def bad_fetcher(url: str) -> dict:
        raise RuntimeError("network dead")

    p = DeribitDvolProvider(_fetcher=bad_fetcher)
    # must not raise — one dead source never aborts the run
    assert p.fetch_series("BTCUSDT", "dvol", limit=10) == []


def test_zero_close_is_dropped():
    bad_fixture = {
        "result": {
            "data": [
                [int(_T0.timestamp()) * 1000, 60.0, 65.0, 58.0, 0.0],          # zero close → drop
                [int((_T0 + timedelta(days=1)).timestamp()) * 1000, 62.0, 68.0, 61.0, 65.5],
            ]
        }
    }
    pts = _points_from_deribit_dvol(bad_fixture, limit=1000)
    assert len(pts) == 1
    assert pts[0].value == 65.5


def test_short_row_is_dropped():
    bad_fixture = {"result": {"data": [[int(_T0.timestamp()) * 1000, 60.0]]}}  # only 2 cols, needs 5
    pts = _points_from_deribit_dvol(bad_fixture, limit=1000)
    assert pts == []


def test_ingest_dvol_per_symbol(tmp_path):
    from cosmu.ingest.pipeline import ingest_numeric

    store = AltDataStore(tmp_path / "alt")
    p = _provider()
    count = ingest_numeric(store, p, ["BTCUSDT", "ETHUSDT"], "dvol", provider_name="deribit")
    assert count == 6  # 3 points × 2 symbols
    assert len(store.read_all("deribit", "BTCUSDT", "dvol")) == 3
    assert len(store.read_all("deribit", "ETHUSDT", "dvol")) == 3
    # market-wide key is not used — dvol is per-symbol
    assert store.read_all("deribit", "MARKET", "dvol") == []
