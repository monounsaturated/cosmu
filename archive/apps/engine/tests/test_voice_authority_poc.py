"""FIRST end-to-end test of the credibility / "voices" edge lane (roadmap #6): typed StrategySpecs whose ENTRY
keys off the registered `authority_weighted_claim_signal` PIT feature, routed through the EXACT per-combo BRUT Gate.

These tests pin the WIRE, not an edge. The authority carrier here is SYNTHETIC (real authority data does not exist
in prod — provider='social_authority' has zero alt_data rows), so the only claims under test are: (a) the specs are
legal, (b) entries actually fire on the authority feature → backtest → metrics → Gate verdict, (c) the Gate REJECTS
a pure-noise carrier (no leak), and (d) a labelled forward-leading carrier CAN reach a Gate PASS (the verdict path
is fully connected). All offline + deterministic; the Gate constants are read, never written.
"""

from __future__ import annotations

from cosmu.research.fixtures import permutation_null_market
from cosmu.research.voice_authority_poc import (
    AUTHORITY_FEATURE,
    inject_synthetic_authority,
    moderate_trend_market,
    run_voice_authority_panel,
    validate_all_specs,
    voice_authority_specs,
)


def test_specs_are_authority_entry_and_deterministic():
    """The authored specs are deterministic, ~7, and EVERY entry keys off the registered authority feature."""
    a = voice_authority_specs()
    b = voice_authority_specs()
    assert len(a) == 7
    assert [vs.spec.name for vs in a] == [vs.spec.name for vs in b]  # pure authoring
    for vs in a:
        assert vs.spec.entry, "an authority spec must have an entry condition"
        assert all(c.feature.name == AUTHORITY_FEATURE for c in vs.spec.entry)
        assert vs.spec.lane == "explore"  # a low-confidence vibe, not a strict-gate claim


def test_every_spec_is_valid():
    """Every authored spec passes the REAL validate_spec — the authority feature is registered, no magic numbers,
    valid horizon/universe. If this fails the wire is broken at authoring (the feature isn't in the registry)."""
    issues = validate_all_specs()
    assert all(not v for v in issues.values()), f"invalid specs: {issues}"


def test_synthetic_injection_shape_and_range():
    """The injected carrier matches the finder's alt-join shape (symbol → feature → {ts.isoformat(): value}) and
    sits in the real signal's [-1, 1] range — so the backtest reads it exactly like a real authority series."""
    market = permutation_null_market(n=200, seed=13)
    alt = inject_synthetic_authority(market, seed=7, regime="null")
    for sym, bars in market.items():
        series = alt[sym][AUTHORITY_FEATURE]
        assert len(series) == len(bars)
        assert all(-1.0 <= v <= 1.0 for v in series.values())
        assert bars[0].ts.isoformat() in series  # keyed by bar timestamp (the PIT join key)


def test_wire_fires_specs_actually_enter_on_authority():
    """The MINIMAL proof the feature reaches the entry path: with an authority carrier present, specs actually
    TRADE (>0 trades) → backtest → metrics → a Gate verdict per cell. A dormant wire would book zero trades."""
    market = permutation_null_market(n=400, seed=13)
    panel = run_voice_authority_panel(market=market, regime="null")
    assert panel.wire_fired
    assert panel.total_trades > 0
    assert panel.n_cells == 7 * len(market)  # one cell per spec × symbol


def test_null_carrier_clears_nothing():
    """A PURE-NOISE authority carrier on the permutation-null market must clear NO cell — the honest Gate rejects a
    signal with no return relationship. A pass here would be a CAUGHT LEAK (never weaken this)."""
    market = permutation_null_market(n=600, seed=13)
    panel = run_voice_authority_panel(market=market, regime="null")
    assert not panel.any_cleared, [c for c in panel.cells if c.cleared]


def test_strong_lead_carrier_can_reach_a_gate_pass():
    """PIPELINE-PROOF: a labelled forward-hold look-ahead carrier on the moderate-trend demo market CAN clear the
    full Gate (DSR/PBO/min-trades/beat-B&H) on at least one cell — proving the verdict path is fully connected to a
    PASS, not only to a REJECT. This is a plumbing demonstration, NOT a claim of real edge."""
    market = moderate_trend_market()  # pinned seed where the mild-level spec clears cleanly
    panel = run_voice_authority_panel(market=market, regime="strong_lead")
    assert panel.wire_fired
    assert panel.any_cleared, "the strong-lead carrier should clear at least one cell end-to-end"
    cleared = [c for c in panel.cells if c.cleared]
    for c in cleared:
        assert c.reasons == []  # a clean pass: no failing gate leg
        assert c.dsr >= panel.gate_dsr_floor
        assert c.trades >= 30


def test_gate_is_strictly_harder_for_noise_than_for_the_lead():
    """The Gate's ranking scalar (DSR) must be HIGHER under the leading carrier than the pure-noise null on the SAME
    market — the wire reacts to signal CONTENT, not just to firing. (A sanity check that the carrier feeds through to
    the metrics, not that either regime passes — neither clears on the null market.)"""
    market = permutation_null_market(n=600, seed=13)
    null_panel = run_voice_authority_panel(market=market, regime="null")
    lead_panel = run_voice_authority_panel(market=market, regime="leading")
    import statistics

    null_med = statistics.median([c.dsr for c in null_panel.cells])
    lead_med = statistics.median([c.dsr for c in lead_panel.cells])
    assert lead_med > null_med
