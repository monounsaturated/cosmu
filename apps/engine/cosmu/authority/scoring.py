# intent: the COMPOSITE AUTHORITY SCORER — pure, deterministic, offline. Given an account's directional CALLS
# joined to the forward tape, it computes the per-call resolution (entry/exit, signed return, hit, base rate,
# echo flag, lead time) and the per-account composite. Brier alone is NOT enough — it ignores PAYOFF — so the
# composite fuses: calibration (Brier skill vs the base rate, sample-shrunk — the math core kept for inspiration
# from the retired voices lane), being-right (hit-rate excess over base), PROFIT (EV: cumulative return trading
# each call small, weighted HIGHEST — profit > hit-rate), magnitude (avg move when right), foresight (lead time),
# and gain spread (consistency — LOW when one spike carries the account). It also surfaces the TOP-3 movers per
# account (an account wrong 90% of the time but huge on the other 10% is interesting). invariants: PURE +
# deterministic (the clock is injected, never wall-time); POINT-IN-TIME (entry uses only tape knowable at the
# call, a horizon past `now` is PENDING — never resolved into the future); the LLM is NEVER on this path (the
# number is math, which kills hallucination); honest — no resolved calls → an UNTESTED row with None metrics,
# never a fabricated score; the only by-design inaccuracy is the lean echo discard (see ECHO_* below), which can
# only ever be OVER-strict, never lax.

from __future__ import annotations

import math
from collections import defaultdict
from datetime import timedelta
from typing import Mapping, Sequence

from cosmu.authority.models import (
    DIR_SIGN,
    AccountCall,
    AuthorityScore,
    Mover,
    PricePoint,
    ResolvedCall,
)

# Frozen, versioned transform — bump whenever the resolution / composite logic changes so a stored scoreboard
# stays attributable to the math that produced it.
AUTHORITY_SCORE_VERSION = "authority-composite-v1"

# ── Resolution policy (constants — never enter a strategy spec) ───────────────────────────────────────────────
# A move smaller than this fractional return over the horizon is "flat" — keeps a directional call from being
# credited for noise and defines the flat class.
FLAT_BAND = 0.01
# Default holding horizon for a call when the upstream gives none. Calls are coarse; 7 days is a sane neutral.
DEFAULT_HORIZON_DAYS = 7

# ── Echo discard (lean, by-design imprecise — see module intent) ──────────────────────────────────────────────
# A call is an ECHO if the claimed-direction move was ALREADY underway when it was tweeted: in the short window
# BEFORE the call, the price had already moved this far in the claimed direction. We do NOT try to find the true
# first-signal — a simple timestamp+price check. Accept it is inaccurate by design; the only failure mode we care
# about is being OVERLY STRICT, so the threshold is generous (a big pre-move) and the discount is partial, never 0.
ECHO_LOOKBACK_DAYS = 3.0
ECHO_MOVE_THRESHOLD = 0.03   # claimed-direction move already realized in the lookback → echo
ECHO_DISCOUNT = 0.4          # an echo call's payoff/credit is kept but down-weighted (never dropped)

# ── EV / payoff ──────────────────────────────────────────────────────────────────────────────────────────────
# "Traded small": each call is sized at this fraction of the book and the per-call signed return is COMPOUNDED.
# EV is the resulting cumulative return (0.20 == +20% over all of the account's resolved calls at this size).
EV_POSITION = 0.10
EV_SCALE = 1.0               # tanh squash scale for normalizing EV into [0,1] for the composite

# ── Lead time ────────────────────────────────────────────────────────────────────────────────────────────────
# A winning call "led" by the time the market took to realize this fraction of the eventual move after the call.
# A call already past it at tweet time (an echo) led by 0. Bigger lead = the call was earlier / more foresightful.
LEAD_CONFIRM_FRAC = 0.5

# ── Composite ────────────────────────────────────────────────────────────────────────────────────────────────
# Sample shrinkage: with few resolved calls the composite is pulled toward 0 (an unproven record is not a high
# one). Smaller than the voices lane's 20 — a per-account call panel is coarse and small by design.
PRIOR_STRENGTH = 8.0
# Component weights — PROFIT-forward (the operator: profit > hit-rate). Sum to 1.0.
W_EV = 0.40            # cumulative payoff — the headline
W_BSS = 0.20           # Brier skill vs base rate — calibration that beats chance
W_HIT_EXCESS = 0.12    # hit-rate above the unconditional base rate
W_CALIBRATION = 0.10   # 1 - calibration error (well-calibrated conviction)
W_LEAD = 0.10          # foresight (called it before it played out)
W_CONSISTENCY = 0.08   # gains spread across calls, not one lucky spike


