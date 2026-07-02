"""LEAKAGE WIRING — the fail-closed admission gate (leakage tripwire + placebo rider) upstream of the Gate.

These tests pin the money-path wiring the PR adds:

  (1) gate_eligible_names is the STATIC-CHECK choke point: a NEW enabled+non-audited feature is in feature_names()
      but NOT in gate_eligible_names(), and a spec that references it FAILS validate_spec with the leakage-audit
      message — while every INCUMBENT (grandfathered) and PRICE feature stays eligible (ZERO regression).
  (2) ingest.audit_registry runs the leakage tripwire fail-closed: a leaked source stays ineligible (FAIL), a
      clean source PASSES and is proposed for admission (propose-only — nothing is mutated).
  (3) the FarmLoop placebo rider emits its event, records the CONTINUOUS placebo_inflation + any_cleared, sets
      leak_caught + PROPOSE-ONLY quarantines the CARRIER SOURCE (never the edge) when a placebo clears, and NEVER
      breaks the cohort even when it raises.
  (4) placebo_inflation is MONOTONE in injected leak strength (a genomic-λ-style continuous read, not just binary).

Hermetic: a temp-sqlite Store, no network, no LLM, no DB beyond the local sqlite file. The instrument LOOSENS
NOTHING — it reads the locked Gate constants, never writes them (registry_version stays byte-unchanged).
"""

from __future__ import annotations

from cosmu.config import feature_registry
from cosmu.config.feature_registry import (
    _PRICE_FEATURE_NAMES,
    FEATURE_REGISTRY,
    FeatureDefinition,
    control_feature_names,
    feature_names,
    gate_eligible_names,
)
from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.research.placebo_panel import (
    PlaceboCell,
    PlaceboPanel,
    control_arm_specs,
    placebo_inflation,
)
from cosmu.strategy.spec import Condition, FeatureRef, ParamRef
from cosmu.strategy.static_check import validate_spec

# --------------------------------------------------------------------------------------------------- fixtures


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/leakwire.sqlite3"))


def _new_feature(name: str, *, enabled: bool = True, audit_passed: bool = False) -> FeatureDefinition:
    """A brand-NEW alt feature (registered AFTER the tripwire was wired) — not a price feature, not a
    grandfathered incumbent. Defaults enabled + un-audited: the exact shape that must be INELIGIBLE."""
    return FeatureDefinition(
        name=name,
        source="brandnew_vendor",
        tier="tier1",
        asset_classes=["crypto"],
        asof_semantics="fetch time (availability == observation)",
        prior="A newly-wired alt source that must clear the leakage tripwire before the Gate may see it.",
        enabled=enabled,
        audit_passed=audit_passed,
    )


def _patch_registry(monkeypatch, *extra: FeatureDefinition) -> None:
    patched = (*FEATURE_REGISTRY, *extra)
    monkeypatch.setattr(feature_registry, "FEATURE_REGISTRY", patched)


def _spec_referencing(feature: str):
    """A valid placebo-shaped spec whose single entry condition references `feature` (everything else is a real,
    param-backed, incumbent-clean spec — so the ONLY validate_spec issue can be the feature's eligibility).
    StrategySpec is a Pydantic model, so we clone via model_copy (not dataclasses.replace)."""
    base = control_arm_specs(n_per_family=1)[0]
    entry = [Condition(feature=FeatureRef(name=feature), op="gt", threshold=ParamRef(param="thresh"))]
    return base.model_copy(update={"entry": entry})


# --------------------------------------------------------------------------------------------------- (1) choke point


def test_new_nonaudited_feature_is_known_but_not_gate_eligible(monkeypatch):
    novel = _new_feature("brandnew_unaudited")
    _patch_registry(monkeypatch, novel)
    # It IS a known enabled feature (feature_names) but NOT gate-eligible (un-audited, not grandfathered/price).
    assert "brandnew_unaudited" in feature_names()
    assert "brandnew_unaudited" not in gate_eligible_names()


