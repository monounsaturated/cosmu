# intent: the deterministic LIVE-ELIGIBILITY gate — what CAN be armed. A strategy may go live ONLY when it has
# BOTH (a) >= PAPER_MIN_DAYS of net-positive FORWARD evidence AND (b) the CURRENT market regime is one it
# proved itself in. inputs: the store (a version's proven-regime passport on track_opened, its paper clock
# origin, and its track's net-of-fee return) + a reference close series for the current regime; outputs: a yes/no
# eligibility with a reason. invariants: both preconditions are HARD and the gate only BLOCKS (never promotes);
# fully deterministic + out of any LLM path; missing evidence fails safe (blocked). A human still makes the final
# launch click — this only gates WHICH survivors are armable. `override` (default OFF, set by a human) waives ONLY
# the paper precondition for an explicit override-launch of an unproven strategy — never the regime gate.

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from cosmu.config.settings import PAPER_MIN_FORWARD_DSR, PAPER_MIN_FORWARD_OBS
from cosmu.knowledge.store import Store
from cosmu.master.paper_maturity import PaperMaturity, maturity
from cosmu.master.scorer import probabilistic_sharpe, sample_moments
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


def paper_clock_origin(store: Store, version_id: str) -> str | None:
    """A version's paper clock origin: the ts of its FIRST `track_opened` event (the moment the
    deterministic gate opened the standalone track). None when the version never opened a track — which the
    maturity reads as age 0 (never matured), the fail-safe."""
    row = store.row(
        "SELECT MIN(ts) AS funded_at FROM events WHERE kind = 'track_opened' AND ref_id = ?",
        (version_id,),
    )
    return row["funded_at"] if row and row.get("funded_at") else None


def paper_net_return_pct(store: Store, version_id: str) -> float:
    """The paper track's net-of-fee return % — the strategy's own per-version FORWARD evidence
    (tracks.return_pct, the standalone track that proves itself on real closes). 0.0 when no track exists yet,
    which the gate reads as 'not net-positive' (fail-safe)."""
    row = store.row("SELECT return_pct FROM tracks WHERE strategy_version_id = ?", (version_id,))
    if not row or row.get("return_pct") is None:
        return 0.0
    try:
        return float(row["return_pct"])
    except (TypeError, ValueError):
        return 0.0


# A track must have actually TRADED forward — not merely aged on the calendar, and not merely carry a
# re-validation-seeded return with no real positions (the perp arm) — before it can read live-ready. >= 1 REAL
# forward fill (executions is_paper=1, after the clock origin) is the minimum bar. A human override still waives
# this (it waives the whole forward-proof precondition); the regime gate is never waived.
MIN_FORWARD_FILLS = 1


def forward_fill_count(store: Store, version_id: str, *, since: str | None = None) -> int:
    """Count of REAL forward paper fills (executions is_paper=1) for a version, restricted to those AFTER the
    paper clock origin when `since` is given. Zero ⇒ the track never actually traded forward (a re-validation
    seed or a funded-but-unfilled registration is NOT forward evidence)."""
    if since is not None:
        row = store.row(
            "SELECT COUNT(*) AS n FROM executions WHERE strategy_version_id = ? "
            "AND CAST(is_paper AS INTEGER) = 1 AND ts >= ?",
            (version_id, since),
        )
    else:
        row = store.row(
            "SELECT COUNT(*) AS n FROM executions WHERE strategy_version_id = ? AND CAST(is_paper AS INTEGER) = 1",
            (version_id,),
        )
    return int(row["n"]) if row and row.get("n") is not None else 0


def forward_evidence(store: Store, version_id: str, *, now: datetime | None = None) -> PaperMaturity:
    """The paper maturity for a version, read from the store: paper_age_days from its track's clock
    origin + net_return_pct from its track. `live_ready` = matured (>= PAPER_MIN_DAYS) AND net-positive —
    the SAME deterministic condition the leaderboard surfaces advisorily, here consulted as a HARD gate."""
    return maturity(
        paper_clock_origin(store, version_id),
        paper_net_return_pct(store, version_id),
        now=now,
    )


