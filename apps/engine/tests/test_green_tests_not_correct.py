"""The "green tests ≠ correct" checklist (item 3) — a meta-guard for AI-written code.

A passing test suite does NOT mean the pipeline is point-in-time honest. The most dangerous bugs are
plausible-wrong: AI-written code touching JOINS / LABELING / TIME-ALIGNMENT / FEES / SIZING that looks right,
passes its own green tests, and is silently leaky. This file does not re-test those surfaces (the other
modules do); it asserts the TRIPWIRES THEMSELVES stay wired — every leakage-critical surface still exists at
its declared path AND is referenced by at least one guard test. So a future change cannot silently delete a
function's temporal guard (or rename the function past its guard) and still go green.

If this test fails, do NOT delete the entry — either restore the guard test or, if a surface genuinely moved,
update the manifest IN THE SAME diff that moved it (and re-read the new code for look-ahead first).
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Surface:
    """One leakage-critical surface AI-written code touches. `symbol` must resolve from `module` (a module-level
    function, OR a `Class.method` on a class in `module`), and at least one of `guard_tests` (test-file stems)
    must reference the bare symbol name — i.e. a live temporal guard exists."""

    symbol: str   # "func" or "Class.method"
    module: str
    category: str  # join | time-alignment | labeling | fees | sizing
    guard_tests: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ref(self) -> str:
        """The bare name guard tests reference (the method/func name, without any Class. prefix)."""
        return self.symbol.split(".")[-1]

    def resolve(self):
        """Import + walk the dotted symbol to the callable (function or unbound method)."""
        obj = importlib.import_module(self.module)
        for part in self.symbol.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                return None
        return obj


# The manifest. Every entry is a place a silent look-ahead / wrong-physics bug could hide.
LEAKAGE_CRITICAL: tuple[Surface, ...] = (
    # --- JOINS: the per-bar as-of joins (where a future value would leak onto a bar) ---
    Surface("align_asof", "cosmu.data.backtest", "join",
            ("test_leakage_tripwire_pit", "test_alt_features", "test_funding_accrual_per_bar")),
    Surface("AltDataStore.read_asof", "cosmu.data.providers.store", "join",
            ("test_leakage_tripwire_pit", "test_pit_fee_resolver")),
    Surface("PgAltDataStore.read_asof", "cosmu.data.providers.store", "join",
            ("test_pit_fee_resolver",)),
    Surface("_snapshot", "cosmu.data.sources.altdata_bridges", "join",
            ("test_leakage_tripwire_pit", "test_altdata_bridges_observed_ts")),
    # --- TIME-ALIGNMENT: cash-flow accrual that must sum only settlements already realized ---
    Surface("sum_funding_per_bar", "cosmu.data.backtest", "time-alignment",
            ("test_leakage_tripwire_pit", "test_funding_accrual_per_bar")),
    # --- FEES: the point-in-time fee read seam (no look-ahead on the cost side) ---
    Surface("read_pit_fee", "cosmu.data.providers.fees", "fees",
            ("test_dynamic_fees", "test_pit_fee_resolver")),
    # --- SIZING: the deterministic position-sizing envelope (parity backtest=paper=live) ---
    Surface("size_fraction", "cosmu.master.sizing", "sizing",
            ("test_sizing", "test_paper_step")),
    # --- DISCONFIRMERS: the reusable null harness must itself stay wired ---
    Surface("shuffle_null", "cosmu.research.disconfirmers", "labeling",
            ("test_disconfirmer_harness",)),
    Surface("symbol_anonymization_null", "cosmu.research.disconfirmers", "labeling",
            ("test_disconfirmer_harness",)),
    # --- LEAKAGE WIRING (fail-closed upstream of the Gate): these three MUST stay wired into the money-path.
    # audit_feature gates a NEW source's admission (via ingest.audit_registry → gate_eligible_names → static_check),
    # and run_placebo_panel is the cohort's negative-control rider. A guard test references each so the wiring
    # cannot be silently un-wired while the suite stays green. ---
    Surface("audit_feature", "cosmu.research.leakage_tripwire", "labeling",
            ("test_leakage_wiring",)),
    Surface("run_placebo_panel", "cosmu.research.placebo_panel", "labeling",
            ("test_leakage_wiring",)),
    Surface("gate_eligible_names", "cosmu.config.feature_registry", "join",
            ("test_leakage_wiring",)),
    Surface("audit_registered_source", "cosmu.ingest.audit_registry", "join",
            ("test_leakage_wiring",)),
    Surface("FarmLoop._run_placebo_rider", "cosmu.evolution.loop", "labeling",
            ("test_leakage_wiring",)),
)


@pytest.mark.parametrize("surface", LEAKAGE_CRITICAL, ids=lambda s: f"{s.module}.{s.symbol}")
def test_leakage_surface_still_exists(surface: Surface):
    """Each named leakage-critical surface is importable + callable at its declared path. A rename that breaks
    this (without updating the manifest) means a guard test is now pointing at a ghost."""
    obj = surface.resolve()
    assert obj is not None, f"{surface.module}.{surface.symbol} is gone — its temporal guard may now be dead"
    assert callable(obj), f"{surface.module}.{surface.symbol} is no longer callable"


@pytest.mark.parametrize("surface", LEAKAGE_CRITICAL, ids=lambda s: f"{s.module}.{s.symbol}")
def test_leakage_surface_has_a_live_guard_test(surface: Surface):
    """At least one declared guard test exists AND references the symbol — so the temporal guard cannot be
    silently deleted while the suite stays green. (References the symbol by name in the test source.)"""
    assert surface.guard_tests, f"{surface.symbol}: no guard test declared — add a temporal/look-ahead test"
    found = False
    for stem in surface.guard_tests:
        path = _TESTS_DIR / f"{stem}.py"
        if path.exists() and surface.ref in path.read_text():
            found = True
            break
    assert found, (
        f"{surface.symbol}: none of its declared guard tests {surface.guard_tests} reference it — "
        "the leakage guard for this surface has gone missing"
    )


def test_every_category_is_covered():
    """Sanity: the five named risky categories (joins/labeling/time-alignment/fees/sizing) each have at least
    one wired surface — so we never quietly drop a whole class of leakage from the checklist."""
    covered = {s.category for s in LEAKAGE_CRITICAL}
    expected = {"join", "labeling", "time-alignment", "fees", "sizing"}
    missing = expected - covered
    assert not missing, f"leakage categories with no guarded surface: {missing}"