# --------------------------------------------------------------------------- per-call resolution


def _at_or_before(series: Sequence[PricePoint], at) -> PricePoint | None:
    """The last sample knowable at `at` (ts <= at) — the price the account could have acted on. Point-in-time."""
    chosen: PricePoint | None = None
    for p in series:
        if p.ts <= at:
            chosen = p
        else:
            break
    return chosen


def _at_or_after(series: Sequence[PricePoint], target) -> PricePoint | None:
    """The first sample at/after `target` (the horizon's resolution sample). None if the tape doesn't reach it."""
    for p in series:
        if p.ts >= target:
            return p
    return None


def _base_rate(series: Sequence[PricePoint], horizon_days: int, direction: str) -> tuple[float | None, float | None]:
    """Unconditional P(direction) and mean |move| over every horizon-length window in the tape — the bar a real
    call must clear (and the magnitude benchmark). Returns (None, None) if no full window exists."""
    horizon = timedelta(days=horizon_days)
    hits = 0
    total = 0
    abs_moves = 0.0
    sign = DIR_SIGN[direction]
    for i, start in enumerate(series):
        exit_p = _at_or_after(series[i + 1 :], start.ts + horizon)
        if exit_p is None or start.price == 0:
            continue
        r = (exit_p.price - start.price) / start.price
        total += 1
        abs_moves += abs(r)
        if direction == "flat":
            if abs(r) <= FLAT_BAND:
                hits += 1
        elif r * sign > FLAT_BAND:
            hits += 1
    if total == 0:
        return None, None
    return hits / total, abs_moves / total


def _echo_and_lead(
    series: Sequence[PricePoint],
    call: AccountCall,
    entry: PricePoint,
    *,
    signed_return: float,
    horizon_days: int,
) -> tuple[bool, float, float]:
    """Lean echo detection + lead time. ECHO: in the `ECHO_LOOKBACK_DAYS` before the call, the price already moved
    `ECHO_MOVE_THRESHOLD` in the claimed direction (the move was underway — a late/echo call). LEAD: for a WINNING
    call, the days from the call until the claimed-direction move first reached `LEAD_CONFIRM_FRAC` of its eventual
    size (0 for a losing or echo call). Returns (is_echo, prior_move_frac, lead_days)."""
    sign = DIR_SIGN[call.direction]
    if sign == 0.0:  # flat calls have no directional move to echo or lead
        return False, 0.0, 0.0

    # Prior move: from the last sample before the lookback window to the entry.
    look_start = _at_or_before(series, call.ts - timedelta(days=ECHO_LOOKBACK_DAYS))
    prior_frac = 0.0
    if look_start is not None and look_start.price != 0:
        prior_frac = ((entry.price - look_start.price) / look_start.price) * sign
    is_echo = prior_frac >= ECHO_MOVE_THRESHOLD

    # Lead: time for the post-call move to confirm LEAD_CONFIRM_FRAC of the eventual signed move.
    lead_days = 0.0
    if signed_return > FLAT_BAND and not is_echo and entry.price != 0:
        target_frac = signed_return * LEAD_CONFIRM_FRAC
        horizon_end = call.ts + timedelta(days=horizon_days)
        for p in series:
            if p.ts <= call.ts or p.ts > horizon_end:
                continue
            move = ((p.price - entry.price) / entry.price) * sign
            if move >= target_frac:
                lead_days = (p.ts - call.ts).total_seconds() / 86400.0
                break
    return is_echo, prior_frac, lead_days