def test_spec_referencing_new_nonaudited_feature_fails_static_check(monkeypatch):
    novel = _new_feature("brandnew_unaudited")
    _patch_registry(monkeypatch, novel)
    issues = validate_spec(_spec_referencing("brandnew_unaudited"))
    assert "feature_not_leakage_audited:brandnew_unaudited" in issues
    # It is NOT reported as unknown — it is registered, just un-audited (so the author fixes the right surface).
    assert "unknown_feature:brandnew_unaudited" not in issues


def test_unknown_feature_still_reports_unknown(monkeypatch):
    _patch_registry(monkeypatch)  # no new feature
    issues = validate_spec(_spec_referencing("totally_made_up_feature"))
    assert "unknown_feature:totally_made_up_feature" in issues


def test_price_features_are_exempt_and_eligible():
    # Every price/bar-computed feature is gate-eligible with no per-feature audit needed.
    eligible = gate_eligible_names()
    for name in _PRICE_FEATURE_NAMES:
        assert name in eligible, f"price feature {name} must be gate-eligible"
    # A spec referencing a price feature is never flagged as un-audited or unknown.
    issues = validate_spec(_spec_referencing("ret_Nd"))
    assert "feature_not_leakage_audited:ret_Nd" not in issues
    assert "unknown_feature:ret_Nd" not in issues


def test_every_incumbent_alt_feature_is_gate_eligible_non_regression():
    """NON-REGRESSION PROOF: every currently-enabled feature (all incumbents grandfathered) is gate-eligible, so
    gate_eligible_names() ⊇ feature_names() → no existing spec can regress."""
    fn = feature_names()
    ge = gate_eligible_names()
    missing = fn - ge
    assert not missing, f"REGRESSION: enabled features not gate-eligible: {sorted(missing)}"
    assert fn == ge  # today they are exactly equal (nothing un-audited is registered yet)
    # The controls (astro/weather/usgs/noaa) are enabled incumbents too — they must stay eligible.
    assert control_feature_names() <= ge


def test_new_feature_becomes_eligible_once_audit_passed(monkeypatch):
    clean = _new_feature("brandnew_clean", audit_passed=True)
    _patch_registry(monkeypatch, clean)
    assert "brandnew_clean" in gate_eligible_names()
    assert validate_spec(_spec_referencing("brandnew_clean")) == []


def test_registry_version_unchanged_by_audit_fields(monkeypatch):
    """audit_passed / audit_report_hash are OFF the hashed surface: flipping them leaves registry_version byte-
    unchanged (a promoted survivor's frozen hash is stable, same discipline as is_control)."""
    before = feature_registry.registry_version()
    # flip an incumbent's audit fields in a patched copy — the hash must not move (Pydantic model_copy).
    patched = tuple(
        f.model_copy(update={"audit_passed": not f.audit_passed, "audit_report_hash": "deadbeef"})
        if f.name == "funding_rate"
        else f
        for f in FEATURE_REGISTRY
    )
    monkeypatch.setattr(feature_registry, "FEATURE_REGISTRY", patched)
    assert feature_registry.registry_version() == before


# --------------------------------------------------------------------------------------------------- (2) audit_registry


def test_audit_registry_leaked_source_stays_ineligible():
    from cosmu.ingest.audit_registry import apply_audit_verdict, audit_registered_source
    from cosmu.research.leakage_tripwire import _synthetic_leaked_feature

    # audit a REAL registered feature name, but feed it deliberately LEAKED points → tripwire FAILS (forward-shift).
    points, bars = _synthetic_leaked_feature(seed=7)
    outcome = audit_registered_source("funding_rate", points, bars, seed=7)
    assert outcome.passed is False
    assert outcome.report is not None and "forward_shift_sanity" in outcome.report.failed_checks
    verdict = apply_audit_verdict(outcome)
    # PROPOSE-ONLY: a failing audit proposes NO enable, and nothing is applied.
    assert verdict.proposed_audit_passed is False
    assert verdict.applied is False


