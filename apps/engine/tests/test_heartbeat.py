# The cron-fleet dead-man's-switch: a fresh fleet is OK + silent; a dark fleet (stale or never-fired signals)
# pages Slack ONCE and returns non-zero. Offline: temp sqlite Store, injected Slack poster (no network).
#
# The `backup` signal reads R2 (the only non-DB signal), so EVERY test stubs `_newest_backup_age_h` via the
# `fresh_backup` autouse fixture (returns a healthy 2h age) — no boto3, no network. The backup-specific tests
# below override that stub to exercise stale/empty/no-creds. This keeps the legacy DB-signal tests focused on
# the fleet they were written for while the new tests own the backup canary.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import cosmu.data.pg_backup as pg_backup  # the module whose _r2_client the backup probe imports
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.notify.slack import SlackNotifier
from cosmu.ops import heartbeat


@pytest.fixture(autouse=True)
def fresh_backup(request, monkeypatch):
    """Default: a healthy 2h-old backup so the DB-signal tests aren't tripped by the R2 probe. Offline (no
    boto3/network). Tests marked `real_backup_probe` opt OUT so they can exercise the genuine probe path."""
    if "real_backup_probe" in request.keywords:
        return
    monkeypatch.setattr(heartbeat, "_newest_backup_age_h", lambda settings, now: 2.0)


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/hb.sqlite3", openrouter_api_key=None))


def _recorder() -> tuple[SlackNotifier, list[str]]:
    sent: list[str] = []
    notifier = SlackNotifier("https://hook.test", _post=lambda _url, payload: sent.append(payload.decode()))
    return notifier, sent


def _seed(
    store: Store, *, ingest_ago_h: float, mark_ago_h: float, tick_ago_h: float, now: datetime,
    exec_ago_h: float | None = None,
) -> None:
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
    # The executor clock: paper_step emits `paper_stepped` every tick. Defaults to the mark cadence so an
    # unspecified exec age never independently trips the legacy 3-signal tests.
    exec_ago_h = mark_ago_h if exec_ago_h is None else exec_ago_h
    store.append_event(actor="master", kind="paper_stepped", ref_type="portfolio", ref_id="aggregate", payload={})
    store.rows("UPDATE events SET ts = ? WHERE kind = 'paper_stepped'", (iso(exec_ago_h),))


def test_fresh_fleet_is_ok_and_silent(tmp_path):
    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    store = _store(tmp_path)
    _seed(store, ingest_ago_h=0.5, mark_ago_h=2.0, tick_ago_h=1.0, exec_ago_h=2.0, now=now)
    report = heartbeat.check(store, now=now)
    assert report["ok"] is True and report["stale"] == {}
    notifier, sent = _recorder()
    assert heartbeat.run(store, notifier=notifier, now=now) == 0
    assert sent == []  # healthy → no Slack noise


def test_dark_fleet_pages_once_and_returns_nonzero(tmp_path):
    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    store = _store(tmp_path)
    # ingest 30h stale (>3), mark 50h stale (>30), tick 40h stale (>9), exec 50h stale (>30) — Railway-dark.
    _seed(store, ingest_ago_h=30.0, mark_ago_h=50.0, tick_ago_h=40.0, exec_ago_h=50.0, now=now)
    report = heartbeat.check(store, now=now)
    assert report["ok"] is False
    assert set(report["stale"]) == {"ingest", "tick", "mark", "exec"}
    notifier, sent = _recorder()
    assert heartbeat.run(store, notifier=notifier, now=now) == 1
    assert len(sent) == 1 and "Cron fleet stale" in sent[0]


def test_never_fired_signal_is_stale(tmp_path):
    # Empty DB → every DB signal is None → all stale (the cold-start / total-silence case). The backup probe is
    # stubbed fresh (2h) by the autouse fixture, so it's the only non-stale signal here.
    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    report = heartbeat.check(_store(tmp_path), now=now)
    assert report["ok"] is False
    assert report["ages_h"] == {"ingest": None, "tick": None, "mark": None, "exec": None, "backup": 2.0}
    assert set(report["stale"]) == {"ingest", "tick", "mark", "exec"}  # backup fresh → not stale


def test_stalled_executor_pages_when_rest_of_fleet_is_fresh(tmp_path):
    # The partial-fleet-death case the other three signals miss: ingest/mark/tick all fresh, but the EXECUTOR
    # clock (paper_stepped / forward_entry) has been dark for 40h (>30) — funded tracks stop stepping forward.
    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    store = _store(tmp_path)
    _seed(store, ingest_ago_h=0.5, mark_ago_h=2.0, tick_ago_h=1.0, exec_ago_h=40.0, now=now)
    report = heartbeat.check(store, now=now)
    assert report["ok"] is False
    assert set(report["stale"]) == {"exec"}
    notifier, sent = _recorder()
    assert heartbeat.run(store, notifier=notifier, now=now) == 1
    assert len(sent) == 1 and "exec" in sent[0]


