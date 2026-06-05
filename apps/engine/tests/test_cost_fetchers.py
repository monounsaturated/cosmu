# Offline tests for vendor spend fetchers and budget alerts.
# All network calls are replaced with injected seams — no real sockets (the session conftest blocks them).
# Tests: (1) fetchers return real numbers when keyed; (2) no-key → skip (None); (3) budget thresholds
# emit at 50/80/100%; (4) Slack POST is called with expected payload; (5) costs rows written.

from __future__ import annotations

import json
import types

import pytest

from cosmu.costs.alerts import BudgetAlert, check_budget, emit_alerts
from cosmu.costs.fetchers import (
    VendorSpend,
    fetch_claude_max,
    fetch_modal,
    fetch_openrouter,
    fetch_railway,
    fetch_supabase,
    fetch_vercel,
    fetch_xai_from_ledger,
    refresh_vendor_costs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**kwargs):
    """Minimal settings stand-in."""
    from cosmu.config.settings import BudgetConfig, VendorBudget
    from decimal import Decimal

    budget_overrides = kwargs.pop("budget_overrides", {})
    vendor_caps = {k: VendorBudget(monthly_cap=Decimal(str(v))) for k, v in budget_overrides.items()}
    global_cap = kwargs.pop("global_monthly_cap", 0)
    budget = BudgetConfig(
        global_monthly_cap=Decimal(str(global_cap)),
        **{k: v for k, v in vendor_caps.items()},
    )
    ns = types.SimpleNamespace(
        openrouter_api_key=kwargs.get("openrouter_api_key"),
        xai_api_key=kwargs.get("xai_api_key"),
        railway_api_token=kwargs.get("railway_api_token"),
        slack_webhook_url=kwargs.get("slack_webhook_url"),
        budget=budget,
    )
    return ns


class _FakeStore:
    """In-memory store stub for testing."""

    def __init__(self, llm_rows=None):
        self.costs: list[dict] = []
        self.recommendations: list[dict] = []
        self._llm_rows = llm_rows or []

    def row(self, sql: str, params=()) -> dict | None:
        if "llm_calls" in sql:
            total = sum(float(r.get("cost", 0)) for r in self._llm_rows)
            return {"total": total}
        return None

    def rows(self, sql: str, params=()) -> list[dict]:
        if "recommendations" in sql:
            return [{"body": r["body"]} for r in self.recommendations if r.get("state") == "open"]
        return []

    def insert(self, table: str, row: dict) -> str:
        import uuid
        row = {"id": str(uuid.uuid4()), **row}
        if table == "costs":
            self.costs.append(row)
        elif table == "recommendations":
            self.recommendations.append(row)
        return row["id"]

    class _writer:
        def __init__(self, store):
            self._store = store
            self._deleted: list[tuple] = []

        def execute(self, sql: str, params=()) -> None:
            # Track deletes but don't actually do anything in the in-memory store
            if sql.strip().upper().startswith("DELETE"):
                self._deleted.append((sql, params))

        def insert(self, table: str, row: dict) -> str:
            return self._store.insert(table, row)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    def batch(self):
        return self._writer(self)


# ---------------------------------------------------------------------------
# fetch_openrouter
# ---------------------------------------------------------------------------


def test_fetch_openrouter_returns_spend_when_keyed():
    payload = json.dumps({"data": {"usage": 12.34, "limit": 100.0}}).encode()
    result = fetch_openrouter("test-key", _http_get=lambda url, headers: payload)
    assert result is not None
    assert result.vendor == "OpenRouter"
    assert result.amount == pytest.approx(12.34)
    assert result.meta["limit"] == pytest.approx(100.0)
    assert result.meta["source"] == "api"


def test_fetch_openrouter_skips_when_no_key():
    result = fetch_openrouter(None)
    assert result is None


def test_fetch_openrouter_returns_none_on_http_error():
    def _fail(url, headers):
        raise OSError("timeout")

    result = fetch_openrouter("key", _http_get=_fail)
    assert result is None


def test_fetch_openrouter_handles_missing_data_field():
    payload = json.dumps({"error": "unauthorized"}).encode()
    result = fetch_openrouter("bad-key", _http_get=lambda url, headers: payload)
    assert result is not None
    assert result.amount == 0.0


# ---------------------------------------------------------------------------
# fetch_xai_from_ledger
# ---------------------------------------------------------------------------


def test_fetch_xai_from_ledger_sums_grok_rows():
    store = _FakeStore(llm_rows=[
        {"model_id": "grok-2", "cost": 1.5, "ts": "2026-06-01"},
        {"model_id": "grok-3", "cost": 2.0, "ts": "2026-06-02"},
    ])

    class _QueryStore:
        def row(self, sql, params=()):
            # simulate the real query: sum all grok/xai rows for the period
            total = sum(float(r["cost"]) for r in store._llm_rows)
            return {"total": total}

    result = fetch_xai_from_ledger(_QueryStore(), period="2026-06")
    assert result.vendor == "xAI"
    assert result.amount == pytest.approx(3.5)
    assert result.meta["source"] == "ledger"


