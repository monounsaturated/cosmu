"""FearGreedProvider (Alternative.me) — offline tests verifying PIT stamping and market-wide ingest."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from cosmu.data.altdata import AltDataStore, FearGreedProvider

_T0 = datetime(2024, 1, 1, tzinfo=UTC)

# Alternative.me /fng/ response: `timestamp` is start-of-day Unix; `value` is the F&G score [0, 100].
FIXTURE = {
    "data": [
        {"timestamp": str(int((_T0 + timedelta(days=i)).timestamp())), "value": str(40 + i), "value_classification": "Fear"}
        for i in range(5)
    ]
}


def _provider() -> FearGreedProvider:
    class Offline(FearGreedProvider):
        def fetch_series(self, symbol, metric, *, limit):
            if metric != "fear_greed":
                return []
            from cosmu.data.altdata import AltDataPoint

            out = []
            for row in FIXTURE["data"][-limit:]:
                ts = datetime.fromtimestamp(int(row["timestamp"]), tz=UTC)
                out.append(AltDataPoint(ts=ts, available_at=ts + timedelta(days=1), value=float(row["value"])))
            return sorted(out, key=lambda p: p.ts)

    return Offline()


def test_parse_values_and_ascending_order():
    p = _provider()
    pts = p.fetch_series("MARKET", "fear_greed", limit=1000)
    assert len(pts) == 5
    assert pts[0].ts == _T0
    assert pts[0].value == 40.0
    assert pts[4].value == 44.0
    assert [pt.ts for pt in pts] == sorted(pt.ts for pt in pts)


def test_point_in_time_is_next_day():
    """The Alternative.me F&G for day T is published during day T; the conservative floor is T+1.
    This prevents using 'today's' score in any same-day backtest bar (no look-ahead)."""
    p = _provider()
    for pt in p.fetch_series("MARKET", "fear_greed", limit=1000):
        assert pt.available_at == pt.ts + timedelta(days=1)
        assert pt.available_at > pt.ts  # never look-ahead


def test_wrong_metric_returns_empty():
    p = _provider()
    assert p.fetch_series("MARKET", "not_fear_greed", limit=10) == []


def test_respects_limit():
    p = _provider()
    assert len(p.fetch_series("MARKET", "fear_greed", limit=3)) == 3


def test_ingest_fear_greed_market_wide(tmp_path):
    from cosmu.ingest.pipeline import ingest_market_wide_numeric

    store = AltDataStore(tmp_path / "alt")
    p = _provider()
    count = ingest_market_wide_numeric(
        store, p, source_metric="fear_greed", stored_metric="fear_greed", provider_name="alternative.me"
    )
    assert count == 5
    pts = store.read_all("alternative.me", "MARKET", "fear_greed")
    assert len(pts) == 5
    # PIT lag preserved in the store
    for pt in pts:
        assert pt.available_at == pt.ts + timedelta(days=1)
    # Not stored per-symbol (market-wide only)
    assert store.read_all("alternative.me", "BTCUSDT", "fear_greed") == []


def test_real_provider_parse_via_injected_fetcher():
    """Test the real FearGreedProvider._fetch path via injected urlopen mock."""
    import json

    real_fixture = json.dumps(FIXTURE).encode()
    p = FearGreedProvider()

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self):
            return real_fixture

    with patch("urllib.request.urlopen", return_value=FakeResp()):
        pts = p.fetch_series("MARKET", "fear_greed", limit=5)
    assert len(pts) == 5
    for pt in pts:
        assert pt.available_at == pt.ts + timedelta(days=1)
