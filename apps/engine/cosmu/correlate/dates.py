# intent: turn a RAW Polymarket resolution string ("reopens before July 1", "in the next 7 days",
# "2026-07-01") into a structured, point-in-time-honest deadline — days-to-event + an horizon bucket — and
# normalize a raw (ts, prob) odds stream into a clean, clipped, deduped, sorted probability time series with
# signed move detection. This is the DATA-SHAPING layer the event monitor + the correlation-conviction template
# build on: a PM market's question carries a resolution deadline in free text, and the LLM/Conviction lane needs
# a number (days-to-event) to size horizon + a clean prob series to read a MOVE off of. Pure + deterministic
# (every parse is a pure function of (raw, as_of) — no clock surprises, offline), stdlib-only (no dateutil),
# never raises on garbage (an unparseable string yields a `basis="unparsed"` deadline=None, never an exception).

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

# ── horizon buckets (days-to-event → coarse label the template reads to size hold horizon) ────────────────────
_IMMINENT_DAYS = 2.0     # < 2d  → resolves almost now (highest news-attention, thinnest edge window)
_NEAR_DAYS = 14.0        # < 14d → near-dated (the sweet spot for a catalyst-driven correlated trade)
_MEDIUM_DAYS = 90.0      # < 90d → medium (the prob can drift a lot before resolution)
# ≥ 90d → "far"; deadline=None → "unknown"


@dataclass(frozen=True)
class NormalizedResolution:
    """The structured form of a raw Polymarket resolution string, computed as-of a given instant.

    `deadline` is the resolution instant in UTC (None when nothing parseable was found). `days_to_event` is
    `(deadline - as_of)` in fractional days (None when no deadline; CAN be negative if the phrase named a past
    date — reported honestly, never clamped). `basis` records HOW it was parsed so a caller can trust an
    "absolute" date more than a coarse "named" bucket. `horizon_bucket` is the coarse label the conviction
    template reads to size its hold horizon."""

    raw: str
    deadline: datetime | None
    days_to_event: float | None
    basis: str          # "absolute" | "relative" | "named" | "unparsed"
    horizon_bucket: str  # "imminent" | "near" | "medium" | "far" | "unknown"


_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_MONTH_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))  # longest-first so "september" wins over "sep"

# "July 1", "Jul 1st", "December 31, 2026", "1 July 2026" — month + day (+ optional year), ordinal-tolerant.
_RE_MONTH_DAY = re.compile(
    rf"\b(?P<month>{_MONTH_ALT})\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(?P<year>20\d{{2}}))?\b",
    re.IGNORECASE,
)
_RE_DAY_MONTH = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month>{_MONTH_ALT})\.?(?:,?\s+(?P<year>20\d{{2}}))?\b",
    re.IGNORECASE,
)
# ISO-ish "2026-07-01" (optionally with a time we ignore — the resolution DAY is the deadline).
_RE_ISO = re.compile(r"\b(?P<year>20\d{2})-(?P<month>\d{1,2})-(?P<day>\d{1,2})\b")
# "Month Year" with no day ("by August 2026", "end of July") → end of that month.
_RE_END_OF_MONTH = re.compile(rf"\bend of (?:the\s+)?(?P<month>{_MONTH_ALT})\b", re.IGNORECASE)
_RE_MONTH_YEAR = re.compile(rf"\b(?P<month>{_MONTH_ALT})\.?\s+(?P<year>20\d{{2}})\b", re.IGNORECASE)
# "in the next 7 days", "within 24 hours", "in 3 months", "next 2 weeks" — relative durations.
_RE_RELATIVE = re.compile(
    r"\b(?:in|within|next)\s+(?:the\s+)?(?:next\s+)?(?P<n>\d{1,3})\s+"
    r"(?P<unit>hour|hr|day|week|wk|month|mo|year|yr)s?\b",
    re.IGNORECASE,
)
# Bare "next week"/"next month" (n implicitly 1).
_RE_RELATIVE_ONE = re.compile(r"\bnext\s+(?P<unit>hour|day|week|month|year)\b", re.IGNORECASE)
# Bare 4-digit year, last-resort ("by 2026") → Dec 31 of that year.
_RE_BARE_YEAR = re.compile(r"\b(?P<year>20\d{2})\b")

_UNIT_DAYS = {
    "hour": 1 / 24, "hr": 1 / 24, "day": 1.0, "week": 7.0, "wk": 7.0,
    "month": 30.0, "mo": 30.0, "year": 365.0, "yr": 365.0,
}


