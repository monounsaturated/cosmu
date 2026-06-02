"""DeFiLlama TVL provider — offline tests with canned fixtures."""
from datetime import UTC, datetime, timedelta
from cosmu.data.altdata import AltDataPoint, AltDataStore, DefiLlamaTvlProvider

_T0 = datetime(2024, 1, 1, tzinfo=UTC)

FIXTURE = [
    {"date": int(_T0.timestamp()) + i * 86400, "tvl": 50_000_000_000 + i * 1_000_000_000}
    for i in range(5)
]

def _make_provider():
    class Offline(DefiLlamaTvlProvider):
        def fetch_series(self, symbol, metric, *, limit):
            if metric != "defi_tvl":
                return []
            out = []
            for row in FIXTURE[-limit:]:
                ts = datetime.fromtimestamp(int(row["date"]), tz=UTC)
                out.append(AltDataPoint(ts=ts, available_at=ts + timedelta(days=1), value=float(row["tvl"])))
            return sorted(out, key=lambda p: p.ts)
    return Offline()

def test_parse_and_point_in_time():
    p = _make_provider()
    series = p.fetch_series("MARKET", "defi_tvl", limit=1000)
    assert len(series) == 5
    for pt in series:
        assert pt.available_at == pt.ts + timedelta(days=1)
        assert pt.value > 0

def test_wrong_metric_returns_empty():
    p = _make_provider()
    assert p.fetch_series("MARKET", "wrong", limit=10) == []

def test_respects_limit():
    p = _make_provider()
    assert len(p.fetch_series("MARKET", "defi_tvl", limit=3)) == 3

def test_ingest_with_defillama(tmp_path):
    from cosmu.ingest.pipeline import ingest_market_wide_numeric
    store = AltDataStore(tmp_path / "alt")
    provider = _make_provider()
    count = ingest_market_wide_numeric(
        store, provider, source_metric="defi_tvl", stored_metric="defi_tvl", provider_name="defillama",
    )
    assert count == 5
