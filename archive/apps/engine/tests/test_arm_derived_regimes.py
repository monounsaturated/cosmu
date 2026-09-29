# Gate-integrity TIGHTENING: the ~12 deploy-lane arms used to hardcode proven_regimes=['bull','bear','chop'] in
# their track_opened payload, which NEUTRALIZED master/live_eligibility's regime gate — an arm claimed it works in
# EVERY trend regime for free, so a strategy that LOSES money in bear months could still clear the live-eligibility
# gate during a bear market. The fix DERIVES the passport from each arm's OWN per-regime net PnL
# (research._arm_regimes), reusing the same deterministic trend classifier (data.backtest._regime_labels via
# ml.regime) the live gate later re-derives from live closes.
#
# This file pins the core invariant: an arm with NEGATIVE bear-month PnL DROPS 'bear' from its proven_regimes (it
# must EARN each regime from positive per-regime PnL, never assume the full set). It exercises both the shared
# helper directly and the DAA arm end-to-end (the persisted track_opened payload), plus the perp self-relative
# (cash-benchmark) fallback. Offline-safe: market data + price fetch are mocked; no network.

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.research import equity_daa as daa
from cosmu.research import equity_daa_arm as daa_arm
from cosmu.research import perp_market_neutral as pmn
from cosmu.research._arm_regimes import (
    derive_proven_regimes,
    proven_regimes_from_validation,
)

# A clean, unambiguous trend benchmark: 18 strongly-up months then 18 strongly-down months. The 6-period trend
# look-back warm-up is absorbed inside each 18-month block, so the up block labels as 'bull' and the down block as
# 'bear' (with a short 'chop' warm-up/transition), giving a deterministic per-regime bucketing of the arm's PnL.
_BULL_THEN_BEAR_BENCH = [0.03] * 18 + [-0.03] * 18


# --------------------------------------------------------------------------- shared helper (direct)


def test_negative_bear_pnl_drops_bear():
    """An arm that LOSES money in the down (bear) stretch must NOT count 'bear' as proven."""
    net_loses_in_bear = [0.02] * 18 + [-0.02] * 18  # wins in the up half, loses in the down half
    proven = derive_proven_regimes(net_loses_in_bear, _BULL_THEN_BEAR_BENCH)
    assert "bear" not in proven, f"bear must be dropped when bear-month PnL is negative; got {proven}"
    assert "bull" in proven, f"bull was profitable and must be kept; got {proven}"


def test_positive_bear_pnl_earns_bear():
    """A defensive arm that is POSITIVE through the down stretch EARNS 'bear' from its own per-regime PnL."""
    net_wins_in_bear = [0.02] * 18 + [0.015] * 18  # positive in BOTH halves (a crisis-avoidance book)
    proven = derive_proven_regimes(net_wins_in_bear, _BULL_THEN_BEAR_BENCH)
    assert "bear" in proven, f"bear must be earned when bear-month PnL is positive; got {proven}"


def test_passport_is_not_the_free_full_set():
    """The whole point of the tightening: a losing-in-bear arm must NOT get the full ['bull','bear','chop'] set."""
    net_loses_in_bear = [0.02] * 18 + [-0.02] * 18
    proven = set(derive_proven_regimes(net_loses_in_bear, _BULL_THEN_BEAR_BENCH))
    assert proven != {"bull", "bear", "chop"}, "must not hand out the full passport for free"


def test_empty_returns_yield_empty_passport():
    """No realized returns -> no proven regime (fails the live-eligibility gate SAFELY, never the full set)."""
    assert derive_proven_regimes([], _BULL_THEN_BEAR_BENCH) == []


def test_self_relative_fallback_for_cash_benchmark():
    """A market-neutral / cash-benchmark book (no benchmark stream) classifies trend off its OWN cumulative path;
    a net stream that turns negative late drops the late (down-trend) regime from the passport."""
    # Positive then negative on its own equity curve -> the down-trend tail is not proven.
    proven = derive_proven_regimes([0.04] * 12 + [-0.05] * 12, None)
    assert "bear" not in proven, f"self-relative: a losing down-trend tail must not be proven; got {proven}"


# --------------------------------------------------------------------------- helper from a validate() verdict