def test_fetch_xai_from_ledger_none_store():
    result = fetch_xai_from_ledger(None)
    assert result.vendor == "xAI"
    assert result.amount == 0.0


def test_fetch_xai_from_ledger_empty_period():
    class _EmptyStore:
        def row(self, sql, params=()):
            return {"total": 0.0}

    result = fetch_xai_from_ledger(_EmptyStore(), period="2026-06")
    assert result.amount == 0.0


# ---------------------------------------------------------------------------
# fetch_railway
# ---------------------------------------------------------------------------


def test_fetch_railway_returns_sum_of_projects():
    payload = json.dumps({
        "data": {
            "me": {
                "projects": {
                    "edges": [
                        {"node": {"name": "cosmu-engine", "usage": {"estimatedCost": 8.5}}},
                        {"node": {"name": "cosmu-web", "usage": {"estimatedCost": 2.0}}},
                    ]
                }
            }
        }
    }).encode()

    result = fetch_railway("token", _http_post=lambda url, headers, body: payload)
    assert result is not None
    assert result.vendor == "Railway"
    assert result.amount == pytest.approx(10.5)
    assert result.meta["source"] == "api"


def test_fetch_railway_skips_when_no_token():
    result = fetch_railway(None)
    assert result is None


def test_fetch_railway_returns_none_on_error():
    def _fail(url, headers, body):
        raise OSError("network")

    result = fetch_railway("tok", _http_post=_fail)
    assert result is None


def test_fetch_railway_handles_empty_edges():
    payload = json.dumps({"data": {"me": {"projects": {"edges": []}}}}).encode()
    result = fetch_railway("tok", _http_post=lambda url, headers, body: payload)
    assert result is not None
    assert result.amount == 0.0


# ---------------------------------------------------------------------------
# fetch_modal
# ---------------------------------------------------------------------------


def test_fetch_modal_parses_dollar_amount():
    class _Result:
        stdout = "Current usage: $4.20 this month"

    result = fetch_modal(_run_cli=lambda: _Result())
    assert result is not None
    assert result.vendor == "Modal"
    assert result.amount == pytest.approx(4.2)


def test_fetch_modal_returns_none_when_no_dollar():
    class _Result:
        stdout = "No usage data available."

    result = fetch_modal(_run_cli=lambda: _Result())
    assert result is None


def test_fetch_modal_returns_none_on_exception():
    def _fail():
        raise FileNotFoundError("modal not installed")

    result = fetch_modal(_run_cli=_fail)
    assert result is None


# ---------------------------------------------------------------------------
# Constant vendors
# ---------------------------------------------------------------------------


def test_fetch_vercel_is_zero():
    result = fetch_vercel()
    assert result.vendor == "Vercel"
    assert result.amount == 0.0
    assert result.meta["source"] == "constant"


def test_fetch_supabase_is_zero():
    result = fetch_supabase()
    assert result.vendor == "Supabase"
    assert result.amount == 0.0


def test_fetch_claude_max_is_100():
    result = fetch_claude_max()
    assert result.vendor == "Claude"
    assert result.amount == pytest.approx(100.0)
    assert "Max plan" in result.meta["note"]


# ---------------------------------------------------------------------------
# refresh_vendor_costs
# ---------------------------------------------------------------------------


def test_refresh_writes_rows_to_store():
    store = _FakeStore()
    settings = _make_settings()
    # Inject no-op seams so no network is touched
    spends = refresh_vendor_costs(
        store,
        settings,
        _http_get=lambda url, headers: b'{"data":{}}',
        _http_post=lambda url, headers, body: b'{"data":{}}',
        _run_cli=lambda: types.SimpleNamespace(stdout=""),
    )
    # At minimum: xAI ledger + Vercel + Supabase + Claude are always returned
    vendors = {s.vendor for s in spends}
    assert "xAI" in vendors
    assert "Vercel" in vendors
    assert "Supabase" in vendors
    assert "Claude" in vendors
    # Rows written to costs table
    assert len(store.costs) == len(spends)


def test_refresh_skips_keyed_vendors_when_no_key():
    store = _FakeStore()
    settings = _make_settings()  # no keys set
    spends = refresh_vendor_costs(store, settings)
    vendors = {s.vendor for s in spends}
    assert "OpenRouter" not in vendors
    assert "Railway" not in vendors
    # Modal may or may not be present depending on CLI availability — that's fine


def test_refresh_none_store_still_returns_spends():
    settings = _make_settings()
    spends = refresh_vendor_costs(None, settings)
    assert any(s.vendor == "Claude" for s in spends)


# ---------------------------------------------------------------------------
# check_budget
# ---------------------------------------------------------------------------


def _spends(*pairs):
    return [VendorSpend(vendor=v, category="llm", amount=a, period="2026-06") for v, a in pairs]


