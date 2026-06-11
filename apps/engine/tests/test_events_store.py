# The point-in-time unstructured-event store (data/events_store.py, realtime-data-lane epic §5): append-only,
# deduped by (provider, content_hash), two clocks never conflated (ts = publish, available_at = receipt), and
# the JSONL/Postgres twins honour the same contract. Offline + deterministic.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.config.settings import Settings
from cosmu.data.events_store import EventsStore, MarketEvent, PgEventsStore, content_hash_for
from cosmu.knowledge.store import Store

_TS = datetime(2026, 6, 10, 14, 30, tzinfo=UTC)
_SEEN = datetime(2026, 6, 10, 14, 31, tzinfo=UTC)


def _event(title: str = "BTC ETF approved", *, ts: datetime = _TS, **kw) -> MarketEvent:
    defaults = dict(provider="gdelt", source="reuters", symbols=("BTCUSDT",), ts=ts, available_at=_SEEN, title=title)
    defaults.update(kw)
    return MarketEvent(**defaults)


def test_jsonl_roundtrip_and_dedup(tmp_path):
    store = EventsStore(root=tmp_path)
    events = [_event(), _event("ETH merge delayed", symbols=("ETHUSDT",))]
    assert store.append(events) == 2
    assert store.append(events) == 0  # idempotent re-ingest: a re-run writes nothing

    back = store.read("gdelt")
    assert {e.title for e in back} == {"BTC ETF approved", "ETH merge delayed"}
    btc = next(e for e in back if e.title == "BTC ETF approved")
    assert btc.ts == _TS and btc.available_at == _SEEN  # the two clocks survive the roundtrip
    assert btc.content_hash == content_hash_for("BTC ETF approved", _TS)


def test_same_headline_same_day_dedups_next_day_is_new(tmp_path):
    store = EventsStore(root=tmp_path)
    assert store.append([_event(), _event(title="  btc  ETF APPROVED ")]) == 1  # normalized text collapses
    assert store.append([_event(ts=_TS + timedelta(days=1))]) == 1  # a later-day recurrence is a NEW event


def test_read_window_clip(tmp_path):
    store = EventsStore(root=tmp_path)
    store.append([_event(title=f"headline {i}", ts=_TS + timedelta(hours=i)) for i in range(5)])
    clipped = store.read("gdelt", since=_TS + timedelta(hours=1), until=_TS + timedelta(hours=3))
    assert [e.title for e in clipped] == ["headline 1", "headline 2", "headline 3"]


def test_pg_twin_same_contract_on_sqlite(tmp_path):
    db = Store(Settings(database_url=f"sqlite:///{tmp_path}/events.sqlite3", openrouter_api_key=None))
    store = PgEventsStore(db)
    events = [
        _event(event_type="regulatory", direction=1, magnitude=0.8, confidence=0.9,
               novelty=1.0, root_event_id="root-1", extractor_version="event-extract-v1"),
        _event("ETH merge delayed", symbols=("ETHUSDT", "BTCUSDT")),
    ]
    assert store.append(events) == 2
    assert store.append(events) == 0  # dedup against the table, not just the batch

    back = store.read("gdelt")
    assert len(back) == 2
    typed = next(e for e in back if e.event_type == "regulatory")
    assert typed.direction == 1 and typed.magnitude == 0.8 and typed.root_event_id == "root-1"
    multi = next(e for e in back if e.title == "ETH merge delayed")
    assert multi.symbols == ("ETHUSDT", "BTCUSDT")  # the JSON symbols column roundtrips

    clipped = store.read("gdelt", since=_TS - timedelta(minutes=1), until=_TS + timedelta(minutes=1))
    assert len(clipped) == 2


def test_batch_internal_duplicates_collapse(tmp_path):
    db = Store(Settings(database_url=f"sqlite:///{tmp_path}/events.sqlite3", openrouter_api_key=None))
    assert PgEventsStore(db).append([_event(), _event()]) == 1  # one batch, one row
