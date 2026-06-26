# The Railway → Modal cross-monitor (the watcher's watcher, cosmu/ops/modal_watch.py): an in-process Railway
# loop that re-runs the SHARED heartbeat.check() FROM Railway and pages on a DARK Modal fleet (the Modal-driven
# DB signals all stale) — the total-Modal-death case the on-Modal heartbeat can't see itself. Detection only.
#
# Mirrors test_heartbeat.py (temp sqlite Store, injected Slack poster, fixed clock) + test_realtime_worker.py's
# async-loop driving (asyncio.run + a stop event). Offline: the `backup` signal (R2/boto3) is irrelevant here
# because the monitor deliberately drops it — but we still stub _newest_backup_age_h fresh so the underlying
# check() never touches boto3/network, exactly as the heartbeat tests do.

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.notify.slack import SlackNotifier
from cosmu.ops import heartbeat, modal_watch

_NOW = datetime(2026, 6, 26, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fresh_backup(monkeypatch):
    """Keep the shared check() offline: stub the only non-DB (R2/boto3) signal to a healthy 2h. The monitor
    drops `backup` from its verdict anyway, so this just guarantees no boto3/network is ever touched."""
    monkeypatch.setattr(heartbeat, "_newest_backup_age_h", lambda settings, now: 2.0)


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/mw.sqlite3", openrouter_api_key=None))


def _recorder() -> tuple[SlackNotifier, list[str]]:
    sent: list[str] = []
    notifier = SlackNotifier("https://hook.test", _post=lambda _url, payload: sent.append(payload.decode()))
    return notifier, sent


def _seed(store: Store, *, ingest_ago_h: float, mark_ago_h: float, tick_ago_h: float, exec_ago_h: float) -> None:
    """Seed the four Modal-driven DB signals at given ages (same shape as the heartbeat tests' _seed)."""
    iso = lambda h: (_NOW - timedelta(hours=h)).isoformat()  # noqa: E731
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
    store.append_event(actor="master", kind="paper_stepped", ref_type="portfolio", ref_id="aggregate", payload={})
    store.rows("UPDATE events SET ts = ? WHERE kind = 'paper_stepped'", (iso(exec_ago_h),))


# ── the pure verdict (check_modal_liveness) ──────────────────────────────────────────────────────────────────


def test_fresh_fleet_is_not_dark(tmp_path):
    store = _store(tmp_path)
    _seed(store, ingest_ago_h=0.5, mark_ago_h=2.0, tick_ago_h=1.0, exec_ago_h=2.0)
    v = modal_watch.check_modal_liveness(store, now=_NOW)
    assert v["modal_dark"] is False and v["modal_stale"] == {}


def test_dark_fleet_is_dark_on_db_signals(tmp_path):
    store = _store(tmp_path)
    # Every Modal DB signal past its ceiling (ingest>3, tick>9, mark>30, exec>30) = total Modal death.
    _seed(store, ingest_ago_h=30.0, mark_ago_h=50.0, tick_ago_h=40.0, exec_ago_h=50.0)
    v = modal_watch.check_modal_liveness(store, now=_NOW)
    assert v["modal_dark"] is True
    assert set(v["modal_stale"]) == {"ingest", "tick", "mark", "exec"}  # backup dropped, never present


def test_backup_signal_never_triggers_the_railway_monitor(tmp_path, monkeypatch):
    # The Railway image has no boto3 → check()'s backup probe would read None (stale). The monitor MUST drop it
    # so that a healthy-DB / unprobeable-backup state is NOT a false 'Modal dark'. Simulate boto3-absence by
    # forcing the backup signal stale; the DB signals are all fresh → modal_dark stays False.
    monkeypatch.setattr(heartbeat, "_newest_backup_age_h", lambda settings, now: None)  # stale backup
    store = _store(tmp_path)
    _seed(store, ingest_ago_h=0.5, mark_ago_h=2.0, tick_ago_h=1.0, exec_ago_h=2.0)
    v = modal_watch.check_modal_liveness(store, now=_NOW)
    assert v["modal_dark"] is False           # backup-stale alone does NOT page the cross-monitor
    assert "backup" not in v["modal_stale"]


# ── the supervised loop (run_modal_watch_loop) ───────────────────────────────────────────────────────────────


def _run_loop_once(store: Store, notifier: SlackNotifier, *, ticks: int = 1) -> int:
    """Drive the loop for a fixed number of cycles at a tiny interval, then stop. Returns pages sent."""
    stop = asyncio.Event()
    seen = {"n": 0}

    def now_fn():
        seen["n"] += 1
        if seen["n"] >= ticks:
            stop.set()
        return _NOW

    return asyncio.run(asyncio.wait_for(
        modal_watch.run_modal_watch_loop(
            store, notifier=notifier, stop=stop, interval_s=0.01, now_fn=now_fn,
        ),
        timeout=10,
    ))


def test_loop_fires_and_pages_when_modal_dark(tmp_path):
    store = _store(tmp_path)
    _seed(store, ingest_ago_h=30.0, mark_ago_h=50.0, tick_ago_h=40.0, exec_ago_h=50.0)
    notifier, sent = _recorder()
    pages = _run_loop_once(store, notifier, ticks=1)
    assert pages == 1
    assert len(sent) == 1 and "MODAL FLEET DARK (seen from Railway)" in sent[0]


def test_loop_is_silent_when_fleet_fresh(tmp_path):
    store = _store(tmp_path)
    _seed(store, ingest_ago_h=0.5, mark_ago_h=2.0, tick_ago_h=1.0, exec_ago_h=2.0)
    notifier, sent = _recorder()
    pages = _run_loop_once(store, notifier, ticks=3)  # several cycles, all healthy
    assert pages == 0 and sent == []


def test_loop_pages_once_per_stale_episode(tmp_path):
    # A long Modal outage = ONE ping, not one-per-cycle (rising-edge dedup).
    store = _store(tmp_path)
    _seed(store, ingest_ago_h=30.0, mark_ago_h=50.0, tick_ago_h=40.0, exec_ago_h=50.0)
    notifier, sent = _recorder()
    pages = _run_loop_once(store, notifier, ticks=5)  # five cycles, all dark
    assert pages == 1 and len(sent) == 1


def test_loop_re_arms_after_recovery(tmp_path):
    # dark → healthy → dark must page TWICE (one per distinct episode). We flip the DB between cycles by
    # rewriting the signal ages on a shared store the loop reads each tick.
    store = _store(tmp_path)
    notifier, sent = _recorder()
    stop = asyncio.Event()
    phase = {"n": 0}

    def now_fn():
        # Cycle 0: dark. Cycle 1: heal. Cycle 2: dark again. Cycle 3: stop.
        n = phase["n"]
        phase["n"] += 1
        store.rows("DELETE FROM alt_data")
        store.rows("DELETE FROM events")
        if n in (0, 2):
            _seed(store, ingest_ago_h=30.0, mark_ago_h=50.0, tick_ago_h=40.0, exec_ago_h=50.0)
        elif n == 1:
            _seed(store, ingest_ago_h=0.5, mark_ago_h=2.0, tick_ago_h=1.0, exec_ago_h=2.0)
        else:
            stop.set()
        return _NOW

    pages = asyncio.run(asyncio.wait_for(
        modal_watch.run_modal_watch_loop(
            store, notifier=notifier, stop=stop, interval_s=0.01, now_fn=now_fn,
        ),
        timeout=10,
    ))
    assert pages == 2 and len(sent) == 2  # two separate dark episodes → two pages


def test_loop_survives_a_check_error(tmp_path, monkeypatch):
    # A transient read error skips one cycle, never kills the loop (crash isolation, like the worker heartbeat).
    store = _store(tmp_path)
    _seed(store, ingest_ago_h=30.0, mark_ago_h=50.0, tick_ago_h=40.0, exec_ago_h=50.0)
    notifier, sent = _recorder()
    calls = {"n": 0}
    real_check = modal_watch.check_modal_liveness

    def flaky(store_, **kw):  # noqa: ANN001, ANN003
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("DB blip")
        return real_check(store_, **kw)

    monkeypatch.setattr(modal_watch, "check_modal_liveness", flaky)
    # tick 1 raises (skipped), tick 2 sees dark and pages, then stop.
    pages = _run_loop_once(store, notifier, ticks=2)
    assert pages == 1 and len(sent) == 1  # survived the first-cycle error, paged on the second


# ── the lifespan flag gate ───────────────────────────────────────────────────────────────────────────────────


def test_lifespan_does_not_spawn_monitor_when_flag_off(tmp_path, monkeypatch):
    # MODAL_WATCH_ENABLED off (default) → the lifespan never imports/creates the monitor task. We assert the
    # branch is gated by spying on run_modal_watch_loop: it must never be called with the flag off.
    import cosmu.api._lifespan as lifespan_mod

    called = {"n": 0}
    monkeypatch.setattr(
        "cosmu.ops.modal_watch.run_modal_watch_loop",
        lambda *a, **k: (_ := called.__setitem__("n", called["n"] + 1)),
    )
    monkeypatch.setattr(lifespan_mod.settings, "modal_watch_enabled", False)
    monkeypatch.setattr(lifespan_mod.settings, "realtime_worker_enabled", False)

    async def drive():
        async with lifespan_mod.lifespan(None):  # type: ignore[arg-type]
            pass

    asyncio.run(drive())
    assert called["n"] == 0  # flag off → monitor never spawned
