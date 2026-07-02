# Hermetic tests for the alerting dead-man fabric (feat/alerting-deadman). No network, temp sqlite Store.
# Covers: (1) sync_modal_secret WANTED carries SLACK_WEBHOOK_URL(+_PAGE) and a .env WITHOUT them silently omits
# them; (2) SlackNotifier.tiered page/log routing + single-channel page→log fallback; (3) record_watchdog_pulse
# writes a pulse; (4) heartbeat.check reports 'watchdog' stale with no recent pulse; (5) GET /health/fleet shape,
# it's auth-exempt, and returns 200 even on a store read error; (6) the fleet-watchdog YAML parses; (7) a budget
# 100%-crossed alert + an account EXHAUSTED stride route to the PAGE tier while info/warn/stride stay on LOG.

from __future__ import annotations

import importlib.util
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.notify.slack import SlackNotifier, record_watchdog_pulse
from cosmu.ops import heartbeat

# Repo root = five parents up from this file (apps/engine/tests/<f> → repo root). Used to load the root-level
# scripts/sync_modal_secret.py and .github/workflows/fleet-watchdog.yml — both live OUTSIDE the engine package.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/dm.sqlite3", openrouter_api_key=None, _env_file=None))


def _load_sync_modal_secret():
    """Load the root-level scripts/sync_modal_secret.py by file path (it is not an importable package)."""
    path = _REPO_ROOT / "scripts" / "sync_modal_secret.py"
    spec = importlib.util.spec_from_file_location("sync_modal_secret_undertest", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# 1. sync_modal_secret — WANTED carries the webhooks; a .env without them omits them (no crash)
# ---------------------------------------------------------------------------


def test_wanted_carries_slack_webhooks():
    sms = _load_sync_modal_secret()
    assert "SLACK_WEBHOOK_URL" in sms.WANTED
    assert "SLACK_WEBHOOK_URL_PAGE" in sms.WANTED


def test_env_without_webhook_silently_omits_it(tmp_path):
    # An operator without a webhook set → the `if env.get(k)` filter drops it → the Modal secret carries no
    # SLACK_WEBHOOK_URL → the notifiers stay a no-op. ZERO behavior change when unset (never a crash).
    sms = _load_sync_modal_secret()
    env_file = tmp_path / ".env.local"
    env_file.write_text("DATABASE_URL=postgres://u:p@h/db\nXAI_API_KEY=xk\n")  # no SLACK_* lines
    parsed = sms._parse_env(env_file)
    pairs = {k: parsed[k] for k in sms.WANTED if parsed.get(k)}
    assert "SLACK_WEBHOOK_URL" not in pairs  # absent → omitted, no KeyError, no crash
    assert "SLACK_WEBHOOK_URL_PAGE" not in pairs
    assert pairs["DATABASE_URL"] == "postgres://u:p@h/db"  # the rest is unaffected


def test_env_with_webhooks_includes_them(tmp_path):
    sms = _load_sync_modal_secret()
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "DATABASE_URL=postgres://u:p@h/db\n"
        "SLACK_WEBHOOK_URL=https://hooks.slack.test/LOG\n"
        "SLACK_WEBHOOK_URL_PAGE=https://hooks.slack.test/PAGE\n"
    )
    parsed = sms._parse_env(env_file)
    pairs = {k: parsed[k] for k in sms.WANTED if parsed.get(k)}
    assert pairs["SLACK_WEBHOOK_URL"] == "https://hooks.slack.test/LOG"
    assert pairs["SLACK_WEBHOOK_URL_PAGE"] == "https://hooks.slack.test/PAGE"


# ---------------------------------------------------------------------------
# 2. SlackNotifier.tiered — page/log routing + single-channel fallback
# ---------------------------------------------------------------------------


