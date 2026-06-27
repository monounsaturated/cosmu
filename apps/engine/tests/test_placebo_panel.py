"""The NEGATIVE-CONTROL EMPIRICAL-NULL PANEL — the Gate's self-validation instrument (playbook bridge #1, from
pharmaco-epi / GWAS, Schuemie-OHDSI). This is the standing leak monitor: run PLACEBO specs (time-shuffled real
signals + pure-noise random-entry) through the EXACT finder→Gate BRUT path and measure where they land.

THE headline guard: NO placebo may clear the Gate (`test_no_placebo_clears_the_gate*`). A placebo passing the
Gate means an upstream leak the Gate cannot see — a regression in the locked deflation, the per-cell PBO, the
folds floor, or the beat-buy-and-hold leg would surface here LOUDLY. It is never a test to weaken.

The supporting controls prove the instrument is not vacuous: the placebo signal injection is deterministic, a
time-shuffled feature's IC actually COLLAPSES (the placebo property), the panel measures a real DSR/PBO spread,
and the survivor-vs-null comparison correctly places a DSR in (or out of) the empirical tail.

All offline + deterministic (the repo's keyless permutation-null market; the M2 is geo-blocked). The panel
LOOSENS NOTHING — it reads the locked gate constants, never writes them.
"""

from __future__ import annotations

import pytest

from cosmu.config.settings import Settings
from cosmu.research.disconfirmers import pit_ic, shuffle_null
from cosmu.research.fixtures import permutation_null_market
from cosmu.research.placebo_panel import (
    PlaceboPanel,
    compare_survivor_to_null,
    inject_time_shuffled,
    placebo_specs,
    run_placebo_panel,
)


# --------------------------------------------------------------------------- authoring is deterministic + distinct


def test_placebo_specs_are_deterministic_and_two_families():
    """The placebo authoring is pure: the same ~10 specs every call, 5 time-shuffled + 5 random-entry."""
    a = placebo_specs()
    b = placebo_specs()
    assert len(a) == 10
    assert [p.spec.name for p in a] == [p.spec.name for p in b]  # deterministic
    fams = [p.family for p in a]
    assert fams.count("time_shuffled") == 5
    assert fams.count("random_entry") == 5
    # the random-entry thresholds are chosen so the firing rate matches the target turnover (thresh = 1 - turnover)
    for p in a:
        if p.family == "random_entry":
            assert abs(p.params["thresh"] - (1.0 - p.target_turnover)) < 1e-9


def test_placebo_specs_compile():
    """Every placebo spec must be a LEGAL StrategySpec (the carrier feature is registered) — else the panel
    couldn't run them through the real finder→Gate path."""
    from cosmu.strategy.compiler import compile_spec

    for p in placebo_specs():
        compiled = compile_spec(p.spec, p.params)
        assert compiled.code_hash


# --------------------------------------------------------------------------- the placebo property: IC collapses


def test_time_shuffled_signal_ic_collapses():
    """The core placebo property: a time-shuffled signal's IC sits INSIDE the shuffle-null band (does NOT
    survive) — its alignment to forward returns is destroyed. If a shuffled placebo still had a surviving IC,
    the injection wouldn't actually be a negative control. Uses the same disconfirmers harness the tripwire does."""
    from cosmu.data.providers._types import AltDataPoint

    market = permutation_null_market(correlated=False, n=400, seed=11)
    alt = inject_time_shuffled(market, seed=7)
    # rebuild the injected series as AltDataPoints for one symbol and score its IC vs forward returns
    sym, bars = next(iter(market.items()))
    series = alt[sym]["fear_greed"]
    by_ts = {b.ts.isoformat(): b for b in bars}
    points = [AltDataPoint(ts=by_ts[ts].ts, available_at=by_ts[ts].ts, value=v) for ts, v in series.items()]
    points.sort(key=lambda p: p.ts)
    res = shuffle_null(points, bars, horizon=1, trials=100, seed=0)
    # a shuffled placebo signal must NOT survive the shuffle null (its IC is indistinguishable from noise)
    assert not res.survives
    real_ic, n = pit_ic(points, bars, 1)
    assert n > 50  # the null market + injection actually produced a scoreable series


# --------------------------------------------------------------------------- the panel measures a real null


def _panel() -> PlaceboPanel:
    market = permutation_null_market(correlated=False, n=600, seed=11)
    return run_placebo_panel(market=market, seed=7)


