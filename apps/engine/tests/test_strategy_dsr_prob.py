# GET /strategies/{vid} surfaces the GATED deflated-Sharpe PROBABILITY (deflated_sharpe_prob) — the 0–1 value the
# 0.95 bar actually checks — recomputed from each backtest's persisted survival inputs, DISTINCT from the deflated-
# Sharpe RATIO (`deflated_sharpe`, a ranking number that can exceed 1.0). This is the data behind the sheet's "DSR
# confidence" row + the deterministic "why this stage" prose; it fixes the "0.98 — below the 0.95 bar" contradiction
# (a ratio compared to a probability bar). Recompute is read-only — it never re-gates. None when survival cols absent.

from __future__ import annotations

import cosmu.api.routers.strategies as strat_mod
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.scorer import BacktestMetrics, TrialStats, deflated_sharpe_prob


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/dsr_prob.sqlite3", openrouter_api_key=None))


def _client(monkeypatch, store):
    from fastapi.testclient import TestClient

    import cosmu.api.app as app_mod

    monkeypatch.setattr(strat_mod, "store", store)
    return TestClient(app_mod.app)


def _version(store: Store) -> str:
    sid = store.insert("strategies", {"name": "DSR-prob algo", "thesis": "t", "origin": "test", "created_at": "2026-06-17T00:00:00Z"})
    return store.insert("strategy_versions", {
        "strategy_id": sid, "spec": {"name": "s"}, "generated_code": "", "code_hash": "h", "params": {},
        "origin": "test", "status": "screened", "kind": "quant", "created_at": "2026-06-17T00:00:00Z",
    })


def _backtest(store: Store, vid: str, *, deflated_sharpe: str, passed: int, survival: bool, **extra) -> str:
    row = {
        "strategy_version_id": vid, "kind": "screen", "oos_return": "0.1", "sharpe": "1.0", "sortino": "1.0",
        "deflated_sharpe": deflated_sharpe, "max_dd": "0.05", "win_rate": "0.5", "num_trades": 358, "pbo": "0.42",
        "trials_counted": 6, "folds_positive": 4, "passed_gates": passed, "holdout_passed": 0,
        "created_at": "2026-06-17T00:00:00Z",
    }
    if survival:
        # DeFi-flow-like inputs: ratio ~0.98 but the GATED probability lands well below 0.95.
        row.update({"sharpe_per_obs": "0.04225765", "skew": "1.442218", "kurtosis": "22.259682", "n_obs": 1622})
    row.update(extra)
    return store.insert("backtests", row)


def test_dsr_prob_is_the_gated_probability_not_the_ratio(tmp_path, monkeypatch):
    """A backtest whose deflated-Sharpe RATIO is ~0.98 exposes a deflated_sharpe_prob WELL below it — the actual
    gated number — so the sheet never reads '0.98 below the 0.95 bar'. The value matches the scorer exactly."""
    store = _store(tmp_path)
    vid = _version(store)
    _backtest(store, vid, deflated_sharpe="0.979785", passed=0, survival=True)
    client = _client(monkeypatch, store)

    bt = client.get(f"/strategies/{vid}").json()["backtests"][0]
    expected = deflated_sharpe_prob(
        BacktestMetrics(
            oos_return="0.1", sharpe="1.0", sortino="1.0", max_drawdown="0.05", win_rate="0.5", num_trades=358,
            sharpe_per_obs="0.04225765", skew="1.442218", kurtosis="22.259682", n_obs=1622, pbo="0.42", trials_counted=6,
        ),
        TrialStats(count=6),
    )
    assert bt["deflated_sharpe"] == 0.979785            # the RATIO, unchanged
    assert bt["deflated_sharpe_prob"] == round(expected, 6)
    assert bt["deflated_sharpe_prob"] < 0.95            # the gated number is BELOW the bar — coherent with passed_gates=0
    assert bt["deflated_sharpe_prob"] < bt["deflated_sharpe"]


def test_dsr_prob_consistent_with_passed_gates(tmp_path, monkeypatch):
    """Where the probability is computable, prob ≥ 0.95 ⟺ passed_gates — so the displayed number never
    contradicts the verdict (the prod-wide invariant this fix relies on)."""
    store = _store(tmp_path)
    vid = _version(store)
    # Strong inputs (high per-obs Sharpe, long sample) → probability clears 0.95.
    _backtest(store, vid, deflated_sharpe="1.10", passed=1, survival=True,
              sharpe_per_obs="0.09", skew="0.2", kurtosis="4.0", n_obs=2000)
    client = _client(monkeypatch, store)

    bt = client.get(f"/strategies/{vid}").json()["backtests"][0]
    assert bt["deflated_sharpe_prob"] is not None
    assert (bt["deflated_sharpe_prob"] >= 0.95) == bool(bt["passed_gates"])


def test_dsr_prob_none_when_survival_columns_absent(tmp_path, monkeypatch):
    """Arm / pre-migration rows carry no survival inputs → deflated_sharpe_prob is None (the UI then falls back to
    the binary ≥/< 0.95 verdict off passed_gates rather than fabricating a number)."""
    store = _store(tmp_path)
    vid = _version(store)
    _backtest(store, vid, deflated_sharpe="0.864741", passed=1, survival=False)
    client = _client(monkeypatch, store)

    bt = client.get(f"/strategies/{vid}").json()["backtests"][0]
    assert bt["deflated_sharpe_prob"] is None
    assert bt["passed_gates"] is True                    # passed despite ratio < 0.95 — proving the ratio isn't the gate metric
