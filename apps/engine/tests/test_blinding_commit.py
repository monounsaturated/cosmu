# BLINDING-COMMIT — the hidden-box (particle-physics) discipline that makes the holdout blind by CONSTRUCTION.
# A version's RECIPE hash is frozen before its untouched holdout/forward set is first read; the deterministic Gate
# then REFUSES to score it if the recipe drifted past that commit AFTER the box was opened, until a FRESH commit
# re-blinds it (which re-arms the spent holdout). These pin: (1) recipe_hash moves on an exit/entry/param edit but
# NOT on a routing relabel; (2) the required scenario — backfill a strategy, read its holdout, edit the exit rule,
# and the Gate refuses to re-score it without a fresh commit; (3) fail-OPEN when there is nothing to protect;
# (4) a re-blind re-arms the one-shot holdout; (5) the forward "read" (a track_opened event) also opens the box.

from __future__ import annotations

import datetime as dt
import json

import pytest

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.blinding import (
    BlindingLedger,
    BlindingViolation,
    assert_scoreable,
    box_opened,
    recipe_hash,
)
from cosmu.master.holdout import HoldoutLedger

_TS = dt.datetime(2026, 1, 1, tzinfo=dt.UTC).isoformat()


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/blind.sqlite3"))


def _spec(*, take_profit: float = 0.10, lane: str = "gate") -> dict:
    """A minimal recipe-shaped spec dict: a routing label (lane), prose (name/rationale), an entry condition, and
    an exit rule (the thing the required test edits). Stored verbatim on the version row."""
    return {
        "name": "blinding-probe",
        "rationale": "pin the blinding discipline",
        "lane": lane,
        "kind": "quant",
        "strategy_kind": "indicator",
        "universe": {"venues": ["binance"], "asset_classes": ["crypto"]},
        "entry": [{"feature": "rsi", "op": "lt", "value_ref": "rsi_floor"}],
        "exit": {"stop_loss": 0.05, "take_profit": take_profit, "signal_exits": []},
    }


def _seed_version(store: Store, spec: dict, params: dict, *, code_hash: str = "h1") -> str:
    sid = store.insert("strategies", {"name": "probe", "thesis": "t", "origin": "finder", "created_at": _TS})
    return store.insert(
        "strategy_versions",
        {"strategy_id": sid, "parent_id": None, "spec": spec, "generated_code": "", "code_hash": code_hash,
         "params": params, "mutation_operator": None, "mutation_rationale": "x", "origin": "finder",
         "status": "screened", "created_at": _TS, "killed_at": None, "kill_reason": None},
    )


def _edit_spec(store: Store, version_id: str, spec: dict) -> None:
    """The THEATER GAP, reproduced: mutate a version's spec IN PLACE (same version_id keeps its spent holdout)."""
    store.rows("UPDATE strategy_versions SET spec = ? WHERE id = ?", (json.dumps(spec, sort_keys=True), version_id))


# --- recipe_hash: the scientific recipe, not the label -------------------------------------------------------

def test_recipe_hash_moves_on_exit_rule_edit():
    params = {"rsi_floor": 30.0}
    base = recipe_hash(_spec(take_profit=0.10), params)
    edited = recipe_hash(_spec(take_profit=0.25), params)  # exit take_profit changed
    assert base != edited, "editing the exit rule must change the recipe hash"


def test_recipe_hash_moves_on_param_refit():
    spec = _spec()
    base = recipe_hash(spec, {"rsi_floor": 30.0})
    refit = recipe_hash(spec, {"rsi_floor": 35.0})  # a silent re-fit of a fitted knob
    assert base != refit, "re-fitting a param must change the recipe hash"


def test_recipe_hash_ignores_routing_labels_and_prose():
    params = {"rsi_floor": 30.0}
    base = recipe_hash(_spec(lane="gate"), params)
    relabel = _spec(lane="deploy")            # routing relabel
    relabel["name"] = "renamed"               # prose
    relabel["rationale"] = "different words"  # prose
    relabel["kind"] = "llm"                   # evaluator label
    assert recipe_hash(relabel, params) == base, "a routing relabel / rename must NOT change the recipe hash"


def test_recipe_hash_is_deterministic_for_dict_or_json():
    params = {"rsi_floor": 30.0}
    spec = _spec()
    assert recipe_hash(spec, params) == recipe_hash(json.dumps(spec), json.dumps(params))


# --- the REQUIRED scenario: backfill → read holdout → edit exit rule → Gate refuses --------------------------

def test_gate_refuses_after_exit_rule_edit_until_fresh_commit(tmp_path):
    store = _store(tmp_path)
    version_id = _seed_version(store, _spec(take_profit=0.10), {"rsi_floor": 30.0})
    blinding = BlindingLedger(store)
    holdout = HoldoutLedger(store)

    # 1) Freeze the recipe, then OPEN the box (read the one-shot holdout). The Gate is happy: recipe unchanged.
    blinding.commit(version_id, reason="holdout_first_read")
    holdout.evaluate_once(version_id, lambda: {"passed": True, "deflated_sharpe": 1.2})
    assert holdout.consumed(version_id)
    assert_scoreable(store, version_id)  # does not raise

    # 2) Edit the EXIT RULE in place (the theater gap) — the recipe now differs from the committed hash.
    _edit_spec(store, version_id, _spec(take_profit=0.25))

    # 3) The Gate REFUSES to score it (recipe changed after the holdout was read, no fresh commit).
    with pytest.raises(BlindingViolation):
        assert_scoreable(store, version_id)

    # 4) A FRESH blinding commit re-blinds the new recipe AND re-arms the spent holdout → scoreable again.
    blinding.commit(version_id, reason="reblind")
    assert not holdout.consumed(version_id), "a re-blind onto a changed recipe must re-arm the one-shot holdout"
    assert_scoreable(store, version_id)  # does not raise

    # The audit trail shows BOTH commits (old recipe + new recipe), reasons intact.
    reasons = [c["reason"] for c in blinding.commits(version_id)]
    assert reasons == ["holdout_first_read", "reblind"]