def test_audit_registry_clean_source_passes_and_is_proposed(monkeypatch):
    from cosmu.ingest.audit_registry import apply_audit_verdict, audit_registered_source
    from cosmu.research.leakage_tripwire import _synthetic_clean_feature

    novel = _new_feature("brandnew_clean")  # enabled, un-audited → not yet gate-eligible
    _patch_registry(monkeypatch, novel)
    points, bars = _synthetic_clean_feature(seed=7)
    outcome = audit_registered_source("brandnew_clean", points, bars, seed=7)
    assert outcome.passed is True
    assert outcome.report_digest  # a report hash is pinned on a pass
    verdict = apply_audit_verdict(outcome)
    # A clean source that is not YET eligible is PROPOSED for admission (propose-only; still not applied/mutated).
    assert verdict.should_enable is True
    assert verdict.proposed_audit_passed is True
    assert verdict.proposed_audit_report_hash == outcome.report_digest
    assert verdict.applied is False
    # The registry itself is untouched — the feature is still ineligible until a human flips audit_passed.
    assert "brandnew_clean" not in gate_eligible_names()


def test_audit_registry_unknown_feature_fails_closed():
    from cosmu.ingest.audit_registry import audit_registered_source

    outcome = audit_registered_source("no_such_feature_anywhere", offline_fallback=False)
    assert outcome.passed is False
    assert outcome.report is None


def test_audit_registered_source_is_the_leakage_tripwire_audit_feature():
    """The admission gate runs the REAL tripwire: audit_registered_source's verdict on a clean feed EQUALS calling
    leakage_tripwire.audit_feature directly (same harness, no second hand-rolled correlation). This also keeps the
    audit_feature surface referenced by name so the meta-guard (test_green_tests_not_correct) stays wired."""
    from cosmu.ingest.audit_registry import audit_registered_source
    from cosmu.research.leakage_tripwire import _synthetic_clean_feature, audit_feature

    points, bars = _synthetic_clean_feature(seed=7)
    direct = audit_feature(points, bars, horizon=1, feature="funding_rate", seed=7)
    via_registry = audit_registered_source("funding_rate", points, bars, seed=7)
    assert via_registry.passed == direct.passed is True
    assert via_registry.report is not None and via_registry.report.failed_checks == direct.failed_checks


# --------------------------------------------------------------------------------------------------- (3) placebo rider


def _cohort_settings() -> Settings:
    return Settings(openrouter_api_key=None)


def _run_tiny_cohort(store: Store):
    from cosmu.evolution.loop import FarmLoop

    loop = FarmLoop(settings=_cohort_settings(), store=store)
    return loop.run_cohort(seed=7, cohort_size=6)


def _event_kinds(store: Store) -> set[str]:
    rows = store.rows("SELECT kind FROM events")
    return {r["kind"] for r in rows}


def test_placebo_rider_emits_event_and_records_inflation(tmp_path):
    store = _store(tmp_path)
    summary = _run_tiny_cohort(store)
    # The rider ran (best-effort): inflation is recorded (a float or None) and the flags are present.
    assert hasattr(summary, "placebo_inflation")
    assert hasattr(summary, "placebo_any_cleared")
    assert hasattr(summary, "leak_caught")
    # A placebo_rider (or placebo_leak_caught) event was written into the cohort log alongside cohort_completed.
    kinds = _event_kinds(store)
    assert ("placebo_rider" in kinds) or ("placebo_leak_caught" in kinds), f"no rider event written; kinds={kinds}"


def test_placebo_rider_never_breaks_cohort_when_it_raises(tmp_path, monkeypatch):
    from cosmu.evolution.loop import FarmLoop

    store = _store(tmp_path)
    loop = FarmLoop(settings=_cohort_settings(), store=store)

    def _boom(*_a, **_k):
        raise RuntimeError("rider blew up")

    # Force the rider's core to raise; the cohort must STILL complete and return a summary.
    monkeypatch.setattr(FarmLoop, "_placebo_market", _boom)
    summary = loop.run_cohort(seed=7, cohort_size=6)
    assert summary is not None
    # A raising rider leaves the summary intact with the None/False defaults (never a partial write, never a crash).
    assert summary.placebo_inflation is None
    assert summary.placebo_any_cleared is False
    assert summary.leak_caught is False


