# intent: PHASE 2 of "PageRank for credibility" — DETERMINISTIC OUTCOME RESOLUTION + per-author track record. NO
# LLM on this path: resolve each Phase-1 Claim against the OHLC bars we already hold (entry = price knowable at the
# claim's availability, exit = first bar at/after claim.ts + horizon), classify hit/miss with a flat band, and
# measure each call AGAINST THE BASE RATE of that (entity, horizon, direction). Per author we emit a Brier score,
# calibration error, hit-rate excess over base, and a single SKILL scalar that is a BRIER SKILL SCORE vs the base
# rate, SHRUNK for sample size — so a SPAMMER who only reproduces the base rate scores ~0 (no excess skill), a
# small-sample lucky author is shrunk toward 0, and only a genuinely-calibrated voice scores high. inputs: claims +
# OHLC bars + an injected `now`; outputs: ResolvedClaim list + AuthorTrackRecord per handle. invariants: PURE +
# offline + deterministic (the clock is injected, never wall-time); POINT-IN-TIME (entry uses only bars knowable at
# claim time, a claim whose horizon extends past `now` is PENDING — never resolved into the future); identical
# repeated claims are de-duped so raw volume can't inflate a record; honest — no bars → "no_data", never a fake hit.

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from cosmu.data.market import Bar
from cosmu.mind.claims import Claim, Direction

# Frozen, versioned transform — pinned so a downstream gate-passed survivor that depends on author track records
# stays reproducible. Bump whenever the resolution / scoring logic changes.
OUTCOME_RESOLVE_VERSION = "outcome-resolve-v1"

# A move smaller than this (in fractional return over the horizon) is "flat". Keeps a directional call from being
# credited for noise, and defines the "flat" class. Policy constant — never enters a strategy spec.
FLAT_BAND = 0.01

# Small-sample shrinkage: with few resolved calls the skill is pulled toward 0 (an unproven record is not a high
# one). shrink = n / (n + PRIOR_STRENGTH). A spammer (high n, base-rate accuracy) is NOT saved by this — their
# Brier Skill Score is ~0 regardless; this only stops a lucky handful of calls from reading as skill.
PRIOR_STRENGTH = 20.0

ResolveStatus = Literal["resolved", "pending", "no_data"]


# --------------------------------------------------------------------------- per-claim resolution


@dataclass(frozen=True)
class ResolvedClaim:
    """One claim scored against the bars. `status`: 'resolved' (entry+exit both knowable), 'pending' (horizon
    extends past `now` — we don't read the future), 'no_data' (no bar at/before the claim). `hit` is whether the
    claimed direction was realized (flat-band aware); `base_rate` is how often that direction happens
    unconditionally over the same horizon — the bar a real call must clear."""

    claim: Claim
    status: ResolveStatus
    entry_ts: datetime | None = None
    exit_ts: datetime | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    realized_return: float | None = None  # (exit - entry) / entry
    hit: bool | None = None
    base_rate: float | None = None        # P(claimed direction) unconditionally over this (entity, horizon)
    base_abs_move: float | None = None    # mean |move| over the base-rate windows (magnitude benchmark)


def _classify(r: float, band: float) -> Direction:
    """Classify a realized return into the claim vocabulary using the flat band."""
    if r > band:
        return "up"
    if r < -band:
        return "down"
    return "flat"


def _entry_bar(bars: list[Bar], at: datetime) -> Bar | None:
    """The last bar knowable at `at` (bar.ts <= at) — the price a voice could have acted on. Point-in-time."""
    chosen: Bar | None = None
    for b in bars:
        if b.ts <= at:
            chosen = b
        else:
            break
    return chosen


def _exit_bar(bars: list[Bar], target: datetime) -> Bar | None:
    """The first bar at/after `target` (the horizon's resolution bar). None if the bars don't reach that far."""
    for b in bars:
        if b.ts >= target:
            return b
    return None


def _base_rate(bars: list[Bar], horizon_days: int, direction: Direction, band: float) -> tuple[float | None, float | None]:
    """Unconditional P(direction) and mean |move| over every horizon-length window in the bars — the base rate a
    real call must beat (and the magnitude benchmark). Each bar is a window start; the exit is the first bar at/
    after start + horizon. Returns (None, None) if no full window exists."""
    horizon = timedelta(days=horizon_days)
    hits = 0
    total = 0
    abs_moves = 0.0
    for i, start in enumerate(bars):
        exit_b = _exit_bar(bars[i + 1 :], start.ts + horizon)
        if exit_b is None:
            continue
        entry_p = float(start.close)
        if entry_p == 0:
            continue
        r = (float(exit_b.close) - entry_p) / entry_p
        total += 1
        abs_moves += abs(r)
        if _classify(r, band) == direction:
            hits += 1
    if total == 0:
        return None, None
    return hits / total, abs_moves / total


