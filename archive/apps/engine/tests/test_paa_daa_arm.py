# Deterministic offline tests for the two NEW deploy-lane documented TAA strategies:
#   - PAA (Keller Protective Asset Allocation, PAA1 top-6)  -> equity_paa.py / equity_paa_arm.py
#   - DAA (Keller Defensive Asset Allocation, DAA top-6)    -> equity_daa.py / equity_daa_arm.py
#
# These mirror the pattern of the existing GEM/VAA/GTAA arms: route via master/lane_router.evaluate_by_lane on a
# lane="deploy" spec, register the SAME control-plane rows the finder writes, and open the held SIM positions sized to
# the strategy's target weights. The crux pinned here (the SHY-cash partial-investment fix, generalized to a weighted
# book): the FULL track capital is deployed (the safe/defensive bucket absorbs the protective fraction), so a partially-
# defensive track never marks an undeployed remainder as a phantom loss.
#
# Offline-safe: each test mocks the strategy module's validate (no market data / no network) and the arm's
# _last_equity_close (fixed prices). The conftest network guard would fail any accidental real socket.

from __future__ import annotations

from decimal import Decimal

import pytest

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.research import equity_daa as daa
from cosmu.research import equity_daa_arm as daa_arm
from cosmu.research import equity_paa as paa
from cosmu.research import equity_paa_arm as paa_arm


def _store(tmp_path, name: str) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3"))


def _fake_v(mod, weights: dict[str, float]) -> dict:
    """A deployable validation verdict carrying the given target weights. Stats are plausible placeholders — the arm
    only reads `deployable`, `current_weights`, `oos.total_return`, `full.ann_sharpe`, `window`, and `turnover`."""
    full = mod.PerfStats(200, 0.5, 0.06, 0.10, 1.1, 0.11, 0.6)
    oos = mod.PerfStats(100, 0.2, 0.05, 0.10, 1.0, 0.10, 0.6)
    return {
        "deployable": True,
        "current_weights": weights,
        "full": full,
        "oos": oos,
        "window": [(2010, 1), (2020, 1)],
        "turnover": 8.0,
    }


def _positions(store: Store, version_id: str) -> dict[str, Decimal]:
    rows = store.rows(
        "SELECT symbol, qty FROM positions WHERE strategy_version_id = ? AND CAST(qty AS REAL) != 0",
        (version_id,),
    )
    return {r["symbol"]: Decimal(str(r["qty"])) for r in rows}


# --------------------------------------------------------------------------- PAA arm: full-capital deployment


@pytest.mark.parametrize("weights", [
    # risk-on: top-6 risk assets equal-weight, no protective fraction (BF=0) -> sums to 1.0.
    {s: 1.0 / 6 for s in ["SPY", "QQQ", "EFA", "EEM", "GLD", "LQD"]},
    # half-defensive: 50% safe asset (IEF) + 50% across 3 risk assets.
    {"IEF": 0.5, "SPY": 0.5 / 3, "QQQ": 0.5 / 3, "GLD": 0.5 / 3},
    # fully defensive: everything in the safe asset.
    {"IEF": 1.0},
])
def test_paa_arm_deploys_full_capital(tmp_path, monkeypatch, weights):
    monkeypatch.setattr(paa, "validate", lambda **_: _fake_v(paa, weights))
    monkeypatch.setattr(paa_arm, "_last_equity_close", lambda _sym: Decimal("100"))

    store = _store(tmp_path, "paa")
    result = paa_arm.arm(store)
    assert result["armed"] is True
    version_id = result["version_id"]

    pos = _positions(store, version_id)
    # Every target-weighted symbol is held.
    for sym, w in weights.items():
        if w > 0:
            assert sym in pos, f"target symbol {sym} not held"

    # The crux: the FULL track capital is deployed (weights sum to 1.0), so qty*price ~ TRACK_CAPITAL.
    deployed = sum(q * Decimal("100") for q in pos.values())
    assert abs(deployed - paa_arm.TRACK_CAPITAL) <= Decimal("1"), (
        f"deployed {deployed} != track capital {paa_arm.TRACK_CAPITAL} (phantom partial-deployment)"
    )

    # And the marked return is honest (~0% at t0, never a phantom negative).
    paa_arm.mark(store)
    track = store.row("SELECT return_pct FROM tracks WHERE strategy_version_id = ?", (version_id,))
    ret = Decimal(str(track["return_pct"]))
    assert abs(ret) < Decimal("1.0"), f"phantom mark: return_pct={ret} (expected ~0)"


