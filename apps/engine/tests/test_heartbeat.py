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
    exec_ago_h: float | None = None, watchdog_ago_h: float = 0.5,
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
    # The heartbeat's SELF-pulse: run() writes this on every healthy run, so a live heartbeat has a fresh one.
    # Defaults to 0.5h (fresh) — the heartbeat cron is what runs check(), so even when the OTHER signals are dark
    # (a partial fleet death) the heartbeat itself is alive and its pulse is recent. Override to age it out and
    # exercise the "the heartbeat cron ITSELF died" case (a stale watchdog seen from the external prober).
    store.append_event(actor="ops", kind="watchdog_pulse", ref_type="heartbeat", ref_id="fleet", payload={})
    store.rows("UPDATE events SET ts = ? WHERE kind = 'watchdog_pulse'", (iso(watchdog_ago_h),))


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
    assert report["ages_h"] == {
        "ingest": None, "tick": None, "mark": None, "exec": None, "backup": 2.0, "watchdog": None,
    }
    # backup fresh (stubbed) → not stale; watchdog never fired → stale (no pulse yet, cold start).
    assert set(report["stale"]) == {"ingest", "tick", "mark", "exec", "watchdog"}


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
# The dead-man watchdog: the heartbeat's own aliveness beacon. A HEALTHY run must record a watchdog_pulse; the
# ABSENCE of a fresh pulse means the heartbeat CRON ITSELF stopped (the SPOF that let the fleet die silently for
# ~10 days). check() reads MAX(ts) of kind='watchdog_pulse' and reports on the heartbeat's OWN last run.
# ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_healthy_run_records_a_watchdog_pulse(tmp_path):
    # A healthy run beats the watchdog: run() appends a watchdog_pulse so the external prober can see the
    # heartbeat is alive. Seed a fresh fleet WITH a fresh pulse (so the check is green + returns 0), and assert a
    # NEW pulse was appended (2 total) with no page.
    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    store = _store(tmp_path)
    _seed(store, ingest_ago_h=0.5, mark_ago_h=2.0, tick_ago_h=1.0, exec_ago_h=2.0, watchdog_ago_h=0.5, now=now)
    assert store.row("SELECT COUNT(*) AS c FROM events WHERE kind = 'watchdog_pulse'")["c"] == 1
    notifier, sent = _recorder()
    assert heartbeat.run(store, notifier=notifier, now=now) == 0
    assert sent == []  # healthy → no page
    assert store.row("SELECT COUNT(*) AS c FROM events WHERE kind = 'watchdog_pulse'")["c"] == 2


def test_run_records_pulse_and_bootstraps_even_when_a_watched_job_is_dark(tmp_path):
    # The pulse is ORTHOGONAL to the other signals: even a run that PAGES (a watched job dark, and no prior pulse
    # so the watchdog signal itself starts None) still records the pulse — proof the cron ran + reached the DB.
    # This also bootstraps the very first pulse from a cold DB (else the watchdog signal could never self-heal).
    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    store = _store(tmp_path)
    _seed(store, ingest_ago_h=0.5, mark_ago_h=2.0, tick_ago_h=1.0, exec_ago_h=40.0, now=now)  # exec dark
    store.rows("DELETE FROM events WHERE kind = 'watchdog_pulse'")  # cold start: no pulse yet
    notifier, sent = _recorder()
    assert heartbeat.run(store, notifier=notifier, now=now) == 1  # exec stale → pages, returns non-zero
    assert len(sent) == 1  # paged for the dark executor
    assert store.row("SELECT COUNT(*) AS c FROM events WHERE kind = 'watchdog_pulse'")["c"] == 1  # still pulsed


def test_check_reports_watchdog_stale_when_no_recent_pulse(tmp_path):
    # The heartbeat-cron-died case: every OTHER signal is fresh, but the watchdog pulse is 3h old (>2h ceiling) —
    # meaning the heartbeat itself hasn't run in >2h. This pages so a dark heartbeat can't hide.
    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    store = _store(tmp_path)
    _seed(store, ingest_ago_h=0.5, mark_ago_h=2.0, tick_ago_h=1.0, exec_ago_h=2.0, watchdog_ago_h=3.0, now=now)
    report = heartbeat.check(store, now=now)
    assert report["ok"] is False
    assert set(report["stale"]) == {"watchdog"}
    assert report["ages_h"]["watchdog"] == 3.0


def test_run_defaults_to_page_tier(tmp_path, monkeypatch):
    # With no injected notifier, run() routes the dark-fleet page through SlackNotifier.tiered('page'). Prove it
    # by pointing settings at a page bus and asserting run() posts there (not the log bus) on a stale fleet.
    from cosmu.config.settings import Settings

    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    posted: list[str] = []
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/hbpage.sqlite3", openrouter_api_key=None,
        slack_webhook_url="https://hook.test/log", slack_webhook_url_page="https://hook.test/PAGE",
    )
    store = Store(settings)
    _seed(store, ingest_ago_h=30.0, mark_ago_h=50.0, tick_ago_h=40.0, exec_ago_h=50.0, now=now)
    # Patch the module-level _live_post so no socket opens; capture the URL the tiered notifier used.
    import cosmu.notify.slack as slack_mod
    monkeypatch.setattr(slack_mod, "_live_post", lambda url, payload: posted.append(url))
    assert heartbeat.run(store, now=now) == 1  # no injected notifier → tiered('page')
    assert posted == ["https://hook.test/PAGE"]  # the WARNING bus, not the log bus


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