def resolve_claim(
    claim: Claim,
    bars: list[Bar],
    *,
    now: datetime,
    flat_band: float = FLAT_BAND,
) -> ResolvedClaim:
    """Resolve ONE claim against one entity's ascending bars. Entry = last bar knowable at the claim's ts (point-
    in-time); exit = first bar at/after ts + horizon. A claim whose exit bar is missing OR lands after `now` is
    PENDING (we never resolve into the future). No bar at/before the claim → no_data."""
    bars = sorted(bars, key=lambda b: b.ts)
    if not bars:
        return ResolvedClaim(claim=claim, status="no_data")
    entry = _entry_bar(bars, claim.ts)
    if entry is None:
        return ResolvedClaim(claim=claim, status="no_data")
    target = claim.ts + timedelta(days=claim.horizon_days)
    exit_b = _exit_bar(bars, target)
    if exit_b is None or exit_b.ts > now:
        # horizon extends past what we have observed — pending, NOT a miss (no look-ahead into the future).
        base_rate, base_abs = _base_rate(bars, claim.horizon_days, claim.direction, flat_band)
        return ResolvedClaim(claim=claim, status="pending", base_rate=base_rate, base_abs_move=base_abs)
    entry_p = float(entry.close)
    if entry_p == 0:
        return ResolvedClaim(claim=claim, status="no_data")
    r = (float(exit_b.close) - entry_p) / entry_p
    hit = _classify(r, flat_band) == claim.direction
    base_rate, base_abs = _base_rate(bars, claim.horizon_days, claim.direction, flat_band)
    return ResolvedClaim(
        claim=claim,
        status="resolved",
        entry_ts=entry.ts,
        exit_ts=exit_b.ts,
        entry_price=entry_p,
        exit_price=float(exit_b.close),
        realized_return=r,
        hit=hit,
        base_rate=base_rate,
        base_abs_move=base_abs,
    )


def _dedupe(claims: list[Claim]) -> list[Claim]:
    """Collapse identical repeated calls (same handle/entity/direction/horizon at the same timestamp) to one, so
    raw spam volume can't inflate a record. Distinct claims are untouched."""
    seen: set[tuple] = set()
    out: list[Claim] = []
    for c in claims:
        key = (c.handle, c.entity, c.direction, c.horizon, c.ts)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def resolve_claims(
    claims: list[Claim],
    bars_by_entity: dict[str, list[Bar]],
    *,
    now: datetime,
    flat_band: float = FLAT_BAND,
) -> list[ResolvedClaim]:
    """Resolve every claim against its entity's bars (de-duping identical repeats first). Claims for an entity we
    hold no bars for resolve as no_data — named, never silently dropped."""
    out: list[ResolvedClaim] = []
    for claim in _dedupe(claims):
        bars = bars_by_entity.get(claim.entity, [])
        out.append(resolve_claim(claim, bars, now=now, flat_band=flat_band))
    return out


# --------------------------------------------------------------------------- per-author track record


@dataclass(frozen=True)
class AuthorTrackRecord:
    """A voice's DETERMINISTIC track record — the node weight Phase 3's authority ranker trusts. `skill` is the
    headline scalar in [0, 1]: a Brier Skill Score vs the base rate, shrunk for sample size. A spammer who only
    reproduces the base rate has BSS ~ 0 → skill ~ 0; a small-sample lucky voice is shrunk toward 0; only a
    genuinely-calibrated, sufficiently-tested voice scores high. influence ≠ authority — being loud earns nothing."""

    handle: str
    n_claims: int          # total claims attributed (incl. pending / no_data) — the volume
    n_resolved: int        # claims actually scored
    hit_rate: float        # fraction of resolved claims whose direction was realized
    base_hit_rate: float   # mean base rate across the same claims — what a coin-at-base-rate would hit
    excess_hit_rate: float # hit_rate - base_hit_rate (skill above chance)
    brier: float           # mean Brier score of the author's conviction-weighted forecasts (lower = better)
    brier_base: float      # mean Brier of the base-rate (climatology) forecast — the benchmark
    brier_skill_score: float  # 1 - brier/brier_base; > 0 beats the base rate, <= 0 does not
    calibration_error: float  # expected calibration error (|confidence - realized| across conviction buckets)
    avg_hit_magnitude: float  # mean |move| on correct calls
    magnitude_vs_base: float  # avg_hit_magnitude / base mean |move| — did they call BIG moves, not just any move
    skill: float           # the headline [0, 1] authority-ready scalar (deflated BSS)