def test_panel_runs_and_measures_a_distribution():
    """The panel produces a non-vacuous measured null: every placebo spec × symbol is scored, and the cells
    actually traded (so the 0-cleared result below is the gate rejecting tempting placebos, not an empty run)."""
    panel = _panel()
    assert panel.n_specs == 10
    assert panel.n_cells == 50  # 10 specs × 5 symbols
    # the cells trade enough to be tempting: a real chunk clear the 30-trade floor (else the null is vacuous)
    eligible = [c for c in panel.cells if c.trades >= 30]
    assert len(eligible) >= 10
    # the DSR null spans a real range — placebos DO produce high DSR by chance (that's the point of measuring it)
    assert panel.dsr_max > 0.5
    assert 0.0 <= panel.dsr_mean <= 1.0


def test_panel_is_deterministic():
    """Same (market, seed) → byte-identical measured null (the instrument is reproducible)."""
    market = permutation_null_market(correlated=False, n=400, seed=11)
    p1 = run_placebo_panel(market=market, seed=7)
    p2 = run_placebo_panel(market=market, seed=7)
    assert p1.null_dsrs == p2.null_dsrs
    assert p1.any_cleared == p2.any_cleared


# --------------------------------------------------------------------------- THE guard: no placebo clears the gate


def test_no_placebo_clears_the_gate():
    """THE headline guard. On a pure null (no edge in the bars NOR the injected signal), NOT ONE placebo cell
    may clear the locked Gate. A pass here = a leak the Gate cannot see (a deflation/PBO/folds/beat-B&H
    regression). Even though placebos routinely produce DSR near the 0.95 floor by chance, the FULL brut gate
    rejects every one — that conjunction is what this pins."""
    panel = _panel()
    assert panel.any_cleared is False
    assert panel.cleared_cells == []
    # belt-and-braces: cross-check directly against the locked gate constant
    floor = float(Settings(openrouter_api_key=None).gates.min_deflated_sharpe_prob)
    cleared = [c for c in panel.cells if c.dsr >= floor and c.cleared]
    assert cleared == []


@pytest.mark.parametrize("correlated,mseed,pseed", [(False, 29, 7), (False, 101, 23), (True, 11, 7), (True, 101, 23)])
def test_no_placebo_clears_across_regimes_and_seeds(correlated, mseed, pseed):
    """0-cleared is not a single lucky seed/regime: across independent + correlated null markets and several
    seeds (incl. regimes where the placebo DSR null reaches ~1.0), still nothing clears."""
    market = permutation_null_market(correlated=correlated, n=600, seed=mseed)
    panel = run_placebo_panel(market=market, seed=pseed)
    assert panel.any_cleared is False


# --------------------------------------------------------------------------- survivor vs the measured null


def test_survivor_above_null_is_right_tail():
    """A real survivor whose DSR sits ABOVE the placebo null p95 AND the gate floor is in the right tail —
    credible against the empirically-measured null."""
    panel = _panel()
    above = max(panel.dsr_p95, panel.gate_dsr_floor) + 0.02
    cmp = compare_survivor_to_null(min(above, 1.0) if above <= 1.0 else 0.999, panel)
    # if the bumped value is still <= 1.0 and clears both bars, it's right-tail; assert the comparison math holds
    if cmp.survivor_dsr > panel.dsr_p95 and cmp.survivor_dsr >= panel.gate_dsr_floor:
        assert cmp.right_tail is True
    assert 0.0 <= cmp.percentile <= 100.0
    assert 0.0 < cmp.empirical_p <= 1.0


def test_survivor_inside_null_band_is_not_credible():
    """A 'survivor' whose DSR sits at the placebo median is INSIDE the null band — not distinguishable from a
    placebo, so not right-tail (the instrument would flag it)."""
    panel = _panel()
    cmp = compare_survivor_to_null(panel.dsr_p50, panel)
    assert cmp.right_tail is False
    # its empirical p is large (a placebo easily matches it)
    assert cmp.empirical_p > 0.05


def test_render_is_loud_on_clean_and_has_verdict():
    """The report renders a clear verdict line either way (the cohort-rider log line + the CLI body)."""
    panel = _panel()
    text = panel.render()
    assert "PLACEBO NULL PANEL" in text
    assert ("CLEAN" in text) or ("LEAK CAUGHT" in text)
    assert "measured null DSR" in text