def test_placebo_rider_quarantines_carrier_source_not_edge_on_clear(tmp_path, monkeypatch):
    """When a placebo CLEARS the Gate, the rider sets leak_caught and PROPOSE-ONLY quarantines the CARRIER SOURCE
    (the feature the placebo values rode in on) — NEVER a strategy/edge. We stub run_placebo_panel to return a
    leaky panel so the branch is deterministic (the panel's own leak-detection is pinned by test_placebo_panel)."""
    from cosmu.evolution.loop import FarmLoop
    from cosmu.research import placebo_panel as pp

    store = _store(tmp_path)
    loop = FarmLoop(settings=_cohort_settings(), store=store)

    leaked = PlaceboCell(
        spec_name="Placebo random-entry #3", family="random_entry", symbol="BTCUSDT",
        dsr=0.97, pbo=0.1, trades=60, cleared=True,
    )
    leaky = PlaceboPanel(
        cells=[leaked], gate_dsr_floor=0.95, n_specs=1, n_cells=1,
        dsr_mean=0.97, dsr_p50=0.97, dsr_p95=0.97, dsr_max=0.97,
        pbo_mean=0.1, pbo_p50=0.1, pbo_min=0.1, any_cleared=True, cleared_cells=[leaked],
    )
    # Give the rider a market (so it does not skip) and a leaky panel (so any_cleared=True).
    monkeypatch.setattr(FarmLoop, "_placebo_market", lambda self, seed: {"BTCUSDT": []})
    monkeypatch.setattr(pp, "run_placebo_panel", lambda **_k: leaky)

    inflation, cleared, leak_caught = loop._run_placebo_rider("cohort-test", 7)
    assert cleared is True
    assert leak_caught is True
    assert inflation is not None and inflation > 1.0  # p50 0.97 / floor 0.95 > 1 = the null already clears the floor

    # The event carries the carrier SOURCE as the quarantine target, and NO strategy/edge is quarantined.
    import json

    rows = store.rows("SELECT kind, payload FROM events WHERE kind = 'placebo_leak_caught'")
    assert rows, "a placebo_leak_caught event must be written on a caught leak"
    payload = json.loads(rows[-1]["payload"]) if isinstance(rows[-1]["payload"], str) else rows[-1]["payload"]
    assert payload.get("quarantine_carrier_source") == pp._CARRIER_FEATURE
    assert payload.get("leak_caught") is True


# --------------------------------------------------------------------------------------------------- (4) monotone


def _panel_with_p50(p50: float) -> PlaceboPanel:
    cells = [PlaceboCell(spec_name="p", family="random_entry", symbol="BTCUSDT", dsr=p50, pbo=0.3, trades=40, cleared=(p50 >= 0.95))]
    return PlaceboPanel(
        cells=cells, gate_dsr_floor=0.95, n_specs=1, n_cells=1,
        dsr_mean=p50, dsr_p50=p50, dsr_p95=p50, dsr_max=p50,
        pbo_mean=0.3, pbo_p50=0.3, pbo_min=0.3, any_cleared=(p50 >= 0.95), cleared_cells=[],
    )


def test_placebo_inflation_monotone_in_leak_strength():
    """placebo_inflation rises MONOTONICALLY as the injected leak strengthens (a stronger leak lifts the placebo
    DSR mass toward — and past — the Gate floor). Continuous, not binary."""
    strengths = [0.10, 0.30, 0.50, 0.70, 0.90, 0.96]
    infl = [placebo_inflation(_panel_with_p50(s)) for s in strengths]
    assert infl == sorted(infl)  # monotone non-decreasing
    assert infl[0] < infl[-1]     # strictly rising end-to-end
    # An empty panel is 0.0 (no inflation to report).
    empty = PlaceboPanel(
        cells=[], gate_dsr_floor=0.95, n_specs=0, n_cells=0,
        dsr_mean=0.0, dsr_p50=0.0, dsr_p95=0.0, dsr_max=0.0,
        pbo_mean=0.0, pbo_p50=0.0, pbo_min=0.0, any_cleared=False, cleared_cells=[],
    )
    assert placebo_inflation(empty) == 0.0