def resolve_call(
    call: AccountCall,
    series: Sequence[PricePoint],
    *,
    now,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> ResolvedCall:
    """Resolve ONE call against one asset's ascending tape. Entry = last sample knowable at the call (point-in-
    time); exit = first sample at/after call.ts + horizon. A call whose exit sample is missing OR lands after
    `now` is PENDING (never resolved into the future). No sample at/before the call → no_data."""
    series = sorted(series, key=lambda p: p.ts)
    if not series:
        return ResolvedCall(call=call, status="no_data", horizon_days=horizon_days)
    entry = _at_or_before(series, call.ts)
    if entry is None or entry.price == 0:
        return ResolvedCall(call=call, status="no_data", horizon_days=horizon_days)
    target = call.ts + timedelta(days=horizon_days)
    exit_p = _at_or_after(series, target)
    base_rate, base_abs = _base_rate(series, horizon_days, call.direction)
    if exit_p is None or exit_p.ts > now:
        # horizon extends past what we have observed — pending, NOT a miss (no look-ahead).
        return ResolvedCall(
            call=call, status="pending", horizon_days=horizon_days,
            base_rate=base_rate, base_abs_move=base_abs,
        )
    raw = (exit_p.price - entry.price) / entry.price
    sign = DIR_SIGN[call.direction]
    signed = raw * sign  # +ve == the move went the way the call claimed
    if call.direction == "flat":
        hit = abs(raw) <= FLAT_BAND
    else:
        hit = raw * sign > FLAT_BAND
    is_echo, prior_frac, lead_days = _echo_and_lead(
        series, call, entry, signed_return=signed, horizon_days=horizon_days
    )
    return ResolvedCall(
        call=call, status="resolved", horizon_days=horizon_days,
        entry_ts=entry.ts, exit_ts=exit_p.ts, entry_price=entry.price, exit_price=exit_p.price,
        raw_return=raw, signed_return=signed, abs_move=abs(raw), hit=hit,
        base_rate=base_rate, base_abs_move=base_abs,
        is_echo=is_echo, prior_move_frac=prior_frac, lead_days=lead_days,
    )


# --------------------------------------------------------------------------- composite scoring helpers


def _forecast_prob(conviction: float) -> float:
    """Map a directional call's conviction to the forecast probability the claimed direction occurs. Conviction 0
    is a coin flip (0.5); conviction 1 approaches certainty. Clamped to [0.5, 0.99]. (Mirrors the voices core.)"""
    return min(0.99, max(0.5, 0.5 + 0.5 * conviction))


def _calibration_error(pairs: list[tuple[float, int]]) -> float:
    """Expected calibration error across conviction buckets: |mean(forecast) - mean(outcome)| weighted by count.
    0 = perfectly calibrated. (Mirrors the voices core.)"""
    if not pairs:
        return 0.0
    buckets: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for p, o in pairs:
        buckets[min(3, int(p * 4))].append((p, o))
    n = len(pairs)
    ece = 0.0
    for items in buckets.values():
        mean_p = sum(p for p, _ in items) / len(items)
        mean_o = sum(o for _, o in items) / len(items)
        ece += (len(items) / n) * abs(mean_p - mean_o)
    return ece


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


# --------------------------------------------------------------------------- per-account composite


def score_account(
    account: str,
    platform: str,
    resolved: list[ResolvedCall],
    *,
    n_calls: int | None = None,
    prior_strength: float = PRIOR_STRENGTH,
    top_n_movers: int = 3,
) -> AuthorityScore:
    """Build one account's COMPOSITE row from its resolved calls. Pure + deterministic. An account with no
    resolved calls is UNTESTED — every resolved-only metric is None (never a fabricated 0); only counts + the
    last-call timestamp are reported. EV/payoff is weighted highest (profit > hit-rate)."""
    total_calls = n_calls if n_calls is not None else len(resolved)
    last_ts = max((r.call.ts for r in resolved), default=None)
    scored = [r for r in resolved if r.status == "resolved" and r.hit is not None and r.signed_return is not None]
    n = len(scored)
    if n == 0:
        return AuthorityScore(
            account=account, platform=platform, n_calls=total_calls, n_resolved=0, n_echo=0,
            last_call_ts=last_ts,
        )

    n_echo = sum(1 for r in scored if r.is_echo)

    # Hit-rate vs the unconditional base rate (being right vs the market just drifting that way).
    hits = sum(1 for r in scored if r.hit)
    hit_rate = hits / n
    base_rates = [r.base_rate if r.base_rate is not None else 0.5 for r in scored]
    base_hit_rate = sum(base_rates) / n

    # Brier + Brier skill score vs the climatology (base-rate) forecast.
    cal_pairs: list[tuple[float, int]] = []
    brier_sum = 0.0
    brier_base_sum = 0.0
    for r, p0 in zip(scored, base_rates, strict=True):
        o = 1 if r.hit else 0
        p = _forecast_prob(r.call.conviction)
        brier_sum += (p - o) ** 2
        brier_base_sum += (p0 - o) ** 2
        cal_pairs.append((p, o))
    brier = brier_sum / n
    brier_base = brier_base_sum / n
    bss = (1.0 - brier / brier_base) if brier_base > 1e-9 else 0.0
    calibration_error = _calibration_error(cal_pairs)

    # EV / payoff — each call traded small, COMPOUNDED, echoes down-weighted. The headline "profit" axis.
    equity = 1.0
    payoffs: list[float] = []
    for r in scored:
        pos = EV_POSITION * (ECHO_DISCOUNT if r.is_echo else 1.0)
        payoff = pos * float(r.signed_return)  # type: ignore[arg-type]
        equity *= 1.0 + payoff
        payoffs.append(payoff)
    ev = equity - 1.0

    # Magnitude when right; foresight; gain-spread consistency.
    right_moves = [abs(float(r.signed_return)) for r in scored if r.hit and r.signed_return is not None]
    avg_move_when_right = (sum(right_moves) / len(right_moves)) if right_moves else 0.0
    leads = [r.lead_days for r in scored if r.hit and not r.is_echo]
    avg_lead_days = (sum(leads) / len(leads)) if leads else 0.0
    pos_payoffs = [p for p in payoffs if p > 0.0]
    if pos_payoffs:
        consistency = 1.0 - (max(pos_payoffs) / sum(pos_payoffs))  # 1 spike dominating → ~0; spread out → ~1
    else:
        consistency = 0.0

    # Composite — profit-forward, normalized to [0,1], shrunk for sample size.
    ev_norm = 0.5 + 0.5 * math.tanh(ev / EV_SCALE)
    bss_norm = _clamp01(bss)
    hit_norm = _clamp01(0.5 + (hit_rate - base_hit_rate))
    cal_norm = _clamp01(1.0 - 2.0 * calibration_error)
    horizon = scored[0].horizon_days or DEFAULT_HORIZON_DAYS
    lead_norm = _clamp01(avg_lead_days / horizon)
    raw_composite = (
        W_EV * ev_norm
        + W_BSS * bss_norm
        + W_HIT_EXCESS * hit_norm
        + W_CALIBRATION * cal_norm
        + W_LEAD * lead_norm
        + W_CONSISTENCY * _clamp01(consistency)
    )
    shrink = n / (n + prior_strength)
    composite = _clamp01(raw_composite) * shrink

    # Top-N movers by PAYOFF (the "huge on 10%" surface) — deterministic ties broken by recency then asset.
    movers = sorted(
        scored,
        key=lambda r: (EV_POSITION * (ECHO_DISCOUNT if r.is_echo else 1.0) * float(r.signed_return), r.call.ts, r.call.asset),  # type: ignore[arg-type]
        reverse=True,
    )[:top_n_movers]
    top_movers = tuple(
        Mover(
            asset=r.call.asset, ts=r.call.ts, direction=r.call.direction,
            signed_return=float(r.signed_return),  # type: ignore[arg-type]
            payoff=EV_POSITION * (ECHO_DISCOUNT if r.is_echo else 1.0) * float(r.signed_return),  # type: ignore[arg-type]
            is_echo=r.is_echo,
        )
        for r in movers
    )

    return AuthorityScore(
        account=account, platform=platform, n_calls=total_calls, n_resolved=n, n_echo=n_echo,
        hit_rate=round(hit_rate, 4), base_hit_rate=round(base_hit_rate, 4),
        brier=round(brier, 4), brier_skill_score=round(bss, 4), calibration_error=round(calibration_error, 4),
        ev=round(ev, 6), avg_move_when_right=round(avg_move_when_right, 6), avg_lead_days=round(avg_lead_days, 4),
        consistency=round(_clamp01(consistency), 4), composite=round(composite, 4),
        top_movers=top_movers, last_call_ts=last_ts,
    )


def score_accounts(
    calls: Sequence[AccountCall],
    prices: Mapping[str, Sequence[PricePoint]],
    *,
    now,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    prior_strength: float = PRIOR_STRENGTH,
) -> list[AuthorityScore]:
    """Resolve every call against its asset's tape and build each account's composite row. Calls on an asset we
    hold no tape for resolve as no_data (counted in n_calls, never silently dropped). Deterministic ordering:
    composite DESC with UNTESTED (None composite) accounts last, then account name as a stable tiebreak."""
    by_account: dict[tuple[str, str], list[AccountCall]] = defaultdict(list)
    for c in calls:
        by_account[(c.account, c.platform)].append(c)

    scores: list[AuthorityScore] = []
    for (account, platform), account_calls in sorted(by_account.items()):
        resolved = [
            resolve_call(c, prices.get(c.asset, []), now=now, horizon_days=horizon_days)
            for c in sorted(account_calls, key=lambda c: (c.ts, c.asset, c.direction))
        ]
        scores.append(
            score_account(account, platform, resolved, n_calls=len(account_calls), prior_strength=prior_strength)
        )

    def _rank(s: AuthorityScore) -> tuple[int, float, str]:
        # composite DESC, None last; account name ASC tiebreak.
        return (0 if s.composite is not None else 1, -(s.composite or 0.0), s.account)

    return sorted(scores, key=_rank)


__all__ = [
    "AUTHORITY_SCORE_VERSION",
    "DEFAULT_HORIZON_DAYS",
    "ECHO_DISCOUNT",
    "ECHO_LOOKBACK_DAYS",
    "ECHO_MOVE_THRESHOLD",
    "EV_POSITION",
    "FLAT_BAND",
    "resolve_call",
    "score_account",
    "score_accounts",
]
