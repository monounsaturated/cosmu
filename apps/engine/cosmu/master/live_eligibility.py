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


def cell_id(version_id: str, symbol: str | None, venue_id: str | None) -> str:
    """The BRUT cell key — one tradeable triple (algorithm × asset × venue). The forward-proof readers below are
    re-keyed to this so a per-cell paper track proves ITSELF: a (version,SOL,binance) cell's clock/fills/marks are
    never read off a sibling (version,XRP,binance) cell. When symbol/venue are None the readers fall back to the
    VERSION-only key (legacy rows written before the per-cell migration, and the pre-existing version-wide callers
    in api/promotion which still pass version_id alone)."""
    return f"{version_id}:{symbol}:{venue_id}"


def _ref_ids(version_id: str, symbol: str | None, venue_id: str | None) -> tuple[str, ...]:
    """Ref-id candidates for a cell-scoped lookup, newest convention first: the cell key, then the legacy
    version-only key. A reader tries each in order so a per-cell row wins when present and a legacy version-only row
    is still honoured (fail-safe back-compat). When symbol/venue are None this collapses to (version_id,)."""
    if symbol is None and venue_id is None:
        return (version_id,)
    return (cell_id(version_id, symbol, venue_id), version_id)


def proven_regimes_for(store: Store, version_id: str, *, symbol: str | None = None, venue_id: str | None = None) -> set[str]:
    """Read a cell's proven-regime passport from its most recent track_opened event (written by the funder/loop
    when the deterministic gate opened the cell's track). The event is keyed to the BRUT cell (version:symbol:venue)
    with a version-only LEGACY fallback. Empty if the cell never opened a track — which the gate then treats as
    'never proven anywhere' (blocked)."""
    for ref in _ref_ids(version_id, symbol, venue_id):
        row = store.row(
            "SELECT payload FROM events WHERE kind = 'track_opened' AND ref_id = ? ORDER BY id DESC LIMIT 1",
            (ref,),
        )
        if not row:
            continue
        payload = row["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return set()
        return set(payload.get("proven_regimes") or [])
    return set()


def live_regime_verdict(store: Store, version_id: str, reference_bars, *, symbol: str | None = None, venue_id: str | None = None) -> LiveRegimeVerdict:
    """Decide whether `version_id` may trade live RIGHT NOW: True only if the current regime (from the
    reference series) is one the strategy proved positive PnL in. Never promotes — only blocks; an empty
    proven set is never eligible (fail-safe). Cell-scoped (version:symbol:venue) with a version-only fallback."""
    proven = proven_regimes_for(store, version_id, symbol=symbol, venue_id=venue_id)
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


def paper_clock_origin(store: Store, version_id: str, *, symbol: str | None = None, venue_id: str | None = None) -> str | None:
    """A cell's paper clock origin: the ts of its FIRST `track_opened` event (the moment the deterministic gate
    opened the standalone cell track), keyed to the BRUT cell (version:symbol:venue) with a version-only LEGACY
    fallback. None when the cell never opened a track — which the maturity reads as age 0 (never matured),
    the fail-safe."""
    for ref in _ref_ids(version_id, symbol, venue_id):
        row = store.row(
            "SELECT MIN(ts) AS funded_at FROM events WHERE kind = 'track_opened' AND ref_id = ?",
            (ref,),
        )
        if row and row.get("funded_at"):
            return row["funded_at"]
    return None


def paper_net_return_pct(store: Store, version_id: str, *, symbol: str | None = None, venue_id: str | None = None) -> float:
    """The paper track's net-of-fee return % — the cell's own FORWARD evidence (tracks.return_pct, the standalone
    track that proves itself on real closes). Scoped to the BRUT cell (version,symbol,venue) with a version-only
    LEGACY fallback. 0.0 when no track exists yet, which the gate reads as 'not net-positive' (fail-safe)."""
    row = None
    if symbol is not None or venue_id is not None:
        row = store.row(
            "SELECT return_pct FROM tracks WHERE strategy_version_id = ? AND symbol = ? AND venue_id = ?",
            (version_id, symbol, venue_id),
        )
    if row is None:  # legacy fallback: version-only (pre-migration rows have NULL symbol/venue_id)
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


def forward_fill_count(
    store: Store,
    version_id: str,
    *,
    since: str | None = None,
    instrument_id: str | None = None,
    venue_id: str | None = None,
) -> int:
    """Count of REAL forward paper fills (executions is_paper=1) for a CELL, restricted to those AFTER the paper
    clock origin when `since` is given. The BRUT cell scope adds the cell's instrument + venue to the WHERE so a
    (version,SOL,binance) cell's fills are never counted off a sibling (version,XRP,binance) cell. When
    instrument_id/venue_id are None it falls back to the VERSION-only count (legacy / version-wide callers). Zero ⇒
    the cell never actually traded forward (a re-validation seed or a funded-but-unfilled registration is NOT
    forward evidence)."""
    clauses = ["strategy_version_id = ?", "CAST(is_paper AS INTEGER) = 1"]
    params: list[object] = [version_id]
    if instrument_id is not None:
        clauses.append("instrument_id = ?")
        params.append(instrument_id)
    if venue_id is not None:
        clauses.append("venue_id = ?")
        params.append(venue_id)
    if since is not None:
        clauses.append("ts >= ?")
        params.append(since)
    row = store.row(
        f"SELECT COUNT(*) AS n FROM executions WHERE {' AND '.join(clauses)}",
        tuple(params),
    )
    return int(row["n"]) if row and row.get("n") is not None else 0


def forward_evidence(store: Store, version_id: str, *, now: datetime | None = None, symbol: str | None = None, venue_id: str | None = None) -> PaperMaturity:
    """The paper maturity for a CELL, read from the store: paper_age_days from its track's clock origin +
    net_return_pct from its track. Scoped to the BRUT cell (version,symbol,venue) with a version-only fallback.
    `live_ready` = matured (>= PAPER_MIN_DAYS) AND net-positive — the SAME deterministic condition the leaderboard
    surfaces advisorily, here consulted as a HARD gate."""
    return maturity(
        paper_clock_origin(store, version_id, symbol=symbol, venue_id=venue_id),
        paper_net_return_pct(store, version_id, symbol=symbol, venue_id=venue_id),
        now=now,
    )


def forward_daily_returns(store: Store, version_id: str, *, limit: int = 4000, symbol: str | None = None, venue_id: str | None = None) -> list[float]:
    """The cell's FORWARD marked-return series, resampled to ONE return per UTC calendar day. Reads the
    scope='track' portfolio_snapshots (the paper clock's marked-equity trajectory) keyed to the BRUT cell
    (version:symbol:venue, version-only LEGACY fallback) and keeps the LAST equity of each day, so the marking
    FREQUENCY (a held basket may be re-marked several times a day by the tick) can NOT inflate the observation
    count or manufacture significance — the forward Sharpe is computed on NON-overlapping daily returns, the same
    non-overlap discipline the deploy lane uses. Empty when the track has no snapshot history yet (a never-marked
    track has no forward evidence, the honest fail-safe)."""
    rows: list[dict] = []
    for ref in _ref_ids(version_id, symbol, venue_id):
        rows = store.rows(
            "SELECT ts, equity FROM portfolio_snapshots WHERE scope = 'track' AND ref_id = ? ORDER BY ts ASC LIMIT ?",
            (ref, limit),
        )
        if rows:
            break
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


def forward_significance(store: Store, version_id: str, *, symbol: str | None = None, venue_id: str | None = None) -> ForwardSignificance:
    """Is the cell's FORWARD trajectory significantly positive, or just net-positive by a coin-flip? Computes the
    Probabilistic-Sharpe floor on the DAILY-resampled marked returns (scoped to the BRUT cell) and checks it clears
    PAPER_MIN_FORWARD_DSR with at least PAPER_MIN_FORWARD_OBS observations. Fails safe to NOT significant on too-few
    obs (the PSR estimate is then too noisy to trust — the track is blocked from AUTO-arming, but the human
    override still applies). Deterministic + LLM-free; reuses the SAME scorer PSR the cohort gate uses, so the
    forward bar speaks the gate's language. A zero-edge random walk clears 'net-positive' ~48% of the time but this
    floor only ~35% (Monte-Carlo, repo PSR machinery) — it carves the coin-flip down without blocking a genuine
    forward edge."""
    rets = forward_daily_returns(store, version_id, symbol=symbol, venue_id=venue_id)
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


def _cell_instrument_id(symbol: str | None, venue_id: str | None) -> str | None:
    """The catalog instrument id for a cell (symbol@venue), used to scope forward fills to the cell's own
    executions. None when symbol/venue aren't both given (version-wide call) or the instrument isn't in the
    catalog (then forward_fill_count falls back to venue-only / version-only scoping — never over-counts)."""
    if symbol is None or venue_id is None:
        return None
    try:
        from cosmu.spine.venue import default_catalog

        return default_catalog().instrument(symbol, venue_id).id
    except Exception:  # noqa: BLE001 — catalog miss → no instrument scope (fail-safe back-compat)
        return None


def live_eligibility_verdict(
    store: Store,
    version_id: str,
    reference_bars,
    *,
    override: bool = False,
    now: datetime | None = None,
    symbol: str | None = None,
    venue_id: str | None = None,
) -> LiveEligibilityVerdict:
    """Compose the HARD live-eligibility preconditions: forward evidence AND regime. Forward evidence is now THREE
    jointly-required facts — paper maturity (>= PAPER_MIN_DAYS), a net-positive return, AND a SIGNIFICANTLY positive
    forward Sharpe (`forward_significance`, so a net-positive coin-flip can no longer arm). `eligible` is True only
    when forward evidence AND regime both pass — UNLESS `override` is set, which waives ONLY the paper preconditions
    (a human's explicit override-launch of an unproven strategy, logged by the caller) and NEVER the regime gate.
    Deterministic, LLM-free; an unproven/underwater/insignificant/out-of-regime strategy fails safe to not-eligible."""
    regime = live_regime_verdict(store, version_id, reference_bars, symbol=symbol, venue_id=venue_id)
    evidence = forward_evidence(store, version_id, now=now, symbol=symbol, venue_id=venue_id)
    sig = forward_significance(store, version_id, symbol=symbol, venue_id=venue_id)
    # Forward-ready UNIONS two complementary hardenings of the same gate: the track must have actually TRADED
    # forward (>= MIN_FORWARD_FILLS real paper fills since the clock origin — not a re-validation seed) AND its
    # forward trajectory must be SIGNIFICANTLY positive (forward_dsr floor — not a net-positive coin-flip), on top of
    # calendar maturity + net-positive. All scoped to the BRUT cell (version,symbol,venue) with a version-only
    # fallback. The human `override` waives ALL forward preconditions (the data-backed-risk valve); the regime gate
    # is never waived.
    traded_forward = forward_fill_count(
        store, version_id,
        since=paper_clock_origin(store, version_id, symbol=symbol, venue_id=venue_id),
        instrument_id=_cell_instrument_id(symbol, venue_id), venue_id=venue_id,
    ) >= MIN_FORWARD_FILLS
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
