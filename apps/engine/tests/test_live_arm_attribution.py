# /live/launch must refuse to arm a (symbol, venue) the forward proof was NOT earned on. A version is funded +
# paper-tested on ONE cell (the verdict-proven symbol); arming a different cell would launch real money on
# evidence that belongs elsewhere — the cardinal-sin on the money path. The guard runs BEFORE the eligibility
# gate, so a mismatch is rejected outright.

from __future__ import annotations

from dataclasses import dataclass

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.spine.venue import default_catalog


def _sol_binance_instrument() -> str:
    for i in default_catalog().instruments:
        if i.symbol == "SOLUSDT" and i.venue_id == "binance":
            return i.id
    raise AssertionError("catalog must have SOLUSDT@binance")


def _setup(tmp_path, monkeypatch):
    store = Store(Settings(
        database_url=f"sqlite:///{tmp_path}/arm.sqlite3", openrouter_api_key=None,
        binance_testnet_api_key="k", binance_testnet_api_secret="s",  # makes _venue_connected('binance') True
    ))
    sid = store.insert("strategies", {"name": "S", "thesis": "t", "origin": "finder", "created_at": "2026-06-17T00:00:00Z"})
    vid = store.insert("strategy_versions", {
        "strategy_id": sid, "spec": {"name": "S", "universe": {"asset_classes": ["crypto"], "venues": ["binance"]}},
        "generated_code": "", "code_hash": "h", "params": {}, "origin": "finder", "status": "paper",
        "created_at": "2026-06-17T00:00:00Z",
    })
    # The funded (proven) cell: a sim position on SOLUSDT@binance.
    store.insert("positions", {
        "strategy_version_id": vid, "instrument_id": _sol_binance_instrument(), "symbol": "SOLUSDT",
        "venue": "sim", "qty": "1", "avg_price": "100", "updated_at": "2026-06-17T00:00:00Z",
    })
    from fastapi.testclient import TestClient

    import cosmu.api.app as app_mod
    import cosmu.api.routers.live as live_mod
    monkeypatch.setattr(live_mod, "store", store)
    monkeypatch.setattr(live_mod, "settings", store.settings)
    return vid, TestClient(app_mod.app)


def test_arm_rejects_a_symbol_the_proof_was_not_earned_on(tmp_path, monkeypatch):
    """Funded on SOLUSDT; arming BTCUSDT must be refused with a clear mis-attribution reason, no status write."""
    vid, client = _setup(tmp_path, monkeypatch)
    r = client.post("/live/launch", json={"version_id": vid, "venue_id": "binance", "symbol": "BTCUSDT", "confirm": True}).json()
    assert r["armed"] is False
    assert "SOLUSDT" in r["reason"] and "earned on" in r["reason"]


def test_arm_guard_passes_for_the_proven_cell(tmp_path, monkeypatch):
    """Arming the SOLUSDT cell that WAS funded passes the attribution guard (it then meets the normal eligibility
    gate — stubbed here to a clean not-yet-proven verdict, so the response is NOT the mis-attribution reason)."""
    vid, client = _setup(tmp_path, monkeypatch)

    @dataclass
    class _V:
        eligible: bool = False
        reason: str = "not yet proven (stub)"
        paper_age_days: int = 0
        forward_ready: bool = False
        overridden: bool = False

    import cosmu.api.routers.live as live_mod
    import cosmu.master.live_eligibility as le
    monkeypatch.setattr(le, "live_eligibility_verdict", lambda *a, **k: _V())
    monkeypatch.setattr(le, "paper_clock_origin", lambda *a, **k: None)
    monkeypatch.setattr(live_mod, "_version_reference_bars", lambda *a, **k: [])

    r = client.post("/live/launch", json={"version_id": vid, "venue_id": "binance", "symbol": "SOLUSDT", "confirm": True}).json()
    assert "earned on" not in (r.get("reason") or "")  # the guard PASSED for the proven cell