def forward_daily_returns(store: Store, version_id: str, *, limit: int = 4000) -> list[float]:
    """The track's FORWARD marked-return series, resampled to ONE return per UTC calendar day. Reads the
    scope='track' portfolio_snapshots (the paper clock's marked-equity trajectory) and keeps the LAST equity of
    each day, so the marking FREQUENCY (a held basket may be re-marked several times a day by the tick) can NOT
    inflate the observation count or manufacture significance — the forward Sharpe is computed on NON-overlapping
    daily returns, the same non-overlap discipline the deploy lane uses. Empty when the track has no snapshot
    history yet (a never-marked track has no forward evidence, the honest fail-safe)."""
    rows = store.rows(
        "SELECT ts, equity FROM portfolio_snapshots WHERE scope = 'track' AND ref_id = ? ORDER BY ts ASC LIMIT ?",
        (version_id, limit),
    )
    if not rows:
        return []
    by_day: dict[str, float] = {}
    for r in rows:
        ts, eq = r.get("ts"), r.get("equity")
        if ts is None or eq is None:
            continue
        try:
            by_day[str(ts)[:10]] = float(eq)  # ORDER BY ts ASC ⇒ the last write of each day wins
        except (TypeError, ValueError):
            continue
    equities = [by_day[d] for d in sorted(by_day)]
    out: list[float] = []
    for prev, cur in zip(equities, equities[1:], strict=False):  # intentionally offset by one (pairwise)
        if prev > 0:
            out.append((cur - prev) / prev)
    return out


@dataclass(frozen=True)
class ForwardSignificance:
    """Whether the track's forward (paper) trajectory is SIGNIFICANTLY positive — not just net-positive by luck.
    `forward_dsr` = PSR(daily marked Sharpe vs 0) − 0.5 ∈ [−0.5, +0.5] (recentred so 0 = a coin-flip Sharpe)."""

    n_obs: int
    forward_dsr: float
    significant: bool


def forward_significance(store: Store, version_id: str) -> ForwardSignificance:
    """Is the track's FORWARD trajectory significantly positive, or just net-positive by a coin-flip? Computes the
    Probabilistic-Sharpe floor on the DAILY-resampled marked returns and checks it clears PAPER_MIN_FORWARD_DSR
    with at least PAPER_MIN_FORWARD_OBS observations. Fails safe to NOT significant on too-few obs (the PSR
    estimate is then too noisy to trust — the track is blocked from AUTO-arming, but the human override still
    applies). Deterministic + LLM-free; reuses the SAME scorer PSR the cohort gate uses, so the forward bar speaks
    the gate's language. A zero-edge random walk clears 'net-positive' ~48% of the time but this floor only ~35%
    (Monte-Carlo, repo PSR machinery) — it carves the coin-flip down without blocking a genuine forward edge."""
    rets = forward_daily_returns(store, version_id)
    n = len(rets)
    if n < PAPER_MIN_FORWARD_OBS:
        return ForwardSignificance(n_obs=n, forward_dsr=0.0, significant=False)
    sr, skew, kurt, _ = sample_moments(rets)
    dsr = probabilistic_sharpe(sr, n, skew, kurt, 0.0) - 0.5
    return ForwardSignificance(n_obs=n, forward_dsr=dsr, significant=dsr > PAPER_MIN_FORWARD_DSR)


