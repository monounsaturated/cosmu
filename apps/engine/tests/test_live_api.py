# Live-trading API surface: /toggle/live requires confirm (and live stays OFF without it), /live/activate
# requires confirm + returns caps/eligible, /live/defund works, /live/positions has the right shape and reports
# mode "sim" with no keys. Secrets never appear in any response. No network, no lifespan: the module store +
# settings are pointed at a temp sqlite DB with no exchange keys (paper), following the existing API-test pattern.

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import cosmu.api.app as app_mod
from cosmu.config.settings import PAPER_MIN_DAYS, LiveSettings, Settings
from cosmu.knowledge.store import Store, utcnow


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/live_api.sqlite3",
        binance_api_key=None,
        binance_api_secret=None,
        binance_testnet_api_key=None,
        binance_testnet_api_secret=None,
        live=LiveSettings(),
    )
    store = Store(settings)
    monkeypatch.setattr(app_mod, "settings", settings)
    monkeypatch.setattr(app_mod, "store", store)
    return TestClient(app_mod.app)  # no `with` → lifespan backtest does not run


def test_toggle_requires_confirm_and_stays_off(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    body = c.post("/toggle/live", json={"enabled": True, "confirm": False}).json()
    assert body["enabled"] is False and body["requires_confirm"] is True
    assert c.post("/toggle/live", json={"enabled": True, "confirm": True}).json()["enabled"] is True


def test_live_venues_jurisdiction_and_honest_connection(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)  # FR default jurisdiction, no exchange keys
    body = c.get("/live/venues").json()
    assert body["jurisdiction"] == "FR"
    by_id = {v["id"]: v for v in body["venues"]}
    assert "binance" in by_id  # Binance is live-legal in FR
    assert all(v["live_legal"] for v in body["venues"])  # the set is only legal-from-jurisdiction venues
    assert by_id["binance"]["connected"] is False  # no keys wired → honestly "not connected"
    assert all(v["deployed_usd"] == 0.0 for v in body["venues"])  # no positions → nothing at risk
    assert body["total_deployed_usd"] == 0.0
    assert "secret" not in c.get("/live/venues").text.lower()  # no secret ever leaks


def test_portfolio_summary_empty_state_never_labels_sim_as_live(tmp_path, monkeypatch):
    # No live position → has_live False, every live_* money figure is None (renders "—"), and sim_equity
    # mirrors the bankroll. The ribbon can NEVER show SIM capital under a live label.
    c = _client(tmp_path, monkeypatch)
    body = c.get("/portfolio/summary").json()
    assert body["has_live"] is False
    assert body["live_invested"] is None and body["live_free"] is None and body["live_pnl_net"] is None
    assert body["live_equity"] is None  # no live snapshot is ever fabricated
    assert body["sim_equity"] == 100000.0 and body["live_mode"] == "sim"
    assert body["positions_count_live"] == 0


def test_portfolio_summary_live_split_excludes_sim(tmp_path, monkeypatch):
    # A position routed live (venue != 'sim') drives the live figures; a SIM position never leaks in.
    c = _client(tmp_path, monkeypatch)
    store = app_mod.store
    store.insert("positions", {"strategy_version_id": "v-live", "instrument_id": "i1", "symbol": "BTCUSDT",
                                "venue": "binance", "qty": "0.1", "avg_price": "20000", "realized_pnl": "100",
                                "last_was_loss": 0, "updated_at": utcnow()})
    store.insert("positions", {"strategy_version_id": "v-sim", "instrument_id": "i2", "symbol": "ETHUSDT",
                                "venue": "sim", "qty": "5", "avg_price": "3000", "realized_pnl": "999",
                                "last_was_loss": 0, "updated_at": utcnow()})
    body = c.get("/portfolio/summary").json()
    assert body["has_live"] is True and body["positions_count_live"] == 1
    assert body["live_invested"] == 2000.0  # 0.1 * 20000 — the SIM 5*3000 is excluded
    assert body["live_realized"] == 100.0    # the SIM realized 999 is excluded
    assert body["live_free"] == body["live_global_cap"] - 2000.0  # budget headroom, not exchange cash


def test_live_venues_excludes_jurisdiction_restricted(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    settings = Settings(database_url=f"sqlite:///{tmp_path}/live_us.sqlite3", live_jurisdiction="US", live=LiveSettings())
    monkeypatch.setattr(app_mod, "settings", settings)
    monkeypatch.setattr(app_mod, "store", Store(settings))
    ids = {v["id"] for v in TestClient(app_mod.app).get("/live/venues").json()["venues"]}
    assert "binance" not in ids  # Binance is NOT live-legal for US → must not appear as available
    assert "kraken" in ids       # US-legal crypto venue still shows


def test_jurisdiction_pick_persists_and_reshapes_venues(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    j = c.get("/live/jurisdictions").json()
    assert j["current"] == "FR" and {o["code"] for o in j["options"]} >= {"FR", "US", "AE", "NL", "GB"}
    # picking US is audited + persisted (event-backed, no schema change) and reshapes the legal venue set
    assert c.post("/live/jurisdiction", json={"code": "US"}).json()["current"] == "US"
    venues = c.get("/live/venues").json()
    assert venues["jurisdiction"] == "US"
    ids = {v["id"] for v in venues["venues"]}
    assert "binance" not in ids and "kraken" in ids  # Binance is US-restricted; Kraken is US-legal
    assert c.post("/live/jurisdiction", json={"code": "ZZ"}).status_code == 400  # unknown code rejected


def test_activate_requires_confirm(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    body = c.post("/live/activate", json={"per_strategy_cap": 1000, "global_cap": 5000, "max_daily_loss": 200, "confirm": False}).json()
    assert body["armed"] is False and body["reason"]


def test_activate_arms_and_returns_caps_and_eligible(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    body = c.post("/live/activate", json={"per_strategy_cap": 1000, "global_cap": 5000, "max_daily_loss": 200, "confirm": True}).json()
    assert body["armed"] is True
    assert body["caps"] == {"per_strategy_cap": 1000.0, "global_cap": 5000.0, "max_daily_loss": 200.0}
    assert isinstance(body["eligible"], list)


def test_live_positions_shape_and_paper_mode_without_keys(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    body = c.get("/live/positions").json()
    assert set(body) == {"armed", "mode", "daily_loss", "caps", "positions"}
    assert body["mode"] == "sim"  # no keys -> sim
    assert body["armed"] is False
    assert set(body["caps"]) == {"per_strategy_cap", "global_cap", "max_daily_loss"}
    assert isinstance(body["positions"], list)


def test_defund_all_ok(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    body = c.post("/live/defund", json={"scope": "all"}).json()
    assert body["ok"] is True and isinstance(body["defunded"], list)


def test_no_secrets_in_responses(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    for path in ("/live/positions", "/overview"):
        text = c.get(path).text.lower()
        assert "secret" not in text


# ── Hard paper live-eligibility gate (P1) ────────────────────────────────────────────────
# /live/activate now excludes too-young survivors from `eligible`; /live/launch enforces the gate and is the
# ONLY path that writes status='live'. Offline the engine reads regime 'chop', so seeds prove 'chop' to isolate
# the PAPER precondition (the regime gate is exercised in test_ml_regime / test_live_eligibility_gate).


def _client_with_keys(tmp_path, monkeypatch):
    """A client whose Binance venue IS configured (keys present) so /live/launch reaches the eligibility gate
    rather than stopping at the venue key-gate. Returns the store handle for seeding + status assertions."""
    from fastapi.testclient import TestClient

    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/live_gate.sqlite3",
        binance_api_key="k", binance_api_secret="s",
        binance_testnet_api_key=None, binance_testnet_api_secret=None,
        live=LiveSettings(),
    )
    store = Store(settings)
    monkeypatch.setattr(app_mod, "settings", settings)
    monkeypatch.setattr(app_mod, "store", store)
    # Isolate the PAPER precondition: pin the regime gate open here so the ambient offline regime
    # (not 'chop' anymore) can't block these tests. The regime gate is exercised in test_ml_regime /
    # test_live_eligibility_gate; here we assert only the paper maturity/override behaviour.
    monkeypatch.setattr("cosmu.master.live_eligibility.regime_eligible", lambda *a, **k: True)
    return TestClient(app_mod.app), store


def _seed_survivor(store: Store, vid: str, *, age_days: float, net_pct: float, proven=("chop",)) -> None:
    """A gate-passed paper survivor WITH a track: strategies + strategy_versions(paper) +
    backtests(passed_gates=1) + a tracks row (net-of-fee return) + a track_opened event whose ts is the
    paper clock origin (backdated `age_days`) carrying the proven-regime passport."""
    now = datetime.now(tz=UTC)
    sid = store.insert("strategies", {"name": f"s-{vid}", "thesis": "t", "origin": "seed", "created_at": utcnow()})
    store.insert(
        "strategy_versions",
        {
            "id": vid, "strategy_id": sid, "parent_id": None, "spec": "{}", "generated_code": "x",
            "code_hash": "h", "params": "{}", "mutation_operator": None, "mutation_rationale": None,
            "origin": "seed", "status": "paper", "created_at": utcnow(), "killed_at": None, "kill_reason": None,
        },
    )
    store.insert(
        "backtests",
        {
            "strategy_version_id": vid, "kind": "screen", "oos_return": "0.04", "sharpe": "1", "sortino": "1",
            "deflated_sharpe": "0.6", "max_dd": "0.1", "win_rate": "0.5", "num_trades": 40, "pbo": "0.2",
            "trials_counted": 1, "regime_label": "mixed", "folds_positive": 4,
            "passed_gates": 1, "holdout_passed": 1, "created_at": utcnow(),
        },
    )
    store.insert(
        "tracks",
        {
            "strategy_version_id": vid, "starting_capital": "100000",
            "equity": str(100000 * (1 + net_pct / 100)), "return_pct": str(net_pct), "updated_at": utcnow(),
        },
    )
    ts = (now - timedelta(days=age_days)).isoformat()
    with store.batch() as w:
        w.execute(
            "INSERT INTO events(ts, actor, kind, ref_type, ref_id, payload) VALUES (?, 'master', 'track_opened', 'strategy_version', ?, ?)",
            (ts, vid, json.dumps({"proven_regimes": list(proven)})),
        )


def _launch_body(vid: str, **over) -> dict:
    body = {
        "version_id": vid, "venue_id": "binance", "symbol": "BTCUSDT", "budget": 100,
        "per_strategy_cap": 100, "global_cap": 1000, "max_daily_loss": 50, "confirm": True,
    }
    body.update(over)
    return body


def test_activate_eligible_excludes_too_young_includes_matured(tmp_path, monkeypatch):
    c, store = _client_with_keys(tmp_path, monkeypatch)
    _seed_survivor(store, "v-young", age_days=1, net_pct=4.0)                      # 0-day clock
    _seed_survivor(store, "v-ok", age_days=PAPER_MIN_DAYS + 5, net_pct=4.0)  # matured + net-positive

    body = c.post("/live/activate", json={"per_strategy_cap": 1000, "global_cap": 5000, "max_daily_loss": 200, "confirm": True}).json()
    assert body["armed"] is True
    ids = {e["version_id"] for e in body["eligible"]}
    assert "v-ok" in ids        # matured net-positive in-regime survivor IS armable
    assert "v-young" not in ids  # a too-young strategy is NOT eligible (the new hard precondition)


def test_launch_arms_and_writes_status_live_for_matured(tmp_path, monkeypatch):
    c, store = _client_with_keys(tmp_path, monkeypatch)
    _seed_survivor(store, "v-ok", age_days=PAPER_MIN_DAYS + 5, net_pct=4.0)

    body = c.post("/live/launch", json=_launch_body("v-ok")).json()
    assert body["armed"] is True
    assert body["readiness"] == "proven"
    assert body["overridden"] is False
    # Launch is the ONLY path that writes status='live'.
    assert store.row("SELECT status FROM strategy_versions WHERE id = ?", ("v-ok",))["status"] == "live"


def test_launch_refuses_unproven_without_override(tmp_path, monkeypatch):
    c, store = _client_with_keys(tmp_path, monkeypatch)
    _seed_survivor(store, "v-young", age_days=1, net_pct=4.0)

    body = c.post("/live/launch", json=_launch_body("v-young")).json()
    assert body["armed"] is False
    assert body["readiness"] == "not yet proven"
    assert "paper not proven" in body["reason"]
    # Refused -> status must NOT have advanced to live.
    assert store.row("SELECT status FROM strategy_versions WHERE id = ?", ("v-young",))["status"] == "paper"


def test_launch_override_arms_unproven_and_logs_warning(tmp_path, monkeypatch):
    c, store = _client_with_keys(tmp_path, monkeypatch)
    _seed_survivor(store, "v-young", age_days=1, net_pct=4.0)

    body = c.post("/live/launch", json=_launch_body("v-young", override_paper=True)).json()
    assert body["armed"] is True          # override waives the paper precondition
    assert body["overridden"] is True
    assert store.row("SELECT status FROM strategy_versions WHERE id = ?", ("v-young",))["status"] == "live"
    # The explicit, logged warning the owner-pending escape hatch must leave behind.
    warn = store.row("SELECT payload FROM events WHERE kind = 'live_override_launch' AND ref_id = ?", ("v-young",))
    assert warn is not None