def _eom(year: int, month: int) -> datetime:
    """Last instant we treat as a month's resolution: 00:00 UTC of the 1st of the NEXT month minus a day → the
    last calendar day at midnight. Kept simple (no calendar lib): step to next month, back up one day."""
    nm_year, nm_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return datetime(nm_year, nm_month, 1, tzinfo=UTC) - timedelta(days=1)


def _infer_year(month: int, day: int, as_of: datetime) -> int:
    """Year for a bare 'Month Day' (no year given): the NEXT occurrence on/after `as_of` (this year if it hasn't
    passed, else next year). A resolution deadline is always in the future relative to when the question is live."""
    try:
        this_year = datetime(as_of.year, month, day, tzinfo=UTC)
    except ValueError:  # e.g. Feb 30 — bail to as_of.year, the caller clamps via _safe_date
        return as_of.year
    return as_of.year if this_year >= as_of.replace(hour=0, minute=0, second=0, microsecond=0) else as_of.year + 1


def _safe_date(year: int, month: int, day: int) -> datetime | None:
    """A UTC midnight datetime, or None if (y,m,d) is not a real calendar date (the parse then falls through)."""
    try:
        return datetime(year, month, day, tzinfo=UTC)
    except ValueError:
        return None


def _bucket(days: float | None) -> str:
    if days is None:
        return "unknown"
    if days < _IMMINENT_DAYS:
        return "imminent"
    if days < _NEAR_DAYS:
        return "near"
    if days < _MEDIUM_DAYS:
        return "medium"
    return "far"


def normalize_resolution(raw: str, *, as_of: datetime | None = None) -> NormalizedResolution:
    """Parse a raw Polymarket resolution string into a structured, as-of-honest deadline. Tries, in priority
    order: ISO date → Month-Day(-Year) / Day-Month → relative duration ("in 7 days") → "end of <month>" /
    "Month Year" → bare year. Returns `basis="unparsed"`, `deadline=None` when nothing matches (NEVER raises).

    `as_of` defaults to now(UTC) but SHOULD be passed by callers that want determinism (tests, backtests) — the
    whole function is then a pure function of (raw, as_of)."""
    now = (as_of or datetime.now(tz=UTC)).astimezone(UTC)
    text = raw or ""

    deadline, basis = _parse_deadline(text, now)
    days = None if deadline is None else (deadline - now).total_seconds() / 86400.0
    return NormalizedResolution(
        raw=raw, deadline=deadline, days_to_event=days, basis=basis, horizon_bucket=_bucket(days),
    )


def _parse_deadline(text: str, now: datetime) -> tuple[datetime | None, str]:
    # 1) ISO date anywhere in the string (most explicit).
    m = _RE_ISO.search(text)
    if m:
        d = _safe_date(int(m["year"]), int(m["month"]), int(m["day"]))
        if d is not None:
            return d, "absolute"

    # 2) "Month Day[, Year]" / "Day Month[, Year]" (year inferred to the next occurrence when absent).
    for rx in (_RE_MONTH_DAY, _RE_DAY_MONTH):
        m = rx.search(text)
        if m:
            month = _MONTHS[m["month"].lower()]
            day = int(m["day"])
            year = int(m["year"]) if m["year"] else _infer_year(month, day, now)
            d = _safe_date(year, month, day)
            if d is not None:
                return d, "absolute"

    # 3) Relative duration ("in the next 7 days", "within 24 hours", "in 3 months").
    m = _RE_RELATIVE.search(text)
    if m:
        return now + timedelta(days=int(m["n"]) * _UNIT_DAYS[m["unit"].lower()]), "relative"
    m = _RE_RELATIVE_ONE.search(text)
    if m:
        return now + timedelta(days=_UNIT_DAYS[m["unit"].lower()]), "relative"

    # 4) Coarse named buckets — "end of <month>" / "Month Year" (no day) → end of that month.
    m = _RE_END_OF_MONTH.search(text)
    if m:
        month = _MONTHS[m["month"].lower()]
        # year: this year if the month-end hasn't passed, else next year.
        year = now.year if _eom(now.year, month) >= now else now.year + 1
        return _eom(year, month), "named"
    m = _RE_MONTH_YEAR.search(text)
    if m:
        return _eom(int(m["year"]), _MONTHS[m["month"].lower()]), "named"

    # 5) Named relatives without a month.
    low = text.lower()
    if "tomorrow" in low:
        return now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=2), "named"
    if "today" in low or "by end of day" in low or "eod" in low:
        return now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1), "named"
    if "this week" in low or "end of week" in low or "by friday" in low:
        return now + timedelta(days=7), "named"
    if "this month" in low or "end of month" in low or "eom" in low:
        return _eom(now.year, now.month), "named"
    if "end of year" in low or "eoy" in low or "year end" in low or "year-end" in low:
        return datetime(now.year, 12, 31, tzinfo=UTC), "named"

    # 6) Bare year, last resort ("by 2026") → Dec 31 of the next such year >= now.
    for m in _RE_BARE_YEAR.finditer(text):
        year = int(m["year"])
        if year >= now.year:
            return datetime(year, 12, 31, tzinfo=UTC), "named"

    return None, "unparsed"


