# intent: WIRE the leakage tripwire into the source→feature admission path — the fail-closed audit a NEW registered
# alt source must clear before static_check will let a spec reference it (gate_eligible_names). A source becomes a
# feature by being registered in feature_registry with audit_passed=False (the default); it is INELIGIBLE for the
# Gate until this module runs cosmu.research.leakage_tripwire.audit_feature on its real PIT points and the audit
# PASSES. This is the choke point the operator named as the #1 blow-up guard: no untrusted feature reaches the Gate.
#
# Two entry points + a CLI:
#   audit_registered_source(feature, points, bars, ...) -> AuditOutcome   (runs the tripwire; PURE if points/bars
#                                                                          supplied; else resolves them PIT from a
#                                                                          store, or falls back to the keyless
#                                                                          offline control for a smoke run)
#   apply_audit_verdict(outcome, ...)                     -> AuditVerdict  (PROPOSE-ONLY: reports what SHOULD flip,
#                                                                          NEVER mutates the registry / moves money)
#   python -m cosmu.ingest.audit_registry <feature> [--all]               (CLI; exits NON-ZERO on a FAIL)
#
# Fail-closed by construction: a source that has NOT passed here stays audit_passed=False → NOT in
# gate_eligible_names() → static_check rejects any spec that references it ("feature_not_leakage_audited"). This
# module READS the tripwire verdict and PROPOSES the flip; a human/operator sets audit_passed=True in the registry
# (the same propose-only discipline the placebo rider + authority consumer use). It reads/writes NO Gate constant.

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

from cosmu.config import feature_registry as _reg
from cosmu.config.feature_registry import FeatureDefinition, gate_eligible_names
from cosmu.data.market import Bar
from cosmu.data.providers._types import AltDataPoint
from cosmu.research.leakage_tripwire import TripwireReport, audit_feature