def _forecast_prob(conviction: float) -> float:
    """Map a directional claim's conviction to the forecast probability that the claimed direction occurs. A
    conviction-0 call is a coin flip (0.5); conviction-1 approaches certainty. Clamped to [0.5, 0.99]."""
    return min(0.99, max(0.5, 0.5 + 0.5 * conviction))


def _calibration_error(pairs: list[tuple[float, int]]) -> float:
    """Expected calibration error across conviction buckets: |mean(forecast) - mean(outcome)| weighted by count.
    `pairs` is (forecast_prob, outcome 0/1). 0 = perfectly calibrated."""
    if not pairs:
        return 0.0
    buckets: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for p, o in pairs:
        idx = min(3, int(p * 4))  # 4 buckets over [0,1]
        buckets[idx].append((p, o))
    n = len(pairs)
    ece = 0.0
    for items in buckets.values():
        mean_p = sum(p for p, _ in items) / len(items)
        mean_o = sum(o for _, o in items) / len(items)
        ece += (len(items) / n) * abs(mean_p - mean_o)
    return ece


def score_author(handle: str, resolved: list[ResolvedClaim]) -> AuthorTrackRecord:
    """Build one author's track record from their resolved claims. Pure + deterministic; abstains to a 0 record
    when nothing is resolvable (honest — never a fabricated skill)."""
    n_claims = len(resolved)
    scored = [r for r in resolved if r.status == "resolved" and r.hit is not None]
    n = len(scored)
    if n == 0:
        return AuthorTrackRecord(
            handle=handle, n_claims=n_claims, n_resolved=0, hit_rate=0.0, base_hit_rate=0.0,
            excess_hit_rate=0.0, brier=0.0, brier_base=0.0, brier_skill_score=0.0,
            calibration_error=0.0, avg_hit_magnitude=0.0, magnitude_vs_base=0.0, skill=0.0,
        )
    hits = sum(1 for r in scored if r.hit)
    hit_rate = hits / n
    base_rates = [r.base_rate if r.base_rate is not None else 0.5 for r in scored]
    base_hit_rate = sum(base_rates) / n

    cal_pairs: list[tuple[float, int]] = []
    brier_sum = 0.0
    brier_base_sum = 0.0
    for r, p0 in zip(scored, base_rates, strict=True):
        o = 1 if r.hit else 0
        p = _forecast_prob(r.claim.conviction)
        brier_sum += (p - o) ** 2
        brier_base_sum += (p0 - o) ** 2
        cal_pairs.append((p, o))
    brier = brier_sum / n
    brier_base = brier_base_sum / n
    bss = (1.0 - brier / brier_base) if brier_base > 1e-9 else 0.0

    hit_mags = [abs(r.realized_return) for r in scored if r.hit and r.realized_return is not None]
    avg_hit_mag = (sum(hit_mags) / len(hit_mags)) if hit_mags else 0.0
    base_abs = [r.base_abs_move for r in scored if r.base_abs_move is not None]
    mean_base_abs = (sum(base_abs) / len(base_abs)) if base_abs else 0.0
    mag_vs_base = (avg_hit_mag / mean_base_abs) if mean_base_abs > 1e-9 else 0.0

    # Headline skill: positive Brier Skill Score (beats the base rate), shrunk for sample size. Spammer → ~0.
    shrink = n / (n + PRIOR_STRENGTH)
    skill = round(max(0.0, bss) * shrink, 4)

    return AuthorTrackRecord(
        handle=handle, n_claims=n_claims, n_resolved=n, hit_rate=round(hit_rate, 4),
        base_hit_rate=round(base_hit_rate, 4), excess_hit_rate=round(hit_rate - base_hit_rate, 4),
        brier=round(brier, 4), brier_base=round(brier_base, 4), brier_skill_score=round(bss, 4),
        calibration_error=round(_calibration_error(cal_pairs), 4), avg_hit_magnitude=round(avg_hit_mag, 4),
        magnitude_vs_base=round(mag_vs_base, 4), skill=skill,
    )


def score_authors(resolved: list[ResolvedClaim]) -> dict[str, AuthorTrackRecord]:
    """Group resolved claims by handle and build each voice's track record. Deterministic ordering by handle."""
    by_handle: dict[str, list[ResolvedClaim]] = defaultdict(list)
    for r in resolved:
        by_handle[r.claim.handle].append(r)
    return {handle: score_author(handle, rows) for handle, rows in sorted(by_handle.items())}
