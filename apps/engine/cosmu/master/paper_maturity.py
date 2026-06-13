# intent: the paper maturity signal per SIM track — has a funded track lived long enough on real closes,
# AND is it net-of-fee positive, to be live-ready. inputs: a track's paper clock origin (its first
# track_opened mark) + the latest net-of-fee return; outputs: paper_age_days, net_return_pct, and a computed
# live_ready flag. This is the SINGLE deterministic definition of "matured + net-positive": the leaderboard /
# paper surface reads it advisorily, AND master/live_eligibility now consults the SAME flag as a HARD
# precondition for live-eligibility (a strategy may be armed only once it is forward-proven). invariants: fully
# deterministic + LLM-free (pure arithmetic on a clock + a return); never PROMOTES (it only ever withholds
# live_ready); the maturity threshold is the named PAPER_MIN_DAYS constant, never an inline magic number.

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from cosmu.config.settings import PAPER_MIN_DAYS


@dataclass(frozen=True)
class PaperMaturity:
    """The live-readiness read-out for one standalone paper track. `live_ready` = the track both matured
    (>= PAPER_MIN_DAYS) AND is net-of-fee positive. It is SURFACED advisorily on the leaderboard/paper
    page AND consulted as a HARD precondition by master/live_eligibility before a strategy may be armed. It is never
    consulted by the scorer/FDR gate (survival) — only by the live-arming path."""

    paper_age_days: float
    net_return_pct: float
    live_ready: bool
    min_days: int = PAPER_MIN_DAYS


def _parse_ts(ts: str) -> datetime | None:
    """Parse an ISO-8601 timestamp (as written by knowledge.store.utcnow) to an aware UTC datetime; None on any
    unparseable/empty value so the caller can fail safe (age 0 → not yet ready)."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def paper_age_days(funded_at: str | None, *, now: datetime | None = None) -> float:
    """Calendar days the paper clock has run for a track: from its first mark (`funded_at`, the track_opened
    ts) to `now` (defaults to UTC now). 0.0 when the origin is missing/unparseable or in the future — a track can
    never be 'more mature' than its own clock (fail safe)."""
    started = _parse_ts(funded_at) if funded_at else None
    if started is None:
        return 0.0
    current = now or datetime.now(tz=UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    delta = (current - started).total_seconds() / 86400.0
    return delta if delta > 0 else 0.0


def maturity(
    funded_at: str | None,
    net_return_pct: float,
    *,
    now: datetime | None = None,
    min_days: int = PAPER_MIN_DAYS,
) -> PaperMaturity:
    """Compute the paper maturity signal for one track. `live_ready` is True ONLY when the track has both
    run at least `min_days` of real-close forward time AND is net-of-fee positive. The leaderboard reads this
    advisorily; master/live_eligibility consults the SAME flag as a hard live-arming precondition."""
    age = paper_age_days(funded_at, now=now)
    ready = age >= min_days and net_return_pct > 0.0
    return PaperMaturity(
        paper_age_days=round(age, 2),
        net_return_pct=net_return_pct,
        live_ready=ready,
        min_days=min_days,
    )
