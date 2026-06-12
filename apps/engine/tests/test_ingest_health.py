# The stale-source alarm (ingest/health.py): silent data death — every source 0, or providers gone quiet —
# pages ONCE per cooldown window via Slack + an ingest_degraded event; healthy passes stay silent; the check
# itself can never break ingest.

from __future__ import annotations

import datetime as dt
import json

from cosmu.config.settings import Settings
from cosmu.ingest.health import check_ingest_health
from cosmu.knowledge.store import Store
from cosmu.notify.slack import SlackNotifier

_NOW = dt.datetime(2024, 6, 5, 12, 0, tzinfo=dt.UTC)  # a Wednesday


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/health.sqlite3", openrouter_api_key=None))


def _notifier(sent: list[str]) -> SlackNotifier:
    return SlackNotifier("http://example.invalid/hook", _post=lambda url, payload: sent.append(json.loads(payload)["text"]))


def _seed_summary(store: Store, provider: str, last_at: dt.datetime) -> None:
    store.rows(
        "INSERT INTO alt_data_provider_summary(provider, metric, n_rows, latest_available_at, latest_value, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (provider, "m", 10, last_at.isoformat(), "1.0", _NOW.isoformat()),
    )


def test_healthy_pass_stays_silent(tmp_path):
    store = _store(tmp_path)
    _seed_summary(store, "binance", _NOW - dt.timedelta(hours=2))
    sent: list[str] = []
    out = check_ingest_health(store, {"funding_rate": 32, "fear_greed": 1}, notifier=_notifier(sent), now=_NOW)
    assert out is None and sent == []
    assert store.row("SELECT id FROM events WHERE kind = 'ingest_degraded'") is None


def test_all_zero_pass_pages_once_then_cools_down(tmp_path):
    # Anchored to REAL wall-clock time: the events ledger stamps utcnow() itself, so the cooldown compares
    # the injected `now` against a real insert timestamp — offsets must be relative to the same clock.
    real_now = dt.datetime.now(tz=dt.UTC)
    store = _store(tmp_path)
    sent: list[str] = []
    first = check_ingest_health(store, {"funding_rate": 0, "fear_greed": 0}, notifier=_notifier(sent), now=real_now)
    assert first is not None and first["all_zero"] is True
    assert len(sent) == 1 and "Ingest degraded" in sent[0]
    # 15 minutes later (the next cron pass) the same condition must NOT re-page — cooldown via the ledger.
    again = check_ingest_health(store, {"funding_rate": 0}, notifier=_notifier(sent), now=real_now + dt.timedelta(minutes=15))
    assert again is None and len(sent) == 1
    # After the cooldown window it pages again (the condition persisted a full day — that is news).
    later = check_ingest_health(store, {"funding_rate": 0}, notifier=_notifier(sent), now=real_now + dt.timedelta(hours=25))
    assert later is not None and len(sent) == 2


def test_stale_provider_is_named_with_age(tmp_path):
    store = _store(tmp_path)
    _seed_summary(store, "gdelt", _NOW - dt.timedelta(hours=100))   # quiet for >72h → stale
    _seed_summary(store, "binance", _NOW - dt.timedelta(hours=1))   # flowing → not listed
    sent: list[str] = []
    out = check_ingest_health(store, {"funding_rate": 32}, notifier=_notifier(sent), now=_NOW)
    assert out is not None and out["all_zero"] is False
    assert out["stale"] == [{"source": "gdelt", "age_hours": 100}]
    assert "gdelt" in sent[0] and "binance" not in sent[0]


def test_weekend_quiet_daily_source_does_not_page(tmp_path):
    """Friday's data read on Monday morning is ~65h old — inside the 72h threshold by design."""
    store = _store(tmp_path)
    friday_close = dt.datetime(2024, 5, 31, 21, 0, tzinfo=dt.UTC)
    monday = dt.datetime(2024, 6, 3, 14, 0, tzinfo=dt.UTC)
    _seed_summary(store, "cboe", friday_close)
    out = check_ingest_health(store, {"putcall_ratio": 1}, notifier=_notifier([]), now=monday)
    assert out is None


def test_health_check_never_raises():
    class _BrokenStore:
        """Every read/write fails — the check must swallow (the rollup reader already self-heals)."""

        def rows(self, *a, **k):  # noqa: ANN002, ANN003
            raise RuntimeError("db down")

        def row(self, *a, **k):  # noqa: ANN002, ANN003
            raise RuntimeError("db down")

        def append_event(self, **k):  # noqa: ANN003
            raise RuntimeError("db down")

    assert check_ingest_health(_BrokenStore(), {"x": 0}, notifier=None, now=_NOW) is None
