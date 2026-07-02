# Compound the autonomous search: (1) the prior-steered / survival-biased exploit mutator, with a HARD byte-identical
# default when no learned signal is passed; (2) run_cohort consuming the learned feature priors, offline/empty-safe;
# (3) the scheduler's time-varied epoch-hour seed with an explicit-override honor; (4) the heavy-slot rider that
# schedules the differentiated funding/microstructure cohorts on the Nth cycle only, best-effort. Offline: temp
# sqlite Store, no network. Style mirrors tests/test_seed_collapse_root_fix.py (hermetic, deterministic).

from __future__ import annotations

import json
import random

from cosmu.config.settings import Settings
from cosmu.evolution import mutator
from cosmu.evolution.seeder import seed_population
from cosmu.knowledge.store import Store, utcnow


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/compound.sqlite3", openrouter_api_key=None))


# --------------------------------------------------------------------------- (1) mutator: byte-identical default


# A FROZEN reference of the pre-steering behaviour: the exact operator+rationale+spec sequence mutate_exploit produced
# from a fixed rng BEFORE feature_priors/survival existed. Captured by re-implementing the old body here (one
# rng.choice over EXPLOIT_OPERATORS, then op(parent, rng)) so the test pins the invariant even if the module changes.
def _legacy_mutate_exploit(parent, rng):  # noqa: ANN001 — mirrors the pre-steering mutate_exploit exactly
    op = rng.choice(mutator.EXPLOIT_OPERATORS)
    return op(parent, rng)


def test_mutate_exploit_default_is_byte_identical():
    """When BOTH steering inputs are None (the offline/cold-start default), mutate_exploit is byte-identical to the
    pre-steering behaviour — same operator, same rationale, same child spec — AND consumes the SAME rng draws (the
    rng end-state matches, so nothing downstream in the cohort's rng stream shifts)."""
    seeds = seed_population()
    for seed in (7, 42, 123, 2026):
        rng_new = random.Random(seed)
        rng_ref = random.Random(seed)
        for _ in range(150):
            p_new = seeds[rng_new.randrange(len(seeds))]
            p_ref = seeds[rng_ref.randrange(len(seeds))]
            child_new = mutator.mutate_exploit(p_new, rng_new)  # no feature_priors, no survival
            child_ref = _legacy_mutate_exploit(p_ref, rng_ref)
            assert child_new.operator == child_ref.operator
            assert child_new.rationale == child_ref.rationale
            assert child_new.spec.model_dump_json() == child_ref.spec.model_dump_json()
        # draw-count parity: identical rng end-state proves the default path drew the same number of randoms.
        assert rng_new.getstate() == rng_ref.getstate()


# --------------------------------------------------------------------------- (1) mutator: prior-steered feature freq


def _swap_parent():
    """A seed whose entry can be swap_feature'd (has ≥1 entry condition on a crypto feature)."""
    for spec in seed_population():
        if spec.entry and "crypto" in spec.universe.asset_classes:
            return spec
    return seed_population()[0]


def test_prior_steering_increases_chosen_feature_frequency():
    """A strong prior on one feature makes swap_feature pick it FAR more often than an unweighted draw would — while
    the exploration floor keeps every other feature reachable (never probability 0)."""
    parent = _swap_parent()
    from cosmu.config.feature_registry import features_for

    pool = [f.name for f in features_for(parent.universe.asset_classes)]
    current = parent.entry[0].feature.name
    target = next(n for n in pool if n != current)  # a feature we will lift the prior on

    def swap_freq(feature_priors):
        rng = random.Random(99)
        hits = 0
        n = 600
        for _ in range(n):
            child = mutator.swap_feature(parent, rng, feature_priors=feature_priors)
            # the swapped feature is whichever entry feature changed vs the parent
            new_names = {c.feature.name for c in child.spec.entry}
            if target in new_names and target != current:
                hits += 1
        return hits / n

    base = swap_freq(None)  # unweighted (byte-identical draw semantics)
    steered = swap_freq({target: 5.0})  # heavy prior on the target
    assert steered > base + 0.15, f"prior steering did not lift the chosen feature's frequency: {steered=} {base=}"
    # exploration floor: a feature with ZERO prior is still sometimes chosen even when another has a huge prior.
    other = next(n for n in pool if n not in (current, target))
    rng = random.Random(7)
    saw_other = False
    for _ in range(2000):
        child = mutator.swap_feature(parent, rng, feature_priors={target: 50.0})
        if other in {c.feature.name for c in child.spec.entry}:
            saw_other = True
            break
    assert saw_other, "exploration floor violated — a zero-prior feature became probability 0"


# --------------------------------------------------------------------------- (1) mutator: survival flips refine/escape