# ──────────────────────────────────────────────────────────────────────────────────────────────────────────
# The backup canary: freshness of the daily Supabase→R2 dump. The tests above stub `_newest_backup_age_h`
# wholesale (via the autouse fixture); the ones below carry @pytest.mark.real_backup_probe to opt OUT of that
# stub and instead patch pg_backup's `_r2_client` (the SHARED client the probe imports) so the REAL probe logic
# (creds-check → list_objects_v2 → newest .dump → age) is exercised offline. A silent backup death must page.
# ──────────────────────────────────────────────────────────────────────────────────────────────────────────

_R2_SETTINGS = Settings(
    database_url="sqlite:///:memory:", openrouter_api_key=None,
    r2_account_id="acct", r2_access_key_id="key", r2_secret_access_key="secret", r2_bucket="cosmu-lake",
)


class _FakeS3:
    """Minimal boto3-S3 stand-in: returns a canned list_objects_v2 page. No network."""

    def __init__(self, contents: list[dict]) -> None:
        self._contents = contents

    def list_objects_v2(self, **_kwargs):  # noqa: ANN003
        return {"Contents": self._contents}


def _obj(key: str, age_h: float, now: datetime) -> dict:
    # boto3 returns tz-aware UTC LastModified — mirror that so the probe's subtraction is real.
    return {"Key": key, "LastModified": now - timedelta(hours=age_h)}


@pytest.mark.real_backup_probe
def test_backup_fresh_is_not_stale(monkeypatch):
    # Real probe path: a 2h-old dump among older retained ones → newest wins → fresh (< 30h ceiling).
    now = datetime(2026, 6, 26, 7, 0, tzinfo=UTC)
    contents = [
        _obj("backups/pg/cosmu_pg_old.dump", 26.0, now),
        _obj("backups/pg/cosmu_pg_new.dump", 2.0, now),
        _obj("backups/pg/_manifest.json", 0.1, now),  # non-.dump ignored
    ]
    monkeypatch.setattr(pg_backup, "_r2_client", lambda settings: _FakeS3(contents))
    assert heartbeat._newest_backup_age_h(_R2_SETTINGS, now) == 2.0


@pytest.mark.real_backup_probe
def test_backup_stale_pages_when_rest_of_fleet_is_fresh(tmp_path, monkeypatch):
    # The silent-backup-death case: ingest/mark/tick/exec all fresh, but the newest dump is 40h old (>30) —
    # the daily_backup cron went dark. Must page ONCE and return non-zero.
    now = datetime(2026, 6, 26, 7, 0, tzinfo=UTC)
    store = _store(tmp_path)
    _seed(store, ingest_ago_h=0.5, mark_ago_h=2.0, tick_ago_h=1.0, exec_ago_h=2.0, now=now)
    monkeypatch.setattr(
        pg_backup, "_r2_client",
        lambda settings: _FakeS3([_obj("backups/pg/cosmu_pg_stale.dump", 40.0, now)]),
    )
    report = heartbeat.check(store, settings=_R2_SETTINGS, now=now)
    assert report["ok"] is False
    assert set(report["stale"]) == {"backup"}
    # run() also pages: it builds check() with the default store.settings (a sqlite store with no R2 creds) →
    # the probe returns None (stale) → run() returns 1 and emits exactly one Slack page naming `backup`.
    notifier, sent = _recorder()
    assert heartbeat.run(store, notifier=notifier, now=now) == 1
    assert len(sent) == 1 and "backup" in sent[0]


@pytest.mark.real_backup_probe
def test_backup_empty_prefix_is_stale(monkeypatch):
    # Prefix exists but holds no .dump (cold start, or everything pruned) → None → stale.
    now = datetime(2026, 6, 26, 7, 0, tzinfo=UTC)
    monkeypatch.setattr(pg_backup, "_r2_client", lambda settings: _FakeS3([]))
    assert heartbeat._newest_backup_age_h(_R2_SETTINGS, now) is None


@pytest.mark.real_backup_probe
def test_backup_no_creds_is_stale():
    # Keyless degradation: missing R2 creds → None (stale) without ever touching boto3/network. R2 fields are
    # explicitly nulled so a dev box's .env.local can't smuggle real creds in and reach the network.
    now = datetime(2026, 6, 26, 7, 0, tzinfo=UTC)
    no_creds = Settings(
        database_url="sqlite:///:memory:", openrouter_api_key=None,
        r2_account_id=None, r2_access_key_id=None, r2_secret_access_key=None, r2_bucket=None,
    )
    assert heartbeat._newest_backup_age_h(no_creds, now) is None


@pytest.mark.real_backup_probe
def test_backup_probe_swallows_r2_error(monkeypatch):
    # A transient R2 error (e.g. _r2_client raises) must return None (→ PAGE), never crash the heartbeat.
    now = datetime(2026, 6, 26, 7, 0, tzinfo=UTC)

    def _boom(settings):  # noqa: ANN001, ANN202
        raise RuntimeError("R2 unreachable")

    monkeypatch.setattr(pg_backup, "_r2_client", _boom)
    assert heartbeat._newest_backup_age_h(_R2_SETTINGS, now) is None