def test_tiered_page_uses_page_bus_when_set(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL_PAGE", raising=False)
    s = types.SimpleNamespace(slack_webhook_url="https://h/log", slack_webhook_url_page="https://h/PAGE")
    posted: list[str] = []
    SlackNotifier.tiered(s, "page", _post=lambda u, p: posted.append(u)).send("x")
    assert posted == ["https://h/PAGE"]


def test_tiered_log_uses_log_bus(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL_PAGE", raising=False)
    s = types.SimpleNamespace(slack_webhook_url="https://h/log", slack_webhook_url_page="https://h/PAGE")
    posted: list[str] = []
    SlackNotifier.tiered(s, "log", _post=lambda u, p: posted.append(u)).send("x")
    assert posted == ["https://h/log"]


def test_tiered_page_falls_back_to_log_when_page_unset(monkeypatch):
    # Single-channel operator: no page bus → the page tier rides the log webhook (loses nothing).
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL_PAGE", raising=False)
    s = types.SimpleNamespace(slack_webhook_url="https://h/only", slack_webhook_url_page=None)
    posted: list[str] = []
    SlackNotifier.tiered(s, "page", _post=lambda u, p: posted.append(u)).send("x")
    assert posted == ["https://h/only"]


def test_tiered_noop_when_both_unset(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL_PAGE", raising=False)
    s = types.SimpleNamespace(slack_webhook_url=None, slack_webhook_url_page=None)
    posted: list[str] = []
    SlackNotifier.tiered(s, "page", _post=lambda u, p: posted.append(u)).send("x")
    assert posted == []  # graceful no-op, never raises


# ---------------------------------------------------------------------------
# 3 & 4. record_watchdog_pulse + heartbeat watchdog signal
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_backup(monkeypatch):
    # Keep the R2 backup probe offline+healthy so it never independently trips these DB-signal tests.
    monkeypatch.setattr(heartbeat, "_newest_backup_age_h", lambda settings, now: 2.0)


def test_record_watchdog_pulse_writes_an_event(tmp_path):
    store = _store(tmp_path)
    assert store.row("SELECT COUNT(*) AS c FROM events WHERE kind = 'watchdog_pulse'")["c"] == 0
    record_watchdog_pulse(store)
    assert store.row("SELECT COUNT(*) AS c FROM events WHERE kind = 'watchdog_pulse'")["c"] == 1


def test_record_watchdog_pulse_is_noop_safe_on_none():
    record_watchdog_pulse(None)  # must not raise


def test_check_reports_watchdog_stale_without_pulse(tmp_path):
    # No pulse ever written → watchdog age None → stale (the heartbeat-cron-died signal).
    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    report = heartbeat.check(_store(tmp_path), now=now)
    assert "watchdog" in report["stale"]
    assert report["ages_h"]["watchdog"] is None


def test_check_watchdog_fresh_after_pulse(tmp_path):
    now = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
    store = _store(tmp_path)
    # A fresh pulse 0.5h ago (well under the 2h ceiling) → watchdog not stale.
    store.append_event(actor="ops", kind="watchdog_pulse", ref_type="heartbeat", ref_id="fleet", payload={})
    store.rows("UPDATE events SET ts = ? WHERE kind = 'watchdog_pulse'",
               ((now - timedelta(hours=0.5)).isoformat(),))
    report = heartbeat.check(store, now=now)
    assert "watchdog" not in report["stale"]
    assert report["ages_h"]["watchdog"] == 0.5


# ---------------------------------------------------------------------------
# 5. GET /health/fleet — shape, auth-exempt, 200 even on a store read error
# ---------------------------------------------------------------------------


def _client(tmp_path, monkeypatch, *, secret: str | None = None):
    from fastapi.testclient import TestClient

    import cosmu.api.app as app_mod

    settings = Settings(database_url=f"sqlite:///{tmp_path}/api.sqlite3", openrouter_api_key=None,
                        api_secret_key=secret, _env_file=None)
    store = Store(settings)
    monkeypatch.setattr(app_mod, "store", store)
    monkeypatch.setattr(app_mod, "settings", settings)
    # Keep the R2 backup probe offline for the route too.
    monkeypatch.setattr(heartbeat, "_newest_backup_age_h", lambda settings, now: 2.0)
    return TestClient(app_mod.app), store


def test_health_fleet_shape(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    resp = client.get("/health/fleet")
    assert resp.status_code == 200
    body = resp.json()
    assert "stale" in body and isinstance(body["stale"], bool)
    assert "ages_h" in body and "watchdog" in body["ages_h"]
    assert "watchdog_pulse_age_h" in body  # cold store → None (never fired)
    assert body["stale"] is True  # empty fleet → stale


def test_health_fleet_is_auth_exempt(tmp_path, monkeypatch):
    import cosmu.api.app as app_mod

    assert "/health/fleet" in app_mod._AUTH_EXEMPT_PATHS
    # And reachable WITHOUT the x-api-key even when a secret is configured.
    client, _ = _client(tmp_path, monkeypatch, secret="s3cret-key-very-long")
    assert client.get("/health/fleet").status_code == 200
    # A control-plane route still 401s without the header (proves the gate is otherwise live).
    assert client.get("/settings/keys").status_code == 401


def test_health_fleet_returns_200_on_store_error(tmp_path, monkeypatch):
    # An external prober must distinguish "engine up but fleet stale" (200 + stale:true) from "engine down"
    # (conn refused / 5xx). A store read error inside the handler must therefore yield 200, not 500. The handler
    # does `from cosmu.ops.heartbeat import check` at call time, so patching heartbeat.check to raise exercises
    # the try/except that converts a DB blip into a 200 stale-report (Store is frozen — can't patch its methods).
    client, _ = _client(tmp_path, monkeypatch)

    def _boom(*_a, **_kw):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(heartbeat, "check", _boom)
    resp = client.get("/health/fleet")
    assert resp.status_code == 200  # NOT a 5xx
    body = resp.json()
    assert body["ok"] is False and body["stale"] is True
    assert "error" in body


# ---------------------------------------------------------------------------
# 6. The off-Modal fleet-watchdog workflow YAML parses
# ---------------------------------------------------------------------------


def test_fleet_watchdog_yaml_parses():
    import yaml

    path = _REPO_ROOT / ".github" / "workflows" / "fleet-watchdog.yml"
    doc = yaml.safe_load(path.read_text())
    assert doc["name"] == "fleet-watchdog"
    # PyYAML parses the bare `on:` key as the boolean True — assert on either spelling defensively.
    on = doc.get("on", doc.get(True))
    assert "schedule" in on and "workflow_dispatch" in on
    assert on["schedule"][0]["cron"] == "15 * * * *"


# ---------------------------------------------------------------------------
# 7. costs/alerts — budget 100% + account EXHAUSTED route to the PAGE tier
# ---------------------------------------------------------------------------


def _alerts_settings(**over):
    return types.SimpleNamespace(
        slack_webhook_url=over.get("slack_webhook_url", "https://h/LOG"),
        slack_webhook_url_page=over.get("slack_webhook_url_page", "https://h/PAGE"),
    )


def test_budget_critical_routes_to_page_and_warn_to_log(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL_PAGE", raising=False)
    from cosmu.costs.alerts import BudgetAlert, emit_alerts

    posted: list[str] = []
    settings = _alerts_settings()
    critical = BudgetAlert(vendor="global", threshold_pct=1.0, level="critical", action="throttle-suggest",
                           spend=31, budget=30)
    warn = BudgetAlert(vendor="OpenRouter", threshold_pct=0.8, level="warning", action="warn", spend=80, budget=100)
    emit_alerts([critical, warn], store=None, settings=settings, _http_post=lambda u, p: posted.append(u))
    assert "https://h/PAGE" in posted  # 100%-crossed critical → PAGE bus
    assert "https://h/LOG" in posted   # 80% warn → LOG bus


def test_budget_critical_falls_back_to_log_when_no_page_bus(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL_PAGE", raising=False)
    from cosmu.costs.alerts import BudgetAlert, emit_alerts

    posted: list[str] = []
    settings = _alerts_settings(slack_webhook_url_page=None)  # single-channel operator
    critical = BudgetAlert(vendor="global", threshold_pct=1.0, level="critical", action="throttle-suggest",
                           spend=31, budget=30)
    emit_alerts([critical], store=None, settings=settings, _http_post=lambda u, p: posted.append(u))
    assert posted == ["https://h/LOG"]  # page tier falls back to the single log channel