def test_relabel_after_holdout_read_does_not_refuse(tmp_path):
    # The explore→gate graduation flips `lane` in place. That is a routing relabel, NOT a recipe change, so the
    # Gate must keep scoring it — the blinding guard must not fire on the one in-place mutation path that exists.
    store = _store(tmp_path)
    version_id = _seed_version(store, _spec(lane="explore"), {"rsi_floor": 30.0})
    BlindingLedger(store).commit(version_id, reason="forward_first_read")
    HoldoutLedger(store).evaluate_once(version_id, lambda: {"passed": True})
    _edit_spec(store, version_id, _spec(lane="gate"))  # the graduation relabel
    assert_scoreable(store, version_id)  # does not raise — lane is stripped from the recipe hash


# --- fail-OPEN: nothing to protect ---------------------------------------------------------------------------

def test_fail_open_without_a_commit(tmp_path):
    # No blinding commit at all (the pre-migration backlog) → never blinded → nothing to violate, even if the
    # holdout was read and the recipe later changes. Fail-open keeps the existing population scoreable.
    store = _store(tmp_path)
    version_id = _seed_version(store, _spec(take_profit=0.10), {"rsi_floor": 30.0})
    HoldoutLedger(store).evaluate_once(version_id, lambda: {"passed": True})
    _edit_spec(store, version_id, _spec(take_profit=0.99))
    assert_scoreable(store, version_id)  # no commit → fail-open


def test_fail_open_when_box_never_opened(tmp_path):
    # Committed but the box was NEVER opened (no holdout read, no forward track). Changing the recipe before any
    # read is harmless (re-commit before the read is the honest flow), so the Gate must not refuse.
    store = _store(tmp_path)
    version_id = _seed_version(store, _spec(take_profit=0.10), {"rsi_floor": 30.0})
    BlindingLedger(store).commit(version_id, reason="holdout_first_read")
    assert not box_opened(store, version_id)
    _edit_spec(store, version_id, _spec(take_profit=0.25))
    assert_scoreable(store, version_id)  # box never opened → fail-open


def test_fail_open_for_unknown_version(tmp_path):
    store = _store(tmp_path)
    assert_scoreable(store, "does-not-exist")  # no row → nothing to score, no raise


# --- the FORWARD read opens the box too ----------------------------------------------------------------------

def test_forward_track_opened_is_a_box_read(tmp_path):
    store = _store(tmp_path)
    version_id = _seed_version(store, _spec(take_profit=0.10), {"rsi_floor": 30.0})
    BlindingLedger(store).commit(version_id, reason="forward_first_read")
    # A cell-keyed track_opened event (version:symbol:venue) is the forward "read" — box_opened must see it.
    store.append_event(actor="master", kind="track_opened", ref_type="strategy_version",
                       ref_id=f"{version_id}:BTC/USDT:binance", payload={"origin": "explore"})
    assert box_opened(store, version_id)
    _edit_spec(store, version_id, _spec(take_profit=0.25))
    with pytest.raises(BlindingViolation):
        assert_scoreable(store, version_id)


def test_idempotent_commit_of_same_recipe(tmp_path):
    store = _store(tmp_path)
    version_id = _seed_version(store, _spec(), {"rsi_floor": 30.0})
    led = BlindingLedger(store)
    led.commit(version_id, reason="holdout_first_read")
    led.commit(version_id, reason="holdout_first_read")  # same recipe → no new row
    assert len(led.commits(version_id)) == 1


# --- graduate_explore: the real in-place-mutation re-score path is now blinding-guarded ----------------------

def test_graduate_explore_refuses_a_recipe_changed_after_forward_read(tmp_path):
    from cosmu.master.zero_capital import graduate_explore

    store = _store(tmp_path)
    version_id = _seed_version(store, _spec(take_profit=0.10, lane="explore"), {"rsi_floor": 30.0})
    # Simulate the forward read open_zero_capital_track performs: freeze the recipe + record a track_opened.
    BlindingLedger(store).commit(version_id, reason="forward_first_read")
    store.append_event(actor="master", kind="track_opened", ref_type="strategy_version",
                       ref_id=version_id, payload={"origin": "explore", "zero_capital": True})

    # Edit the exit rule in place AFTER the forward read — the recipe drifts past the commit.
    _edit_spec(store, version_id, _spec(take_profit=0.25, lane="explore"))

    # gate_clears would say yes, but the blinding precondition REFUSES graduation (no fresh commit) → stays explore.
    assert graduate_explore(store, version_id, gate_clears=lambda _vid: True) is False
    spec_now = json.loads(store.row("SELECT spec FROM strategy_versions WHERE id = ?", (version_id,))["spec"])
    assert spec_now["lane"] == "explore", "a blinding-refused vibe must NOT graduate to the gate lane"

    # A fresh re-blind clears the violation → graduation proceeds and the lane flips to gate.
    BlindingLedger(store).commit(version_id, reason="reblind")
    assert graduate_explore(store, version_id, gate_clears=lambda _vid: True) is True
    spec_after = json.loads(store.row("SELECT spec FROM strategy_versions WHERE id = ?", (version_id,))["spec"])
    assert spec_after["lane"] == "gate"