# ── probability time series normalization + move detection ────────────────────────────────────────────────────

@dataclass(frozen=True)
class ProbPoint:
    """One point of a normalized probability series: an aware-UTC `ts` and a `prob` clipped to [0, 1]."""

    ts: datetime
    prob: float


@dataclass(frozen=True)
class ProbMove:
    """A signed probability MOVE between two consecutive points of a normalized series. `delta = prob - prev_prob`
    (positive = the YES probability ROSE). This is the unit the conviction template reads to decide a side +
    size on the correlated asset."""

    ts: datetime
    prob: float
    prev_ts: datetime
    prev_prob: float
    delta: float

    @property
    def abs_delta(self) -> float:
        return abs(self.delta)

    @property
    def span(self) -> timedelta:
        return self.ts - self.prev_ts


def _coerce_point(item: Any) -> tuple[datetime, float] | None:
    """Accept a raw (ts, value) tuple OR anything with `.ts`/`.value` (an AltDataPoint) → (aware-UTC ts, float),
    or None when the value is missing/NaN/non-finite (dropped, never zero-filled)."""
    if isinstance(item, tuple) and len(item) == 2:
        ts, val = item
    elif hasattr(item, "ts") and hasattr(item, "value"):
        ts, val = item.ts, item.value
    else:
        return None
    if not isinstance(ts, datetime):
        return None
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return (ts if ts.tzinfo else ts.replace(tzinfo=UTC)).astimezone(UTC), v


def normalize_prob_series(
    raw: Iterable[Any], *, clip: tuple[float, float] = (0.0, 1.0),
) -> list[ProbPoint]:
    """Turn a raw stream of (ts, prob) tuples / AltDataPoints into a clean probability series: coerce to aware
    UTC, drop missing/NaN/inf values (never zero-fill a gap), clip into `clip`, dedup by ts (LAST value wins —
    a re-poll of the same instant supersedes), and sort ascending by ts. Pure; empty in → empty out."""
    lo, hi = clip
    by_ts: dict[datetime, float] = {}
    for item in raw:
        coerced = _coerce_point(item)
        if coerced is None:
            continue
        ts, v = coerced
        by_ts[ts] = min(max(v, lo), hi)  # last write wins per ts
    return [ProbPoint(ts=ts, prob=by_ts[ts]) for ts in sorted(by_ts)]


def latest_move(series: list[ProbPoint]) -> ProbMove | None:
    """The MOST RECENT consecutive-point move (last two points), or None when the series has < 2 points."""
    if len(series) < 2:
        return None
    prev, cur = series[-2], series[-1]
    return ProbMove(
        ts=cur.ts, prob=cur.prob, prev_ts=prev.ts, prev_prob=prev.prob, delta=cur.prob - prev.prob,
    )


def detect_moves(
    series: list[ProbPoint], *, min_abs_delta: float = 0.05, max_span: timedelta | None = None,
) -> list[ProbMove]:
    """Every consecutive-point move whose |delta| ≥ `min_abs_delta` (default 5 percentage points). `max_span`
    optionally drops moves whose two points are further apart in time than the span (a 5pp move over a year is
    not a catalyst; a 5pp move over a day is). Series MUST be normalized first (sorted, deduped)."""
    out: list[ProbMove] = []
    for prev, cur in zip(series, series[1:], strict=False):
        delta = cur.prob - prev.prob
        if abs(delta) < min_abs_delta:
            continue
        mv = ProbMove(ts=cur.ts, prob=cur.prob, prev_ts=prev.ts, prev_prob=prev.prob, delta=delta)
        if max_span is not None and mv.span > max_span:
            continue
        out.append(mv)
    return out


__all__ = [
    "NormalizedResolution",
    "ProbMove",
    "ProbPoint",
    "detect_moves",
    "latest_move",
    "normalize_prob_series",
    "normalize_resolution",
]