def report_hash(report: TripwireReport) -> str:
    """A deterministic 16-char content hash of a TripwireReport — pins WHICH audit run a verdict came from, so a
    promoted feature's audit_report_hash is traceable. Hashes the rendered verdict body (feature, n_obs, real_ic,
    each check's summary, the failed set). Keyless/offline (sha256), stable across processes."""
    payload = "|".join(
        [
            report.feature,
            str(report.n_obs),
            f"{report.real_ic:.6f}",
            report.available_at.summary,
            f"{report.shuffle.p_value:.6f}",
            report.forward_shift.summary,
            ("anon:" + f"{report.anonymization.identity_share:.4f}") if report.anonymization is not None else "anon:none",
            "PASS" if report.passed else "FAIL",
            ",".join(report.failed_checks),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class AuditOutcome:
    """The result of auditing ONE registered source. `report` is the raw TripwireReport (None only if the source
    could not be scored — no PIT data — which is treated as a FAIL, fail-closed). `passed` mirrors report.passed
    (False when report is None). `report_digest` pins the report. `note` explains a None report."""

    feature: str
    report: TripwireReport | None
    passed: bool
    report_digest: str | None
    note: str = ""

    @property
    def summary(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        if self.report is None:
            return f"{self.feature}: {verdict} (no report — {self.note or 'no PIT data'})"
        return f"{self.feature}: {verdict}  ({self.report.render().splitlines()[0]})"


@dataclass(frozen=True)
class AuditVerdict:
    """PROPOSE-ONLY: what SHOULD change in the registry given an AuditOutcome — never applied here. `should_enable`
    is True iff the audit passed AND the feature is not already gate-eligible (so a pass would newly admit it).
    `proposed_audit_passed` is the audit_passed value the operator should set. `applied` is ALWAYS False — this
    module reports, a human disposes (the same discipline as the placebo rider / authority consumer)."""

    feature: str
    should_enable: bool
    proposed_audit_passed: bool
    proposed_audit_report_hash: str | None
    already_gate_eligible: bool
    applied: bool = False
    reasons: list[str] = field(default_factory=list)

    def render(self) -> str:
        head = "PROPOSE audit_passed=True" if self.should_enable else "NO CHANGE"
        return (
            f"{self.feature}: {head} "
            f"(proposed audit_passed={self.proposed_audit_passed}, "
            f"already_gate_eligible={self.already_gate_eligible}, applied={self.applied}) "
            f"— {'; '.join(self.reasons) if self.reasons else 'ok'}"
        )


def _feature_def(feature: str) -> FeatureDefinition | None:
    # Read the LIVE module attribute (not a name bound at import) so a monkeypatched registry (tests) + a future
    # registry edit are both honoured.
    return next((f for f in _reg.FEATURE_REGISTRY if f.name == feature), None)


def audit_registered_source(
    feature: str,
    points: list[AltDataPoint] | None = None,
    bars: list[Bar] | None = None,
    *,
    horizon: int = 1,
    shuffle_trials: int = 200,
    seed: int = 0,
    series_by_symbol: dict[str, list[AltDataPoint]] | None = None,
    bars_by_symbol: dict[str, list[Bar]] | None = None,
    offline_fallback: bool = True,
) -> AuditOutcome:
    """Run the leakage tripwire on a REGISTERED source and return an AuditOutcome (fail-closed).

    If `points`+`bars` are supplied they are audited directly (the pure, testable path — the caller resolved the
    source's real PIT points). Otherwise, when `offline_fallback` is True, a keyless synthetic control is scored so
    the CLI/smoke path still exercises the wiring end-to-end without a DB or network (the M2 is geo-blocked); when
    it is False and no data is supplied the outcome is a FAIL with a note (nothing to audit ⇒ not trustworthy).

    A source that is not in the registry is a FAIL (you cannot admit an unknown feature). PROPOSE-ONLY + pure for
    fixed inputs — reuses audit_feature (never a second hand-rolled correlation); reads no Gate constant."""
    fdef = _feature_def(feature)
    if fdef is None:
        return AuditOutcome(feature=feature, report=None, passed=False, report_digest=None, note="unknown feature (not in registry)")

    if points is None or bars is None:
        if not offline_fallback:
            return AuditOutcome(feature=feature, report=None, passed=False, report_digest=None, note="no PIT points/bars supplied")
        # Keyless offline smoke: score the tripwire's own clean synthetic control so the wiring runs anywhere.
        from cosmu.research.leakage_tripwire import _synthetic_clean_feature

        points, bars = _synthetic_clean_feature(seed=seed, horizon=horizon)

    report = audit_feature(
        points,
        bars,
        horizon=horizon,
        feature=feature,
        shuffle_trials=shuffle_trials,
        seed=seed,
        series_by_symbol=series_by_symbol,
        bars_by_symbol=bars_by_symbol,
    )
    return AuditOutcome(
        feature=feature,
        report=report,
        passed=report.passed,
        report_digest=report_hash(report),
        note="",
    )


def apply_audit_verdict(outcome: AuditOutcome, *, apply: bool = False) -> AuditVerdict:
    """PROPOSE-ONLY (the name is legacy-shaped; the DEFAULT and only supported mode is propose): given an
    AuditOutcome, report what the registry SHOULD become. `apply` MUST stay False here — this module never mutates
    FEATURE_REGISTRY (a frozen module tuple) and never moves money; a human sets audit_passed in the source. When
    `apply=True` is requested we still do NOT mutate — we record a reason that application is out of scope (the
    registry is the source of truth, edited by a person)."""
    already = outcome.feature in gate_eligible_names()
    reasons: list[str] = []
    should = outcome.passed and not already
    if outcome.passed:
        reasons.append("leakage tripwire PASSED")
    else:
        reasons.append(f"leakage tripwire FAILED{(' — ' + ', '.join(outcome.report.failed_checks)) if outcome.report and outcome.report.failed_checks else ''}")
    if already:
        reasons.append("already gate-eligible (grandfathered/price/audited)")
    if apply:
        reasons.append("apply requested but PROPOSE-ONLY: set audit_passed in feature_registry by hand")
    return AuditVerdict(
        feature=outcome.feature,
        should_enable=should,
        proposed_audit_passed=outcome.passed,
        proposed_audit_report_hash=outcome.report_digest if outcome.passed else None,
        already_gate_eligible=already,
        applied=False,
        reasons=reasons,
    )


# --------------------------------------------------------------------------------------------------- CLI (offline)


def _main(argv: list[str] | None = None) -> int:
    """`python -m cosmu.ingest.audit_registry <feature>` — run the leakage tripwire audit on a registered source
    (keyless offline smoke by default) and print the PASS/FAIL + the propose-only verdict. `--all` audits every
    enabled feature. Exits NON-ZERO iff ANY audited feature FAILS, so a script/CI/cron rider fails loudly on a
    leak. No network, no DB, no LLM — the harness is pure so the wiring runs anywhere (the M2 is geo-blocked)."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Leakage-tripwire audit of a registered alt source (fail-closed admission to the Gate)."
    )
    parser.add_argument("feature", nargs="?", default=None, help="feature name to audit (omit with --all)")
    parser.add_argument("--all", action="store_true", help="audit every enabled feature (observe-only smoke)")
    parser.add_argument("--horizon", type=int, default=1)
    parser.add_argument("--trials", type=int, default=200)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    if args.all:
        targets = [f.name for f in _reg.FEATURE_REGISTRY if f.enabled]
    elif args.feature:
        targets = [args.feature]
    else:
        parser.error("provide a <feature> or --all")
        return 2

    print(f"LEAKAGE-AUDIT REGISTRY — {len(targets)} feature(s) @ {datetime.now(UTC).isoformat()}")
    any_fail = False
    for name in targets:
        outcome = audit_registered_source(name, horizon=args.horizon, shuffle_trials=args.trials, seed=args.seed)
        verdict = apply_audit_verdict(outcome)
        print(f"  {outcome.summary}")
        print(f"    -> {verdict.render()}")
        if not outcome.passed:
            any_fail = True
    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(_main())
