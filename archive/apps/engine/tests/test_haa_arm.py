# Deterministic offline test for the HAA (Keller Hybrid Asset Allocation, top-4) deploy-lane arm. Mirrors
# test_paa_daa_arm.py: mock the strategy validate (no market data) + the arm's _last_equity_close (fixed prices),
# route via the lane router on a lane="deploy" spec, and pin the crux — the FULL track capital is deployed (the
# BIL/IEF cash bucket absorbs the protective fraction, so a partially-defensive track never marks an undeployed
# remainder as a phantom loss). The conftest network guard fails any accidental real socket.

from __future__ import annotations

from decimal import Decimal

import pytest

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.research import equity_haa as haa
from cosmu.research import equity_haa_arm as haa_arm


def _store(tmp_path, name: str) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3"))


def _fake_v(weights: dict[str, float], *, deployable: bool = True) -> dict:
    full = haa.PerfStats(200, 0.5, 0.06, 0.10, 1.1, 0.09, 0.6)
    oos = haa.PerfStats(100, 0.2, 0.05, 0.10, 1.0, 0.09, 0.6)
    return {"deployable": deployable, "current_weights": weights, "full": full, "full_spy": full,
            "oos": oos, "oos_spy": oos, "window": [(2010, 1), (2020, 1)], "turnover": 60.0}


def _positions(store: Store, version_id: str) -> dict[str, Decimal]:
    rows = store.rows(
        "SELECT symbol, qty FROM positions WHERE strategy_version_id = ? AND CAST(qty AS REAL) != 0",
        (version_id,),
    )
    return {r["symbol"]: Decimal(str(r["qty"])) for r in rows}


@pytest.mark.parametrize("weights", [
    {s: 0.25 for s in ["SPY", "IWM", "EEM", "DBC"]},   # risk-on: top-4 offensive equal-weight
    {"BIL": 1.0},                                       # fully defensive: TIP canary down -> all cash
    {"BIL": 0.5, "SPY": 0.25, "TLT": 0.25},             # partial: a slot's own momentum non-positive -> cash
])
def test_haa_arm_deploys_full_capital(tmp_path, monkeypatch, weights):
    monkeypatch.setattr(haa, "validate", lambda **_: _fake_v(weights))
    monkeypatch.setattr(haa_arm, "_last_equity_close", lambda _sym: Decimal("100"))
    store = _store(tmp_path, "haa")

    res = haa_arm.arm(store)
    assert res["armed"]
    vid = res["version_id"]
    # every positive-weight symbol is held; the cash bucket is a real position, not an undeployed remainder
    pos = _positions(store, vid)
    assert set(pos) == {s for s, w in weights.items() if w > 0}
    # FULL capital deployed: sum(qty*price) ~= track capital (prices all 100)
    deployed = sum(q * Decimal("100") for q in pos.values())
    assert abs(deployed - haa_arm.TRACK_CAPITAL) <= haa_arm.TRACK_CAPITAL * Decimal("0.01")


def test_haa_arm_idempotent(tmp_path, monkeypatch):
    weights = {s: 0.25 for s in ["SPY", "IWM", "EEM", "DBC"]}
    monkeypatch.setattr(haa, "validate", lambda **_: _fake_v(weights))
    monkeypatch.setattr(haa_arm, "_last_equity_close", lambda _sym: Decimal("100"))
    store = _store(tmp_path, "haa2")
    v1 = haa_arm.arm(store)["version_id"]
    v2 = haa_arm.arm(store)["version_id"]
    assert v1 == v2  # re-arm reuses the version, never double-opens / resets the clock
    assert len(_positions(store, v1)) == 4


def test_haa_arm_aborts_when_not_deployable(tmp_path, monkeypatch):
    monkeypatch.setattr(haa, "validate", lambda **_: _fake_v({"SPY": 1.0}, deployable=False))
    store = _store(tmp_path, "haa3")
    res = haa_arm.arm(store)
    assert res["armed"] is False and res["reason"] == "not deployable"
