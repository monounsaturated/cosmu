# Offline tests for the standardized scrape path (data/sources/scrape_stub.py). No live scraping: agent-
# written ScrapedRecords are persisted to a fixture dir and served through the standard AltDataProvider seam.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.data.sources.scrape_stub import (
    ScrapedAltDataProvider,
    ScrapedRecord,
    stub_scrape,
    write_scraped_records,
)
from cosmu.ingest.pipeline import ingest_numeric
from cosmu.data.altdata import AltDataStore

_T0 = datetime(2024, 1, 1, tzinfo=UTC)


def _records(n: int) -> list[ScrapedRecord]:
    return [
        ScrapedRecord(
            source="obscure_site", symbol="BTCUSDT", metric="reddit_sentiment",
            ts=_T0 + timedelta(days=i), available_at=_T0 + timedelta(days=i, hours=2),
            value=0.1 * i, url="https://example.test/page",
        )
        for i in range(n)
    ]


def test_missing_scrape_dir_degrades_to_empty(tmp_path):
    prov = ScrapedAltDataProvider(tmp_path / "nope")
    assert prov.fetch_series("BTCUSDT", "reddit_sentiment", limit=10) == []


def test_roundtrip_records_through_provider_seam(tmp_path):
    write_scraped_records(tmp_path, "obscure_site", _records(5))
    prov = ScrapedAltDataProvider(tmp_path)
    pts = prov.fetch_series("BTCUSDT", "reddit_sentiment", limit=10)
    assert len(pts) == 5
    assert [p.ts for p in pts] == sorted(p.ts for p in pts)  # ascending, point-in-time
    assert all(p.available_at > p.ts for p in pts)  # availability is after observation (no look-ahead)
    # Wrong symbol/metric → [] (the seam filters strictly).
    assert prov.fetch_series("ETHUSDT", "reddit_sentiment", limit=10) == []


def test_scraped_records_ingest_through_standard_pipeline(tmp_path):
    write_scraped_records(tmp_path / "scrape", "obscure_site", _records(4))
    prov = ScrapedAltDataProvider(tmp_path / "scrape")
    store = AltDataStore(tmp_path / "alt")
    n = ingest_numeric(store, prov, ["BTCUSDT"], "reddit_sentiment", provider_name="scrape")
    assert n == 4  # scraped rows flow through the EXACT same ingest path as an API source
    far = _T0 + timedelta(days=99)
    assert len(store.read_asof("scrape", "BTCUSDT", "reddit_sentiment", far)) == 4


def test_stub_scrape_is_inert(tmp_path):
    # The fetch+extract step is deliberately unbuilt — it returns [] so the path is wired without live scraping.
    assert stub_scrape("obscure_site", "BTCUSDT", "reddit_sentiment", "https://example.test") == []
