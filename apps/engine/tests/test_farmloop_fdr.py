# The deployed farming loop must apply Benjamini-Hochberg FDR across the WHOLE cohort before any gate-passer
# becomes fundable — otherwise authoring more candidates per tick manufactures a "winner" by sheer count, which
# is exactly the multiple-testing failure the funding path (orchestrator/_survivor_sleeves) used to inherit.

from __future__ import annotations

from cosmu.evolution.loop import Evaluated, fdr_culled_vids


def _ev(vid: str, deflated_sharpe: float, *, passed: bool) -> Evaluated:
    return Evaluated(
        version_id=vid,
        name=vid,
        origin="test",
        lane="explore",
        deflated_sharpe=deflated_sharpe,   # DSR probability in [0,1]; p-value = 1 - this
        oos_return_pct=1.0,
        passed=passed,
        reasons=[] if passed else ["deflated_sharpe"],
    )


def test_lone_weak_passer_among_many_tests_is_culled():
    # One candidate squeaks past score() at p=0.04, surrounded by 30 noise candidates the gate already killed.
    # 0.04 of 31 tests is not a discovery — BH must cull it.
    family = [_ev("winner", 0.96, passed=True)]
    family += [_ev(f"noise{i}", 0.5, passed=False) for i in range(30)]
    culled = fdr_culled_vids(family, q=0.10)
    assert culled == {"winner"}


def test_strongly_significant_cohort_all_survive():
    # 30 candidates each at p=0.001 — genuinely significant even after correcting for 30 tests; none culled.
    family = [_ev(f"s{i}", 0.999, passed=True) for i in range(30)]
    assert fdr_culled_vids(family, q=0.10) == set()


def test_failed_candidates_are_never_culled():
    # FDR can only DEMOTE a gate-passer; a candidate the gate already killed has nothing left to cull.
    family = [_ev("killed", 0.10, passed=False), _ev("killed2", 0.20, passed=False)]
    assert fdr_culled_vids(family, q=0.10) == set()


def test_empty_cohort():
    assert fdr_culled_vids([], q=0.10) == set()


def test_stricter_q_culls_more():
    # A borderline passer that clears a lenient q can fail a stricter one — q is the honesty dial.
    family = [_ev("borderline", 0.93, passed=True)]
    family += [_ev(f"s{i}", 0.985, passed=True) for i in range(8)]
    lenient = fdr_culled_vids(family, q=0.50)
    strict = fdr_culled_vids(family, q=0.01)
    assert "borderline" in strict
    assert len(strict) >= len(lenient)
