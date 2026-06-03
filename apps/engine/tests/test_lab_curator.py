# The Curator: distill a gate-passing Version into a graded SKILL recipe (a parameterized spec template + the
# features/modules it used), grade skills by the downstream OOS success of derived Versions, and PRUNE a
# low-grade skill (set pruned_at). The Curator curates only what the deterministic Gate already judged — it
# never scores or promotes. Offline + keyless.

from __future__ import annotations

from cosmu.config.settings import Settings
from cosmu.evolution.loop import fit_params
from cosmu.evolution.seeder import seed_meanrev_spec, seed_momentum_spec
from cosmu.knowledge.store import Store, utcnow
from cosmu.lab.curator import distill_skill, grade_skills, live_skills, skill_feature_priors
from cosmu.strategy.compiler import compile_spec


class _Ev:
    def __init__(self, vid, name, origin, passed, reasons=None, ds=0.6, oos=4.0):  # noqa: ANN001
        self.version_id = vid
        self.name = name
        self.origin = origin
        self.passed = passed
        self.reasons = reasons or []
        self.deflated_sharpe = ds
        self.oos_return_pct = oos


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/cur.sqlite3", openrouter_api_key=None))


def _persist_version(store: Store, spec, *, passed: bool, vid_origin="seed") -> str:  # noqa: ANN001
    """Persist a strategy + version + a screen backtest with the given gate verdict so grade_skills() has REAL
    derived evidence to read (it reads only persisted verdicts — never re-scores)."""
    params = fit_params(spec)
    compiled = compile_spec(spec, params)
    sid = store.insert("strategies", {"name": spec.name, "thesis": spec.rationale, "origin": vid_origin, "created_at": utcnow()})
    vid = store.insert(
        "strategy_versions",
        {
            "strategy_id": sid, "parent_id": None, "spec": spec.model_dump(mode="json"),
            "generated_code": compiled.code, "code_hash": compiled.code_hash, "params": params,
            "mutation_operator": None, "mutation_rationale": None, "origin": vid_origin,
            "status": "forward_test" if passed else "killed", "created_at": utcnow(),
            "killed_at": None if passed else utcnow(), "kill_reason": None if passed else "pbo",
        },
    )
    store.insert(
        "backtests",
        {
            "strategy_version_id": vid, "kind": "screen", "oos_return": "0.04", "sharpe": "1", "sortino": "1",
            "deflated_sharpe": "0.6", "max_dd": "0.1", "win_rate": "0.5", "num_trades": 40, "pbo": "0.2",
            "trials_counted": 1, "regime_label": "mixed", "folds_positive": 4,
            "passed_gates": 1 if passed else 0, "holdout_passed": 1, "created_at": utcnow(),
        },
    )
    return vid


def test_distill_survivor_into_graded_skill(tmp_path):
    store = _store(tmp_path)
    spec = seed_momentum_spec()
    spec.name = "Trend momentum ADX"
    vid = _persist_version(store, spec, passed=True)

    skill_id = distill_skill(store, spec, _Ev(vid, spec.name, "seed", passed=True))
    assert skill_id

    graded = grade_skills(store)
    assert len(graded) == 1
    skill = graded[0]
    # all derived versions passed the gate → grade 1.0
    assert skill.grade == 1.0
    assert skill.success_count == 1
    assert "ret_Nd" in skill.recipe_summary or "adx" in skill.recipe_summary
    # the recipe carries STRUCTURE only — its features feed authoring as priors
    priors = skill_feature_priors(store)
    assert priors and max(priors.values()) == 1.0


def test_distill_rejects_non_survivor(tmp_path):
    store = _store(tmp_path)
    spec = seed_meanrev_spec()
    try:
        distill_skill(store, spec, _Ev("v", spec.name, "seed", passed=False, reasons=["pbo"]))
    except ValueError:
        return
    raise AssertionError("distill_skill must reject a non-gate-passing Version")


def test_grade_prunes_low_grade_skill(tmp_path):
    store = _store(tmp_path)
    # Distill a skill from one survivor, then persist further DERIVED versions of the same structure that the
    # gate KILLED — pushing the downstream pass-rate below the floor → the skill is pruned (pruned_at set).
    spec = seed_momentum_spec()
    spec.name = "Trend momentum ADX"
    seed_vid = _persist_version(store, spec, passed=True)
    distill_skill(store, spec, _Ev(seed_vid, spec.name, "seed", passed=True))

    # three derived failures of the SAME structure (same features/modules) → 1 pass / 4 derived = 0.25 < floor
    for i in range(3):
        derived = seed_momentum_spec()
        derived.name = f"Trend derived {i}"
        _persist_version(store, derived, passed=False)

    graded = grade_skills(store)
    assert graded == [], "a skill whose derived Versions stop passing the gate must be pruned out of the prior set"
    row = store.row("SELECT pruned_at FROM skills LIMIT 1")
    assert row and row["pruned_at"] is not None
    assert live_skills(store) == []  # pruned skills never feed authoring again
