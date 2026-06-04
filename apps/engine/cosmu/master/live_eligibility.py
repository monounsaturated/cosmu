# intent: the deterministic LIVE-ELIGIBILITY gate — what CAN be armed. A strategy may go live ONLY when it has
# BOTH (a) >= FORWARD_TEST_MIN_DAYS of net-positive FORWARD evidence AND (b) the CURRENT market regime is one it
# proved itself in. inputs: the store (a version's proven-regime passport on track_opened, its forward-test clock
# origin, and its track's net-of-fee return) + a reference close series for the current regime; outputs: a yes/no
# eligibility with a reason. invariants: both preconditions are HARD and the gate only BLOCKS (never promotes);
# fully deterministic + out of any LLM path; missing evidence fails safe (blocked). A human still makes the final
# launch click — this only gates WHICH survivors are armable. `override` (default OFF, set by a human) waives ONLY
# the forward-test precondition for an explicit override-launch of an unproven strategy — never the regime gate.

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from cosmu.knowledge.store import Store
from cosmu.master.forward_maturity import ForwardMaturity, maturity
from cosmu.ml.regime import Regime, current_regime, regime_eligible


@dataclass(frozen=True)
class LiveRegimeVerdict:
    version_id: str
    eligible: bool
    current_regime: Regime
    proven_regimes: list[str]
    reason: str


def proven_regimes_for(store: Store, version_id: str) -> set[str]:
    """Read a strategy version's proven-regime passport from its most recent track_opened event (written by
    the evolution loop when the deterministic gate opened the track). Empty if the version never opened a
    track — which the gate then treats as 'never proven anywhere' (blocked)."""
    row = store.row(
        "SELECT payload FROM events WHERE kind = 'track_opened' AND ref_id = ? ORDER BY id DESC LIMIT 1",
        (version_id,),
    )
    if not row:
        return set()
    payload = row["payload"]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return set()
    return set(payload.get("proven_regimes") or [])


def live_regime_verdict(store: Store, version_id: str, reference_bars) -> LiveRegimeVerdict:
    """Decide whether `version_id` may trade live RIGHT NOW: True only if the current regime (from the
    reference series) is one the strategy proved positive PnL in. Never promotes — only blocks; an empty
    proven set is never eligible (fail-safe)."""
    proven = proven_regimes_for(store, version_id)
    now = current_regime(reference_bars)
    eligible = regime_eligible(now, proven)
    if not proven:
        reason = "no proven regime on record"
    elif eligible:
        reason = f"current regime '{now.label}' is in the proven set"
    else:
        reason = f"current regime '{now.label}' not in proven set {sorted(proven)}"
    return LiveRegimeVerdict(
        version_id=version_id,
        eligible=eligible,
        current_regime=now,
        proven_regimes=sorted(proven),
        reason=reason,
    )


def forward_clock_origin(store: Store, version_id: str) -> str | None:
    """A version's forward-test clock origin: the ts of its FIRST `track_opened` event (the moment the
    deterministic gate opened the standalone track). None when the version never opened a track — which the
    maturity reads as age 0 (never matured), the fail-safe."""
    row = store.row(
        "SELECT MIN(ts) AS funded_at FROM events WHERE kind = 'track_opened' AND ref_id = ?",
        (version_id,),
    )
    return row["funded_at"] if row and row.get("funded_at") else None


def forward_net_return_pct(store: Store, version_id: str) -> float:
    """The forward-test track's net-of-fee return % — the strategy's own per-version FORWARD evidence
    (tracks.return_pct, the standalone track that proves itself on real closes). 0.0 when no track exists yet,
    which the gate reads as 'not net-positive' (fail-safe)."""
    row = store.row("SELECT return_pct FROM tracks WHERE strategy_version_id = ?", (version_id,))
    if not row or row.get("return_pct") is None:
        return 0.0
    try:
        return float(row["return_pct"])
    except (TypeError, ValueError):
        return 0.0


def forward_evidence(store: Store, version_id: str, *, now: datetime | None = None) -> ForwardMaturity:
    """The forward-test maturity for a version, read from the store: forward_age_days from its track's clock
    origin + net_return_pct from its track. `live_ready` = matured (>= FORWARD_TEST_MIN_DAYS) AND net-positive —
    the SAME deterministic condition the leaderboard surfaces advisorily, here consulted as a HARD gate."""
    return maturity(
        forward_clock_origin(store, version_id),
        forward_net_return_pct(store, version_id),
        now=now,
    )


@dataclass(frozen=True)
class LiveEligibilityVerdict:
    """The HARD live-eligibility verdict — what CAN be armed. `eligible` is True only when the strategy has BOTH
    >= FORWARD_TEST_MIN_DAYS of net-positive forward evidence (`forward_ready`) AND is in a proven regime
    (`regime_eligible`). A human still makes the final launch click; this only gates the armable set. `overridden`
    is True when a human waived the forward-test precondition via `override` to arm an UNPROVEN strategy (the
    caller logs the warning) — the regime gate is never waived. Never promotes — only blocks; missing evidence
    fails safe (not eligible)."""

    version_id: str
    eligible: bool
    forward_ready: bool
    forward_age_days: float
    net_return_pct: float
    min_days: int
    regime_eligible: bool
    current_regime: Regime
    proven_regimes: list[str]
    overridden: bool
    reason: str


def live_eligibility_verdict(
    store: Store,
    version_id: str,
    reference_bars,
    *,
    override: bool = False,
    now: datetime | None = None,
) -> LiveEligibilityVerdict:
    """Compose the two HARD live-eligibility preconditions: forward-test maturity (>= FORWARD_TEST_MIN_DAYS,
    net-positive) AND regime. `eligible` is True only when BOTH pass — UNLESS `override` is set, which waives
    ONLY the forward-test precondition (a human's explicit override-launch of an unproven strategy, logged by the
    caller) and NEVER the regime gate. Deterministic, LLM-free; an unproven/underwater/out-of-regime strategy
    fails safe to not-eligible."""
    regime = live_regime_verdict(store, version_id, reference_bars)
    evidence = forward_evidence(store, version_id, now=now)
    forward_ready = evidence.live_ready
    eligible = (forward_ready or override) and regime.eligible
    overridden = bool(override) and not forward_ready and eligible
    if not regime.eligible:
        # The regime gate blocks regardless of forward-test maturity or any override.
        reason = regime.reason
    elif overridden:
        reason = (
            f"OVERRIDE: arming UNPROVEN strategy "
            f"({evidence.forward_age_days:.1f}d / {evidence.net_return_pct:+.2f}%, "
            f"needs >= {evidence.min_days}d net-positive) — regime '{regime.current_regime.label}' ok"
        )
    elif not forward_ready:
        reason = (
            f"forward-test not proven: {evidence.forward_age_days:.1f}d / {evidence.net_return_pct:+.2f}% "
            f"(needs >= {evidence.min_days}d net-positive)"
        )
    else:
        reason = (
            f"forward-test proven ({evidence.forward_age_days:.1f}d net-positive) and "
            f"regime '{regime.current_regime.label}' in proven set"
        )
    return LiveEligibilityVerdict(
        version_id=version_id,
        eligible=eligible,
        forward_ready=forward_ready,
        forward_age_days=evidence.forward_age_days,
        net_return_pct=evidence.net_return_pct,
        min_days=evidence.min_days,
        regime_eligible=regime.eligible,
        current_regime=regime.current_regime,
        proven_regimes=regime.proven_regimes,
        overridden=overridden,
        reason=reason,
    )