@dataclass(frozen=True)
class LiveEligibilityVerdict:
    """The HARD live-eligibility verdict — what CAN be armed. `eligible` is True only when the strategy has BOTH
    forward evidence that is `forward_ready` AND is in a proven regime (`regime_eligible`). `forward_ready` now
    means THREE things jointly: >= PAPER_MIN_DAYS of clock, a net-positive return, AND a SIGNIFICANTLY positive
    forward Sharpe (`forward_dsr` > PAPER_MIN_FORWARD_DSR over >= PAPER_MIN_FORWARD_OBS daily marks) — so a track
    that is merely net-positive by a coin-flip can no longer arm. A human still makes the final launch click; this
    only gates the armable set. `overridden` is True when a human waived the paper preconditions via `override` to
    arm an UNPROVEN strategy (the caller logs the warning) — the regime gate is never waived. Never promotes — only
    blocks; missing evidence fails safe (not eligible)."""

    version_id: str
    eligible: bool
    forward_ready: bool
    paper_age_days: float
    net_return_pct: float
    min_days: int
    forward_obs: int
    forward_dsr: float
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
    """Compose the HARD live-eligibility preconditions: forward evidence AND regime. Forward evidence is now THREE
    jointly-required facts — paper maturity (>= PAPER_MIN_DAYS), a net-positive return, AND a SIGNIFICANTLY positive
    forward Sharpe (`forward_significance`, so a net-positive coin-flip can no longer arm). `eligible` is True only
    when forward evidence AND regime both pass — UNLESS `override` is set, which waives ONLY the paper preconditions
    (a human's explicit override-launch of an unproven strategy, logged by the caller) and NEVER the regime gate.
    Deterministic, LLM-free; an unproven/underwater/insignificant/out-of-regime strategy fails safe to not-eligible."""
    regime = live_regime_verdict(store, version_id, reference_bars)
    evidence = forward_evidence(store, version_id, now=now)
    sig = forward_significance(store, version_id)
    # Forward-ready UNIONS two complementary hardenings of the same gate: the track must have actually TRADED
    # forward (>= MIN_FORWARD_FILLS real paper fills since the clock origin — not a re-validation seed) AND its
    # forward trajectory must be SIGNIFICANTLY positive (forward_dsr floor — not a net-positive coin-flip), on top of
    # calendar maturity + net-positive. The human `override` waives ALL forward preconditions (the data-backed-risk
    # valve); the regime gate is never waived.
    traded_forward = forward_fill_count(store, version_id, since=paper_clock_origin(store, version_id)) >= MIN_FORWARD_FILLS
    forward_ready = evidence.live_ready and traded_forward and sig.significant
    eligible = (forward_ready or override) and regime.eligible
    overridden = bool(override) and not forward_ready and eligible
    if not regime.eligible:
        # The regime gate blocks regardless of paper maturity or any override.
        reason = regime.reason
    elif overridden:
        reason = (
            f"OVERRIDE: arming UNPROVEN strategy "
            f"({evidence.paper_age_days:.1f}d / {evidence.net_return_pct:+.2f}%, forward dsr "
            f"{sig.forward_dsr:+.3f} on {sig.n_obs} marks) — regime '{regime.current_regime.label}' ok"
        )
    elif not traded_forward:
        reason = (
            f"paper not proven: no real forward fills yet — has not started trading "
            f"(needs >= {MIN_FORWARD_FILLS} forward fill, then >= {evidence.min_days}d net-positive + significant)"
        )
    elif not evidence.live_ready:
        reason = (
            f"paper not proven: {evidence.paper_age_days:.1f}d / {evidence.net_return_pct:+.2f}% "
            f"(needs >= {evidence.min_days}d net-positive)"
        )
    elif not sig.significant:
        reason = (
            f"forward not significant: dsr {sig.forward_dsr:+.3f} on {sig.n_obs} daily marks "
            f"(needs > {PAPER_MIN_FORWARD_DSR:.2f} over >= {PAPER_MIN_FORWARD_OBS} marks) — net-positive but a "
            f"coin-flip-positive forward run is not proof of edge"
        )
    else:
        reason = (
            f"paper proven ({evidence.paper_age_days:.1f}d net-positive, forward dsr {sig.forward_dsr:+.3f} on "
            f"{sig.n_obs} marks) and regime '{regime.current_regime.label}' in proven set"
        )
    return LiveEligibilityVerdict(
        version_id=version_id,
        eligible=eligible,
        forward_ready=forward_ready,
        paper_age_days=evidence.paper_age_days,
        net_return_pct=evidence.net_return_pct,
        min_days=evidence.min_days,
        forward_obs=sig.n_obs,
        forward_dsr=sig.forward_dsr,
        regime_eligible=regime.eligible,
        current_regime=regime.current_regime,
        proven_regimes=regime.proven_regimes,
        overridden=overridden,
        reason=reason,
    )
