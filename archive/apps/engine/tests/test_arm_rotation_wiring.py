# Wiring proof for the P0 rotation fix: every deploy-lane arm must call the shared close_stale_legs
# (research/arm_rotation.py) AFTER its Portfolio is constructed and BEFORE any held-check / new fill, so a strategy
# that ROTATES (GEM SPY→AGG, a GTAA sleeve below its SMA, the VAA/DAA canary flip, a weights reshuffle) closes the
# old leg instead of stacking the new one on top (double capital, polluted forward P&L).
#
# Coverage strategy (per pattern, not per arm):
#   1. GEM end-to-end — the single-signal pattern: arm with signal A, re-arm with signal B, assert A closed @ qty 0,
#      B open, and a rotation_closed event booked.
#   2. PAA end-to-end — the weights-dict pattern (same seam test_paa_daa_arm.py already proves stable).
#   3. inspect-based wiring assertion for ALL TEN equity arms — pragmatic proof the call exists in every arm().
#   4. perp_market_neutral_arm is honestly SKIPPED: it holds NO per-symbol SIM positions (its track is a return-stream
#      trajectory), so there is nothing for close_stale_legs to close — pinned so a future per-leg rewrite trips here.
#
# Offline-safe: tests mock the strategy module's validate (no market data) and the arm's _last_equity_close (fixed
# prices). The conftest network guard fails any accidental real socket.

from __future__ import annotations

import importlib
import inspect
from decimal import Decimal

import pytest

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.research import equity_dual_momentum as gem
from cosmu.research import equity_dual_momentum_arm as gem_arm
from cosmu.research import equity_paa as paa
from cosmu.research import equity_paa_arm as paa_arm
from cosmu.research import perp_market_neutral_arm as perp_arm

# Every equity arm registers per-symbol SIM legs for a rotation strategy — ALL must wire the shared rotation close.
ROTATION_ARM_MODULES = [
    "cosmu.research.equity_dual_momentum_arm",
    "cosmu.research.equity_dual_momentum_qqq_arm",
    "cosmu.research.equity_accel_dual_momentum_arm",
    "cosmu.research.equity_vaa_arm",
    "cosmu.research.equity_faber_gtaa_arm",
    "cosmu.research.equity_tsmom_trend_arm",
    "cosmu.research.equity_sector_rotation_arm",
    "cosmu.research.equity_risk_parity_arm",
    "cosmu.research.equity_paa_arm",
    "cosmu.research.equity_daa_arm",
]


def _store(tmp_path, name: str) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3", openrouter_api_key=None))


def _qty(store: Store, version_id: str, symbol: str) -> Decimal:
    row = store.row(
        "SELECT qty FROM positions WHERE strategy_version_id = ? AND symbol = ?", (version_id, symbol)
    )
    return Decimal(str(row["qty"])) if row else Decimal("0")


def _fake_gem_v(signal: str) -> dict:
    """A deployable GEM verdict carrying the given current signal. Stats are plausible placeholders — the arm only
    reads deployable / current_signal / full.ann_sharpe / oos.total_return / full.max_dd / win_rate / window / switches."""
    full = gem.PerfStats(200, 0.5, 0.06, 0.10, 0.9, 0.25, 0.6)
    oos = gem.PerfStats(100, 0.2, 0.05, 0.10, 0.8, 0.20, 0.6)
    return {"deployable": True, "current_signal": signal, "full": full, "oos": oos,
            "window": ((2010, 1), (2020, 1)), "switches": 12}


def _fake_paa_v(weights: dict[str, float]) -> dict:
    full = paa.PerfStats(200, 0.5, 0.06, 0.10, 1.1, 0.11, 0.6)
    oos = paa.PerfStats(100, 0.2, 0.05, 0.10, 1.0, 0.10, 0.6)
    return {"deployable": True, "current_weights": weights, "full": full, "oos": oos,
            "window": [(2010, 1), (2020, 1)], "turnover": 8.0}


# ------------------------------------------------------------------ 1. single-signal pattern, end-to-end (GEM)