def _daa_result(net: list[float], spy: list[float]) -> daa.DaaResult:
    n = len(net)
    return daa.DaaResult(
        months=[(2000 + i // 12, i % 12 + 1) for i in range(n)],
        weights=[{} for _ in range(n)],
        net_returns=net,
        gross_returns=net,
        spy_returns=spy,
        turnover=1.0,
        cash_fractions=[0.0] * n,
    )


def test_from_validation_pulls_result_streams():
    net_loses_in_bear = [0.02] * 18 + [-0.02] * 18
    v = {"result": _daa_result(net_loses_in_bear, _BULL_THEN_BEAR_BENCH)}
    proven = proven_regimes_from_validation(v)
    assert "bear" not in proven and "bull" in proven, proven


def test_from_validation_missing_result_fails_closed():
    assert proven_regimes_from_validation({}) == []
    assert proven_regimes_from_validation({"result": None}) == []


def test_from_validation_perp_net_self_relative():
    """The perp StratResult exposes `.net` (no benchmark) -> self-relative classification still applies."""
    res = pmn.StratResult(net=[0.04] * 12 + [-0.05] * 12, gross=[0.0] * 24, turnover=[0.0] * 24, times=[])
    proven = proven_regimes_from_validation({"result": res})
    assert "bear" not in proven, proven


# --------------------------------------------------------------------------- DAA arm end-to-end (persisted payload)


def _store(tmp_path, name: str) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/{name}.sqlite3"))


def _fake_v(weights: dict[str, float], net: list[float], spy: list[float]) -> dict:
    full = daa.PerfStats(len(net), 0.5, 0.06, 0.10, 1.1, 0.11, 0.6)
    oos = daa.PerfStats(len(net) // 2, 0.2, 0.05, 0.10, 1.0, 0.10, 0.6)
    return {
        "deployable": True,
        "current_weights": weights,
        "full": full,
        "oos": oos,
        "window": [(2000, 1), (2003, 1)],
        "turnover": 1.0,
        "result": _daa_result(net, spy),
    }


def _track_opened_payload(store: Store, version_id: str) -> dict:
    row = store.row(
        "SELECT payload FROM events WHERE kind='track_opened' AND ref_id = ? LIMIT 1", (version_id,)
    )
    payload = row["payload"]
    return payload if isinstance(payload, dict) else json.loads(payload)


def test_daa_arm_persists_derived_passport_dropping_bear(tmp_path, monkeypatch):
    """End-to-end: a DAA arm whose net PnL is NEGATIVE in bear months persists a track_opened passport WITHOUT
    'bear' — the hardcoded full set is gone, the live-eligibility regime gate is no longer neutralized."""
    weights = {s: 1.0 / 6 for s in ["SPY", "QQQ", "EFA", "EEM", "GLD", "TLT"]}
    net_loses_in_bear = [0.02] * 18 + [-0.02] * 18
    monkeypatch.setattr(daa, "validate", lambda **_: _fake_v(weights, net_loses_in_bear, _BULL_THEN_BEAR_BENCH))
    monkeypatch.setattr(daa_arm, "_last_equity_close", lambda _sym: Decimal("100"))

    store = _store(tmp_path, "daa_regimes")
    result = daa_arm.arm(store)
    assert result["armed"] is True

    proven = _track_opened_payload(store, result["version_id"])["proven_regimes"]
    assert "bear" not in proven, f"DAA arm must DROP bear from its passport on negative bear PnL; got {proven}"
    assert "bull" in proven, f"profitable bull regime must remain; got {proven}"
    assert set(proven) != {"bull", "bear", "chop"}, "must not persist the free full set"


def test_daa_arm_persists_bear_when_earned(tmp_path, monkeypatch):
    """A genuinely defensive DAA arm (positive net through bear months) EARNS 'bear' in its persisted passport."""
    weights = {"SHY": 1.0}
    net_wins_in_bear = [0.02] * 18 + [0.015] * 18
    monkeypatch.setattr(daa, "validate", lambda **_: _fake_v(weights, net_wins_in_bear, _BULL_THEN_BEAR_BENCH))
    monkeypatch.setattr(daa_arm, "_last_equity_close", lambda _sym: Decimal("100"))

    store = _store(tmp_path, "daa_regimes_earned")
    result = daa_arm.arm(store)
    proven = _track_opened_payload(store, result["version_id"])["proven_regimes"]
    assert "bear" in proven, f"defensive arm with positive bear PnL must EARN bear; got {proven}"