def test_survival_shift_flips_refine_vs_escape():
    """A HIGH survival score biases the operator choice toward the REFINE bucket (tune the winner in place); a LOW
    score biases toward the ESCAPE bucket (change its shape). Measured over many draws from the SAME parent."""
    parent = _swap_parent()
    refine = {op.__name__ for op in mutator._REFINE_OPERATORS}

    def refine_share(surv):
        rng = random.Random(4321)
        r = 0
        n = 800
        for _ in range(n):
            child = mutator.mutate_exploit(parent, rng, survival=surv)
            if child.operator in refine:
                r += 1
        return r / n

    hi = refine_share(0.95)
    lo = refine_share(0.05)
    assert hi > lo + 0.15, f"survival did not flip refine↔escape: high={hi} low={lo}"
    # both buckets stay reachable at either extreme (never a hard veto).
    assert 0.0 < lo < 1.0 and 0.0 < hi < 1.0


# --------------------------------------------------------------------------- (2) run_cohort consumes priors / safe


def _seed_skill(store: Store, feature: str, grade: float) -> None:
    """Insert one un-pruned skill whose recipe names `feature`, so skill_feature_priors returns {feature: grade}."""
    store.insert(
        "skills",
        {
            "name": f"skill-{feature}",
            "recipe": json.dumps({"features": [feature]}),
            "grade": str(grade),
            "lineage": "test",
            "success_count": 3,
            "created_at": utcnow(),
        },
    )


def test_feature_priors_helper_reads_skills_and_is_store_failure_safe(tmp_path):
    """FarmLoop._feature_priors reads the flywheel's skills into a {feature: grade} dict, and a store failure (the
    helper is best-effort) yields {} without raising — so a priors hiccup can never break a cohort."""
    from cosmu.evolution.loop import FarmLoop

    store = _store(tmp_path)
    loop = FarmLoop(settings=store.settings, store=store)
    assert loop._feature_priors() == {}  # cold start: no skills yet
    _seed_skill(store, "rsi", 0.8)
    _seed_skill(store, "rsi", 0.9)  # best grade wins
    _seed_skill(store, "atr", 0.4)
    priors = loop._feature_priors()
    assert priors == {"rsi": 0.9, "atr": 0.4}

    # A broken store (query raises) → {} not an exception.
    class _BrokenStore:
        def __getattr__(self, _name):
            raise RuntimeError("store down")

    broken_loop = FarmLoop(settings=store.settings, store=_BrokenStore())
    assert broken_loop._feature_priors() == {}


def test_run_cohort_consumes_priors_and_survives_priors_failure(tmp_path, monkeypatch):
    """run_cohort computes priors via _feature_priors and threads them into the exploit lane; a priors failure is
    swallowed ({} → unweighted default) and the cohort still completes. We assert the cohort runs green in both
    regimes (priors present vs priors-helper raising)."""
    from cosmu.evolution.loop import FarmLoop

    store = _store(tmp_path)
    _seed_skill(store, "rsi", 0.9)
    loop = FarmLoop(settings=store.settings, store=store)

    # priors present: cohort runs and produces a summary (offline screen → likely 0 survivors, that's fine).
    summary = loop.run_cohort(seed=7, cohort_size=6, explore_pct=0.5)
    assert summary.generated >= 0  # completed without raising

    # The UNDERLYING skill_feature_priors RAISES → _feature_priors swallows it to {} and the cohort still completes.
    # (This is the exact failure mode the task requires be non-fatal: an offline/broken curator.)
    import cosmu.lab.curator as curator

    def _boom(_store):  # noqa: ANN001
        raise RuntimeError("priors down")

    monkeypatch.setattr(curator, "skill_feature_priors", _boom)
    assert loop._feature_priors() == {}  # helper swallows the failure
    try:
        summary2 = loop.run_cohort(seed=8, cohort_size=6, explore_pct=0.5)
        raised = False
    except Exception:  # noqa: BLE001
        raised = True
    assert not raised, "a skill_feature_priors failure propagated out of run_cohort"
    assert summary2.generated >= 0


# --------------------------------------------------------------------------- (3) scheduler: time-varied seed


def test_epoch_hour_seed_varies_across_hours(monkeypatch):
    """The epoch-hour seed changes between two different wall-clock hours (each 4h tick starts from a fresh origin)
    and is a positive bounded int. _epoch_hour_seed does `import time` at call time, so we swap sys.modules['time']."""
    import sys

    import cosmu.master.scheduler as sched

    fake_a = type(sys)("time")
    fake_a.time = lambda: 1_700_000_000.0
    fake_b = type(sys)("time")
    fake_b.time = lambda: 1_700_000_000.0 + 3 * 3600  # 3 hours later → a different epoch-hour

    monkeypatch.setitem(sys.modules, "time", fake_a)
    seed_a = sched._epoch_hour_seed()
    monkeypatch.setitem(sys.modules, "time", fake_b)
    seed_b = sched._epoch_hour_seed()
    assert seed_a != seed_b, f"epoch-hour seed did not vary across hours: {seed_a} == {seed_b}"
    assert seed_a > 0 and seed_b > 0
    assert seed_a < 2**31 and seed_b < 2**31


