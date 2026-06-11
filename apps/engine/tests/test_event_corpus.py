# The event-corpus bridge (research/event_corpus.py): root-event clustering (breaker vs echoes, decaying
# novelty, window expiry), honest availability on JSONL loads (publish-time feeds vs scraped archives — no
# silent backdating), and the NewsItem adapter. Offline + deterministic (keyless embedding, no LLM).

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from cosmu.data.events_store import MarketEvent
from cosmu.data.providers._types import NewsItem
from cosmu.research.event_corpus import cluster_root_events, events_from_jsonl, events_from_news_items

_T0 = datetime(2026, 6, 10, 9, 0, tzinfo=UTC)


def _event(title: str, *, hours: float = 0.0) -> MarketEvent:
    ts = _T0 + timedelta(hours=hours)
    return MarketEvent(provider="gdelt", source="", symbols=("BTCUSDT",), ts=ts, available_at=ts, title=title)


def test_same_story_clusters_breaker_first_novelty_decays():
    events = [
        _event("SEC approves the spot bitcoin ETF application", hours=0),
        _event("Spot bitcoin ETF application approved by SEC", hours=1),       # echo (same tokens)
        _event("SEC approves spot bitcoin ETF application today", hours=2),    # echo
        _event("Ethereum foundation announces devcon schedule", hours=1),      # unrelated → own root
    ]
    clustered = cluster_root_events(events)
    by_title = {e.title: e for e in clustered}

    breaker = by_title["SEC approves the spot bitcoin ETF application"]
    echo1 = by_title["Spot bitcoin ETF application approved by SEC"]
    echo2 = by_title["SEC approves spot bitcoin ETF application today"]
    other = by_title["Ethereum foundation announces devcon schedule"]

    assert breaker.novelty == 1.0 and breaker.root_event_id == breaker.content_hash
    assert echo1.root_event_id == breaker.root_event_id and echo1.novelty == 0.5
    assert echo2.root_event_id == breaker.root_event_id and abs(echo2.novelty - 1 / 3) < 1e-9
    assert other.root_event_id == other.content_hash and other.novelty == 1.0


def test_cluster_window_expires():
    events = [
        _event("SEC approves the spot bitcoin ETF application", hours=0),
        _event("SEC approves the spot bitcoin ETF application again", hours=30),  # past the 24h window
    ]
    clustered = cluster_root_events(events, window_hours=24)
    assert clustered[0].root_event_id != clustered[1].root_event_id
    assert clustered[1].novelty == 1.0  # a re-emerging story is a NEW root, not a stale echo


def test_clustering_is_deterministic():
    events = [_event(f"bitcoin headline number {i}", hours=i * 0.1) for i in range(10)]
    a = cluster_root_events(events)
    b = cluster_root_events(list(reversed(events)))  # input order must not matter (sorted internally)
    assert [(e.content_hash, e.root_event_id, e.novelty) for e in a] == [
        (e.content_hash, e.root_event_id, e.novelty) for e in b
    ]


def test_jsonl_load_publish_time_vs_scrape_time(tmp_path):
    path = tmp_path / "corpus.jsonl"
    rows = [
        {"ts": _T0.isoformat(), "title": "headline one", "symbol": "BTCUSDT", "source": "reuters"},
        {"ts": _T0.isoformat(), "title": "headline two", "symbols": ["ETHUSDT"],
         "available_at": (_T0 + timedelta(minutes=5)).isoformat()},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows))

    pit = events_from_jsonl(path, provider="gdelt", availability="publish-time")
    one = next(e for e in pit if e.title == "headline one")
    two = next(e for e in pit if e.title == "headline two")
    assert one.available_at == one.ts                             # true-PIT feed: available at publish
    assert two.available_at == _T0 + timedelta(minutes=5)         # a row's own stamp always wins

    scraped_at = _T0 + timedelta(days=400)
    archive = events_from_jsonl(path, provider="chrome_lane", availability=scraped_at)
    one_a = next(e for e in archive if e.title == "headline one")
    assert one_a.available_at == scraped_at                       # scraped archive: NEVER backdated
    assert one_a.ts == _T0                                        # …but the event clock keeps publish time


def test_news_item_adapter():
    items = [NewsItem(ts=_T0, available_at=_T0 + timedelta(minutes=1), headline="BTC rallies on ETF news")]
    events = events_from_news_items(items, symbol="BTCUSDT")
    assert events[0].symbols == ("BTCUSDT",)
    assert events[0].available_at == _T0 + timedelta(minutes=1)
    assert events[0].content_hash  # hydrated on adaptation