def test_gem_rearm_closes_stale_leg_and_opens_new_signal(tmp_path, monkeypatch):
    store = _store(tmp_path, "gem_rot")
    monkeypatch.setattr(gem_arm, "_last_equity_close", lambda _sym: Decimal("100"))

    # Month 1: GEM signals SPY — the arm opens the SPY leg.
    monkeypatch.setattr(gem, "validate", lambda **_: _fake_gem_v("SPY"))
    r1 = gem_arm.arm(store)
    assert r1["armed"] is True
    version_id = r1["version_id"]
    assert _qty(store, version_id, "SPY") > 0
    assert r1["rotation"] == {"closed": [], "deferred": []}  # nothing stale on first arm

    # Month 2: the signal ROTATES SPY→AGG. The stale SPY leg must close BEFORE the AGG leg opens.
    monkeypatch.setattr(gem, "validate", lambda **_: _fake_gem_v("AGG"))
    r2 = gem_arm.arm(store)
    assert r2["version_id"] == version_id  # same track — the clock is never reset by a rotation
    assert [c["symbol"] for c in r2["rotation"]["closed"]] == ["SPY"]
    assert _qty(store, version_id, "SPY") == 0, "stale SPY leg left open — double capital deployed"
    assert _qty(store, version_id, "AGG") > 0, "new AGG leg not opened"
    assert store.row(
        "SELECT id FROM events WHERE kind = 'rotation_closed' AND ref_id = ?", (version_id,)
    ) is not None, "rotation close must be audited as a rotation_closed event"


# ------------------------------------------------------------------ 2. weights-dict pattern, end-to-end (PAA)


def test_paa_rearm_closes_legs_dropped_from_target_weights(tmp_path, monkeypatch):
    store = _store(tmp_path, "paa_rot")
    monkeypatch.setattr(paa_arm, "_last_equity_close", lambda _sym: Decimal("100"))

    # Month 1: risk-on, two equity buckets held.
    monkeypatch.setattr(paa, "validate", lambda **_: _fake_paa_v({"SPY": 0.5, "QQQ": 0.5}))
    r1 = paa_arm.arm(store)
    version_id = r1["version_id"]
    assert _qty(store, version_id, "SPY") > 0 and _qty(store, version_id, "QQQ") > 0

    # Month 2: breadth collapses — fully defensive (IEF only). Both equity legs must close, IEF opens.
    monkeypatch.setattr(paa, "validate", lambda **_: _fake_paa_v({"IEF": 1.0}))
    r2 = paa_arm.arm(store)
    assert r2["version_id"] == version_id
    assert sorted(c["symbol"] for c in r2["rotation"]["closed"]) == ["QQQ", "SPY"]
    assert _qty(store, version_id, "SPY") == 0 and _qty(store, version_id, "QQQ") == 0
    assert _qty(store, version_id, "IEF") > 0


# ------------------------------------------------------------------ 3. every arm wires the shared rotation close


@pytest.mark.parametrize("modname", ROTATION_ARM_MODULES)
def test_every_rotation_arm_calls_close_stale_legs(modname):
    mod = importlib.import_module(modname)
    src = inspect.getsource(mod.arm)
    assert "close_stale_legs(" in src, f"{modname}.arm() does not call close_stale_legs — stale legs stack on rotation"
    assert "keep_symbols" in src, f"{modname}.arm() must pass its full CURRENT target set as keep_symbols"
    # The rotation result must surface in the arm's summary so callers/audits see what was closed/deferred.
    assert '"rotation": rotation' in src, f"{modname}.arm() must return the rotation summary"


# ------------------------------------------------------------------ 4. perp arm: honestly out of scope


def test_perp_market_neutral_arm_has_no_per_symbol_legs_to_rotate():
    """The perp-momentum-neutral track is a RETURN-STREAM trajectory (scope='track' snapshots rewritten from the
    validated net stream) — it opens NO per-symbol SIM positions, so there is nothing for close_stale_legs to close.
    Pinned: if a per-leg Portfolio ever appears here, this trips and the long-spot legs must be wired (the SHORT legs
    can NOT reuse the helper as-is — it closes with side=-1, a short held as negative qty needs side=+1)."""
    src = inspect.getsource(perp_arm)
    assert "Portfolio(" not in src and "apply_fill" not in src, (
        "perp_market_neutral_arm now holds per-symbol positions — wire close_stale_legs for its long legs "
        "and handle the short side separately"
    )