def test_check_budget_no_caps_returns_empty():
    settings = _make_settings()
    alerts = check_budget(_spends(("OpenRouter", 999)), settings)
    assert alerts == []


def test_check_budget_50pct_info():
    settings = _make_settings(budget_overrides={"openrouter": 100})
    alerts = check_budget(_spends(("OpenRouter", 51)), settings)
    assert len(alerts) == 1
    assert alerts[0].vendor == "OpenRouter"
    assert alerts[0].level == "info"
    assert alerts[0].threshold_pct == pytest.approx(0.50)


def test_check_budget_80pct_warn():
    settings = _make_settings(budget_overrides={"openrouter": 100})
    alerts = check_budget(_spends(("OpenRouter", 82)), settings)
    assert len(alerts) == 1
    assert alerts[0].level == "warning"
    assert alerts[0].threshold_pct == pytest.approx(0.80)


def test_check_budget_100pct_throttle():
    settings = _make_settings(budget_overrides={"openrouter": 100})
    alerts = check_budget(_spends(("OpenRouter", 100)), settings)
    assert len(alerts) == 1
    assert alerts[0].level == "critical"
    assert alerts[0].action == "throttle-suggest"


def test_check_budget_only_highest_threshold():
    """When spend is at 120%, only the 100% alert fires (not 80% or 50% as well)."""
    settings = _make_settings(budget_overrides={"openrouter": 100})
    alerts = check_budget(_spends(("OpenRouter", 120)), settings)
    assert len(alerts) == 1
    assert alerts[0].threshold_pct == pytest.approx(1.0)


def test_check_budget_global_cap():
    settings = _make_settings(global_monthly_cap=200)
    spends = _spends(("Claude", 100), ("OpenRouter", 60), ("Railway", 50))
    alerts = check_budget(spends, settings)
    global_alerts = [a for a in alerts if a.vendor == "global"]
    assert len(global_alerts) == 1
    assert global_alerts[0].spend == pytest.approx(210)
    assert global_alerts[0].level == "critical"


def test_check_budget_multiple_vendors():
    settings = _make_settings(budget_overrides={"openrouter": 100, "railway": 50})
    spends = _spends(("OpenRouter", 60), ("Railway", 42))
    alerts = check_budget(spends, settings)
    vendors_alerted = {a.vendor for a in alerts}
    assert "OpenRouter" in vendors_alerted
    assert "Railway" in vendors_alerted


# ---------------------------------------------------------------------------
# emit_alerts — Slack POST + recommendation rows
# ---------------------------------------------------------------------------


def test_emit_alerts_calls_slack_per_alert():
    posted: list[tuple] = []

    def _mock_post(url: str, payload: bytes) -> None:
        posted.append((url, json.loads(payload)))

    alerts = [BudgetAlert(vendor="OpenRouter", threshold_pct=0.8, level="warning", action="warn", spend=80, budget=100)]
    store = _FakeStore()
    settings = _make_settings(slack_webhook_url="https://hooks.slack.com/fake")
    emit_alerts(alerts, store, settings, _http_post=_mock_post)

    assert len(posted) == 1
    url, body = posted[0]
    assert url == "https://hooks.slack.com/fake"
    assert "OpenRouter" in body["text"]
    assert "80%" in body["text"]


def test_emit_alerts_writes_recommendation_row():
    alerts = [BudgetAlert(vendor="Railway", threshold_pct=0.5, level="info", action="info", spend=26, budget=50)]
    store = _FakeStore()
    settings = _make_settings()
    emit_alerts(alerts, store, settings, _http_post=lambda url, body: None)

    assert len(store.recommendations) == 1
    rec = store.recommendations[0]
    assert rec["kind"] == "budget_threshold"
    assert "Railway" in rec["body"]
    assert rec["state"] == "open"


def test_emit_alerts_no_duplicate_recommendations():
    alerts = [BudgetAlert(vendor="xAI", threshold_pct=0.5, level="info", action="info", spend=5, budget=10)]
    store = _FakeStore()
    settings = _make_settings()
    # First call writes the recommendation
    emit_alerts(alerts, store, settings, _http_post=lambda url, body: None)
    # Second call must not duplicate it
    emit_alerts(alerts, store, settings, _http_post=lambda url, body: None)
    assert len(store.recommendations) == 1


def test_emit_alerts_no_slack_when_no_webhook():
    posted: list = []
    alerts = [BudgetAlert(vendor="Claude", threshold_pct=1.0, level="critical", action="throttle-suggest", spend=105, budget=100)]
    store = _FakeStore()
    settings = _make_settings()  # no slack_webhook_url
    emit_alerts(alerts, store, settings, _http_post=lambda url, body: posted.append(url))
    assert posted == []


def test_emit_alerts_no_op_when_empty():
    posted: list = []
    store = _FakeStore()
    settings = _make_settings(slack_webhook_url="https://hooks.slack.com/fake")
    emit_alerts([], store, settings, _http_post=lambda url, body: posted.append(url))
    assert posted == []
    assert store.recommendations == []