def test_paa_arm_idempotent(tmp_path, monkeypatch):
    weights = {s: 1.0 / 6 for s in ["SPY", "QQQ", "EFA", "EEM", "GLD", "LQD"]}
    monkeypatch.setattr(paa, "validate", lambda **_: _fake_v(paa, weights))
    monkeypatch.setattr(paa_arm, "_last_equity_close", lambda _sym: Decimal("100"))
    store = _store(tmp_path, "paa_idem")
    r1 = paa_arm.arm(store)
    r2 = paa_arm.arm(store)
    assert r1["version_id"] == r2["version_id"]  # re-arm reuses the version (clock not reset)
    # Exactly one strategy + one version + one track + one track_opened event.
    assert store.row("SELECT COUNT(*) c FROM strategies WHERE name = ?", (paa_arm.STRATEGY_NAME,))["c"] == 1
    assert store.row("SELECT COUNT(*) c FROM tracks WHERE strategy_version_id = ?", (r1["version_id"],))["c"] == 1
    n_opened = store.row(
        "SELECT COUNT(*) c FROM events WHERE kind='track_opened' AND ref_id = ?", (r1["version_id"],)
    )["c"]
    assert n_opened == 1


def test_paa_arm_lane_is_deploy(tmp_path, monkeypatch):
    weights = {"IEF": 1.0}
    monkeypatch.setattr(paa, "validate", lambda **_: _fake_v(paa, weights))
    monkeypatch.setattr(paa_arm, "_last_equity_close", lambda _sym: Decimal("100"))
    store = _store(tmp_path, "paa_lane")
    result = paa_arm.arm(store)
    spec = store.row(
        "SELECT spec FROM strategy_versions WHERE id = ?", (result["version_id"],)
    )["spec"]
    spec = spec if isinstance(spec, dict) else __import__("json").loads(spec)
    assert spec["lane"] == "deploy", "PAA must route through the documented-deploy lane, not the 0.95 gate"
    assert paa_arm._routing_spec().lane == "deploy"


# --------------------------------------------------------------------------- DAA arm: full-capital deployment


@pytest.mark.parametrize("weights", [
    # risk-on: top-6 risk assets equal-weight, no protective fraction (b=0) -> sums to 1.0.
    {s: 1.0 / 6 for s in ["SPY", "QQQ", "EFA", "EEM", "GLD", "TLT"]},
    # half-defensive: one bad canary -> 50% into best defensive (SHY) + 50% across 6 risk assets.
    {"SHY": 0.5, **{s: 0.5 / 6 for s in ["SPY", "QQQ", "EFA", "EEM", "GLD", "TLT"]}},
    # fully defensive: both canaries bad -> everything in the best defensive asset.
    {"SHY": 1.0},
])
def test_daa_arm_deploys_full_capital(tmp_path, monkeypatch, weights):
    monkeypatch.setattr(daa, "validate", lambda **_: _fake_v(daa, weights))
    monkeypatch.setattr(daa_arm, "_last_equity_close", lambda _sym: Decimal("100"))

    store = _store(tmp_path, "daa")
    result = daa_arm.arm(store)
    assert result["armed"] is True
    version_id = result["version_id"]

    pos = _positions(store, version_id)
    for sym, w in weights.items():
        if w > 0:
            assert sym in pos, f"target symbol {sym} not held"

    deployed = sum(q * Decimal("100") for q in pos.values())
    assert abs(deployed - daa_arm.TRACK_CAPITAL) <= Decimal("1"), (
        f"deployed {deployed} != track capital {daa_arm.TRACK_CAPITAL} (phantom partial-deployment)"
    )

    daa_arm.mark(store)
    track = store.row("SELECT return_pct FROM tracks WHERE strategy_version_id = ?", (version_id,))
    ret = Decimal(str(track["return_pct"]))
    assert abs(ret) < Decimal("1.0"), f"phantom mark: return_pct={ret} (expected ~0)"


def test_daa_arm_lane_is_deploy(tmp_path, monkeypatch):
    weights = {"SHY": 1.0}
    monkeypatch.setattr(daa, "validate", lambda **_: _fake_v(daa, weights))
    monkeypatch.setattr(daa_arm, "_last_equity_close", lambda _sym: Decimal("100"))
    store = _store(tmp_path, "daa_lane")
    result = daa_arm.arm(store)
    spec = store.row(
        "SELECT spec FROM strategy_versions WHERE id = ?", (result["version_id"],)
    )["spec"]
    spec = spec if isinstance(spec, dict) else __import__("json").loads(spec)
    assert spec["lane"] == "deploy", "DAA must route through the documented-deploy lane, not the 0.95 gate"
    assert daa_arm._routing_spec().lane == "deploy"


def test_arm_aborts_when_not_deployable(tmp_path, monkeypatch):
    """If the deployment bar fails, the arm must NOT register anything (no track, no positions)."""
    monkeypatch.setattr(paa, "validate", lambda **_: {"deployable": False})
    store = _store(tmp_path, "paa_abort")
    result = paa_arm.arm(store)
    assert result["armed"] is False
    assert store.row("SELECT COUNT(*) c FROM strategies WHERE name = ?", (paa_arm.STRATEGY_NAME,))["c"] == 0