def test_main_honors_explicit_seed_override(monkeypatch):
    """`--seed N` pins the cohort seed verbatim (repro), overriding the time-varied default. We capture the seed
    run_tick is called with, for both an explicit --seed and the default (time-varied) path."""
    import cosmu.master.scheduler as sched

    captured: dict[str, int] = {}

    def _fake_run_tick(store, *, n, seed, **_kw):  # noqa: ANN001
        captured["seed"] = seed
        from cosmu.master.scheduler import TickReport, TickSummary

        return TickReport(summary=TickSummary())

    monkeypatch.setattr(sched, "run_tick", _fake_run_tick)
    monkeypatch.setattr(sched, "_epoch_hour_seed", lambda: 424242)

    sched._main(["--offline", "--seed", "99"])
    assert captured["seed"] == 99, "explicit --seed was not honored verbatim"

    sched._main(["--offline"])
    assert captured["seed"] == 424242, "default did not use the time-varied epoch-hour seed"


# --------------------------------------------------------------------------- (4) scheduler: heavy-slot rider


def test_heavy_cohorts_fire_only_on_nth_cycle(tmp_path, monkeypatch):
    """_run_heavy_cohorts runs the differentiated cohorts only when cycle_count % every == 0, and returns the list
    of cohorts it ran (empty on an off-cycle). The actual cohort calls are stubbed so the test is hermetic + fast."""
    import cosmu.research.funding_crowding_cohort as fcc
    import cosmu.research.social_signal_cohort as ssc
    from cosmu.master import scheduler as sched

    store = _store(tmp_path)

    # stub each cohort's data assembly + run so no real bars/funding/social are touched (hermetic).
    class _Rep:
        verdict = "INSUFFICIENT-DATA"

    monkeypatch.setattr(fcc, "load_specs", lambda: [])
    monkeypatch.setattr("cosmu.research.carry_ablation._real_market", lambda *_a, **_k: {})
    monkeypatch.setattr("cosmu.research.carry_ablation._clip_to_funding_window", lambda *_a, **_k: {})
    monkeypatch.setattr("cosmu.data.altdata.CachedFundingRateProvider", lambda *_a, **_k: object())
    monkeypatch.setattr(fcc, "run_cohort", lambda *_a, **_k: _Rep())

    monkeypatch.setattr(ssc, "load_specs", lambda: [])
    monkeypatch.setattr(ssc, "_real_market", lambda *_a, **_k: {})
    monkeypatch.setattr(ssc, "_clip_to_social_window", lambda *_a, **_k: {})
    monkeypatch.setattr(ssc, "StoreBackedAltProvider", lambda *_a, **_k: object())
    monkeypatch.setattr("cosmu.data.alt_join.resolve_alt_store", lambda *_a, **_k: object())
    monkeypatch.setattr(ssc, "run_cohort", lambda *_a, **_k: _Rep())

    # off-cycle (cycle 1 with every=6) → nothing runs
    assert sched._run_heavy_cohorts(store, cycle_count=1, every=6) == []
    # on-cycle (cycle 0 and cycle 6) → both cohorts run
    assert sched._run_heavy_cohorts(store, cycle_count=0, every=6) == ["funding_crowding", "social_signal"]
    assert sched._run_heavy_cohorts(store, cycle_count=6, every=6) == ["funding_crowding", "social_signal"]
    # every<=0 disables the rider entirely
    assert sched._run_heavy_cohorts(store, cycle_count=0, every=0) == []


def test_heavy_cohort_failure_is_best_effort(tmp_path, monkeypatch):
    """A cohort raising inside the heavy slot never propagates — the other cohort still runs and the tick is safe."""
    import cosmu.research.funding_crowding_cohort as fcc
    import cosmu.research.social_signal_cohort as ssc
    from cosmu.master import scheduler as sched

    store = _store(tmp_path)

    def _boom(*_a, **_k):
        raise RuntimeError("funding cohort exploded")

    # funding cohort blows up during data assembly …
    monkeypatch.setattr("cosmu.research.carry_ablation._real_market", _boom)
    # … but the social cohort is stubbed to succeed.
    class _Rep:
        verdict = "PASS"

    monkeypatch.setattr(ssc, "load_specs", lambda: [])
    monkeypatch.setattr(ssc, "_real_market", lambda *_a, **_k: {})
    monkeypatch.setattr(ssc, "_clip_to_social_window", lambda *_a, **_k: {})
    monkeypatch.setattr(ssc, "StoreBackedAltProvider", lambda *_a, **_k: object())
    monkeypatch.setattr("cosmu.data.alt_join.resolve_alt_store", lambda *_a, **_k: object())
    monkeypatch.setattr(ssc, "run_cohort", lambda *_a, **_k: _Rep())

    ran = sched._run_heavy_cohorts(store, cycle_count=0, every=6)
    assert ran == ["social_signal"], f"best-effort broke: funding failure should be swallowed, got {ran}"
    # a failure event was audited (never silent).
    rows = store.rows("SELECT payload FROM events WHERE kind = 'heavy_cohort_failed'")
    assert any("funding_crowding" in (r["payload"] or "") for r in rows)
