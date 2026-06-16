# The cron-fleet dead-man's-switch: a fresh fleet is OK + silent; a dark fleet (stale or never-fired signals)
# pages Slack ONCE and returns non-zero. Offline: temp sqlite Store, injected Slack poster (no network).

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.notify.slack import SlackNotifier
from cosmu.ops import heartbeat


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/hb.sqlite3", openrouter_api_key=None))


def _recorder() -> tuple[SlackNotifier, list[str]]:
    sent: list[str] = []
    notifier = SlackNotifier("https://hook.test", _post=lambda _url, payload: sent.append(payload.decode()))
    return notifier, sent


def _seed(store: Store, *, ingest_ago_h: float, mark_ago_h: float, tick_ago_h: float, now: datetime) -> None:
    iso = lambda h: (now - timedelta(hours=h)).isoformat()  # noqa: E731
    store.rows(
        "INSERT INTO alt_data (provider, symbol, metric, ts, available_at, value, ingested_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("binance", "BTC", "funding_rate", iso(ingest_ago_h), iso(ingest_ago_h), "0.0001", iso(ingest_ago_h)),
    )
    store.append_event(actor="master", kind="tracks_marked", ref_type="portfolio", ref_id="aggregate", payload={})
    store.rows("UPDATE events SET ts = ? WHERE kind = 'tracks_marked'", (iso(mark_ago_h),))
    store.append_event(actor="master", kind="autonomy_tick_started", ref_type="run", ref_id="r", payload={})
    store.append_event(actor="master", kind="autonomy_tick_completed", ref_type="run", ref_id="r", payload={})
    store.rows("UPDATE events SET ts = ? WHERE kind IN ('autonomy_tick_started', 'autonomy_tick_completed')", (iso(tick_ago_h),))


def test_fresh_fleet_is_ok_and_silent(tmp_path):
    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    store = _store(tmp_path)
    _seed(store, ingest_ago_h=0.5, mark_ago_h=2.0, tick_ago_h=1.0, now=now)
    report = heartbeat.check(store, now=now)
    assert report["ok"] is True and report["stale"] == {}
    notifier, sent = _recorder()
    assert heartbeat.run(store, notifier=notifier, now=now) == 0
    assert sent == []  # healthy → no Slack noise


def test_dark_fleet_pages_once_and_returns_nonzero(tmp_path):
    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    store = _store(tmp_path)
    # ingest 30h stale (>3), mark 50h stale (>30), tick 40h stale (>9) — the real Railway-dark scenario.
    _seed(store, ingest_ago_h=30.0, mark_ago_h=50.0, tick_ago_h=40.0, now=now)
    report = heartbeat.check(store, now=now)
    assert report["ok"] is False
    assert set(report["stale"]) == {"ingest", "tick", "mark"}
    notifier, sent = _recorder()
    assert heartbeat.run(store, notifier=notifier, now=now) == 1
    assert len(sent) == 1 and "Cron fleet stale" in sent[0]


def test_never_fired_signal_is_stale(tmp_path):
    # Empty DB → every signal is None → all stale (the cold-start / total-silence case).
    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    report = heartbeat.check(_store(tmp_path), now=now)
    assert report["ok"] is False
    assert report["ages_h"] == {"ingest": None, "tick": None, "mark": None}
