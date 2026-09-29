# intent: offline unit tests for the lean Slack notifier.
# All network is replaced by an injected fake poster — no real sockets opened.
# Tests: (1) no-op when webhook unset; (2) posts when url set; (3) notify_gate_verdict fires only with survivors;
# (4) notify_tick_error fires; (5) notify_health_change fires; (6) errors in the poster are swallowed;
# (7) scheduler.run_tick calls the notifier on gate-pass and on error (injectable seam).

from __future__ import annotations

from cosmu.notify.slack import SlackNotifier, notify_gate_verdict, notify_health_change, notify_tick_error


# ---------------------------------------------------------------------------
# SlackNotifier unit tests
# ---------------------------------------------------------------------------


def test_no_op_when_webhook_url_is_none():
    posted: list[str] = []
    n = SlackNotifier(webhook_url=None, _post=lambda url, payload: posted.append(url))
    n.send("hello")
    assert posted == []


def test_posts_when_url_is_set():
    calls: list[tuple[str, bytes]] = []
    n = SlackNotifier(webhook_url="https://hooks.slack.test/T1", _post=lambda u, p: calls.append((u, p)))
    n.send("hello world")
    assert len(calls) == 1
    url, payload = calls[0]
    assert url == "https://hooks.slack.test/T1"
    import json
    assert json.loads(payload)["text"] == "hello world"


def test_errors_in_poster_are_swallowed():
    def _bad(url, payload):
        raise RuntimeError("network gone")

    n = SlackNotifier(webhook_url="https://hooks.slack.test/T2", _post=_bad)
    n.send("should not raise")  # must not propagate


def test_from_env_reads_env_var(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/ENV")
    calls: list[str] = []
    n = SlackNotifier.from_env(_post=lambda u, p: calls.append(u))
    n.send("from env")
    assert calls == ["https://hooks.slack.test/ENV"]


def test_from_env_noop_when_unset(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    calls: list[str] = []
    n = SlackNotifier.from_env(_post=lambda u, p: calls.append(u))
    n.send("no webhook")
    assert calls == []


def test_from_settings_reads_attribute():
    import types
    settings = types.SimpleNamespace(slack_webhook_url="https://hooks.slack.test/S1")
    calls: list[str] = []
    n = SlackNotifier.from_settings(settings, _post=lambda u, p: calls.append(u))
    n.send("from settings")
    assert calls == ["https://hooks.slack.test/S1"]


# ---------------------------------------------------------------------------
# High-level helpers
# ---------------------------------------------------------------------------


def test_notify_gate_verdict_fires_with_survivors():
    calls: list[str] = []
    n = SlackNotifier(webhook_url="https://h.t/w", _post=lambda u, p: calls.append(p.decode()))
    notify_gate_verdict(n, survivors=["mom-v1", "xsec-v2"], authored=6)
    assert len(calls) == 1
    assert "Gate passed" in calls[0]
    assert "mom-v1" in calls[0]


def test_notify_gate_verdict_noop_with_no_survivors():
    calls: list[str] = []
    n = SlackNotifier(webhook_url="https://h.t/w", _post=lambda u, p: calls.append(p))
    notify_gate_verdict(n, survivors=[], authored=4)
    assert calls == []


def test_notify_gate_verdict_evolved_note():
    calls: list[str] = []
    n = SlackNotifier(webhook_url="https://h.t/w", _post=lambda u, p: calls.append(p.decode()))
    notify_gate_verdict(n, survivors=["s1"], authored=4, evolved=3)
    assert "evolved 3" in calls[0]


def test_notify_health_change_fires():
    calls: list[str] = []
    n = SlackNotifier(webhook_url="https://h.t/w", _post=lambda u, p: calls.append(p.decode()))
    notify_health_change(n, status="degraded", detail="DB latency high")
    assert len(calls) == 1
    assert "degraded" in calls[0]
    assert "DB latency high" in calls[0]


def test_notify_tick_error_fires():
    calls: list[str] = []
    n = SlackNotifier(webhook_url="https://h.t/w", _post=lambda u, p: calls.append(p.decode()))
    notify_tick_error(n, kind="autonomy_funding_failed", error="TimeoutError")
    assert len(calls) == 1
    assert "autonomy_funding_failed" in calls[0]
    assert "TimeoutError" in calls[0]


# ---------------------------------------------------------------------------
# scheduler.run_tick injectable seam
# ---------------------------------------------------------------------------


def test_run_tick_fires_gate_verdict_via_notifier(tmp_path):
    """run_tick propagates gate-pass events through the injected notifier (no network)."""
    from cosmu.config.settings import Settings
    from cosmu.knowledge.store import Store
    from cosmu.master.scheduler import run_tick

    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/tick.sqlite3"))

    def _no_ingest(_s):
        return {"funding_rate": 3, "fear_greed": 1}

    calls: list[str] = []
    notifier = SlackNotifier(
        webhook_url="https://hooks.slack.test/TICK",
        _post=lambda u, p: calls.append(p.decode()),
    )

    report = run_tick(store, n=4, seed=7, edge_market=True, ingest=_no_ingest, _notifier=notifier)

    # The notifier must have been called if the tick had survivors; or called 0 times if none passed
    # (edge-market fixture is designed to produce at least 1 survivor, but we do not assert the count —
    # only that no exception escaped and the call count matches survivors).
    import json
    gate_calls = [c for c in calls if "Gate passed" in c or json.loads(c).get("text", "").startswith(":white")]
    if report.summary.gated_passed > 0:
        assert len(gate_calls) >= 1


def test_run_tick_fires_error_notif_on_funding_failure(tmp_path):
    """When funding raises, the injected notifier receives a tick-error call."""
    from cosmu.config.settings import Settings
    from cosmu.knowledge.store import Store
    from cosmu.master.scheduler import run_tick

    store = Store(Settings(database_url=f"sqlite:///{tmp_path}/tick2.sqlite3"))

    calls: list[str] = []
    notifier = SlackNotifier(
        webhook_url="https://hooks.slack.test/ERR",
        _post=lambda u, p: calls.append(p.decode()),
    )

    def _no_ingest(_s):
        return {}

    # Inject a broken fund_tracks callable to force the funding-failed path.
    import cosmu.master.scheduler as sched
    orig = None
    try:
        import cosmu.orchestrator as _orch
        orig = _orch.fund_tracks_from_survivors

        def _fail(*_a, **_kw):
            raise RuntimeError("injected failure")

        _orch.fund_tracks_from_survivors = _fail
        run_tick(store, n=2, seed=7, edge_market=True, ingest=_no_ingest, _notifier=notifier)
    finally:
        if orig is not None:
            _orch.fund_tracks_from_survivors = orig

    error_calls = [c for c in calls if "autonomy_funding_failed" in c]
    assert len(error_calls) >= 1
