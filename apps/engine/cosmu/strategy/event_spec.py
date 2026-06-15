# intent: the first-class ALT-DATA / EVENT strategy TYPE — typed predicates over a MarketEvent and the
# point-in-time event→bar matcher the event backtest uses to decide which bars an entry fires on; inputs: a
# spec's EventSetup + a symbol's MarketEvent timeline; outputs: a per-bar "did a matching event become KNOWN in
# this bar's interval" boolean series; invariants: events join on `available_at` (the honest trading clock,
# NEVER `ts` — a scraped archive is available at scrape time, never backdated), no look-ahead (a bar only sees
# events whose available_at falls in its interval), and an unextracted event (magnitude/direction None) is kept
# only when the filter imposes no floor on that field. The typed models live on cosmu.strategy.spec (so a
# StrategySpec can carry them without an import cycle); this module re-exports them and owns the matcher.

from __future__ import annotations

from datetime import timedelta

from cosmu.data.events_store import MarketEvent
from cosmu.data.market import Bar

# Re-export the typed models from the spec module (single source of truth — the discriminator field on
# StrategySpec references them, so they must be defined there to avoid an import cycle). Importing here keeps
# `from cosmu.strategy.event_spec import EventFilter, EventEntrySignal, EventRegimeShift, EventSetup` working.
from cosmu.strategy.spec import (  # noqa: F401  (re-exported)
    EventEntrySignal,
    EventFilter,
    EventRegimeShift,
    EventSetup,
)

__all__ = [
    "EventFilter",
    "EventEntrySignal",
    "EventRegimeShift",
    "EventSetup",
    "event_matches",
    "event_fired_series",
    "apply_cooldown",
    "EVENT_FIRED_FEATURE",
]

# The synthetic point-in-time feature name the event entry condition reads. The event backtest materializes a
# {bar.ts.isoformat(): 1.0} series under this key (only on bars where a matching event became known) and feeds
# it to the SAME backtest engine as any alt feature, so the discrete entry reuses the indicator path verbatim.
# Dunder-bracketed so it can never collide with a real registry feature name.
EVENT_FIRED_FEATURE = "__event_fired__"


def event_matches(event: MarketEvent, filt: EventFilter) -> bool:
    """Does `event` satisfy `filt`? Point-in-time agnostic (the caller owns the available_at window); this is the
    field predicate only. An unextracted event (event_type/direction/magnitude still None) passes a field only
    when the filter leaves that field unconstrained — a magnitude/direction floor on an unscored event is a
    non-match, never silently treated as 0 (no fabrication)."""
    if filt.source is not None and event.provider != filt.source:
        return False
    if filt.kind is not None and event.event_type != filt.kind:
        return False
    if filt.direction is not None and event.direction != filt.direction:
        return False
    if filt.min_magnitude is not None:
        if event.magnitude is None or event.magnitude < filt.min_magnitude:
            return False
    return True


def event_fired_series(
    bars: list[Bar],
    events: list[MarketEvent],
    filt: EventFilter,
    *,
    symbol: str | None = None,
) -> dict[str, float]:
    """Build the point-in-time "a matching event became KNOWN in this bar's interval" series, keyed by
    bar.ts.isoformat() with value 1.0 on firing bars (absent => no event, the feature reads None there). Joins on
    `available_at` (the trading clock), NOT `ts`: a bar's interval is (prev_bar.ts, bar.ts], so an event we
    received inside that window is the first bar that could honestly trade on it — never the bar of the event's
    own publish time. `symbol`, when given, additionally requires the event to name that symbol (or be
    market-wide: symbols == () applies everywhere). Mirrors data/backtest.sum_funding_per_bar's interval math so
    deep pre-history never dumps onto bar 0."""
    if not bars or not events:
        return {}
    bars_sorted = sorted(bars, key=lambda b: b.ts)
    matching = sorted(
        (e for e in events if event_matches(e, filt) and _symbol_applies(e, symbol)),
        key=lambda e: e.available_at,
    )
    if not matching:
        return {}
    cadence = (bars_sorted[1].ts - bars_sorted[0].ts) if len(bars_sorted) >= 2 else timedelta(0)
    out: dict[str, float] = {}
    j, n = 0, len(matching)
    lo = bars_sorted[0].ts - cadence  # bar 0's lower bound (one cadence back); pre-window events are dropped
    for bar in bars_sorted:
        fired = False
        while j < n and matching[j].available_at <= bar.ts:
            if matching[j].available_at > lo:  # inside (lo, bar.ts]
                fired = True
            j += 1
        if fired:
            out[bar.ts.isoformat()] = 1.0
        lo = bar.ts
    return out


def apply_cooldown(bars: list[Bar], fired: dict[str, float], cooldown_bars: int) -> dict[str, float]:
    """Suppress re-firing for `cooldown_bars` bars after each kept firing, so one clustered news burst is one
    trade rather than a flurry. Walks bars in time order: the first firing is kept and starts a window in which
    every later firing is dropped; the next firing AFTER the window is kept and re-arms it. cooldown_bars <= 0
    (the default) returns `fired` unchanged — byte-identical to no cooldown."""
    if cooldown_bars <= 0 or not fired:
        return fired
    out: dict[str, float] = {}
    blocked_until = -1  # bar index up to and including which further firings are suppressed
    for i, bar in enumerate(sorted(bars, key=lambda b: b.ts)):
        key = bar.ts.isoformat()
        if key not in fired:
            continue
        if i <= blocked_until:
            continue
        out[key] = fired[key]
        blocked_until = i + cooldown_bars
    return out


def _symbol_applies(event: MarketEvent, symbol: str | None) -> bool:
    """A market-wide event (symbols == ()) applies to every symbol; otherwise the event must name `symbol`. When
    the caller passes no symbol (symbol is None) every event applies — the per-symbol filter is opt-in."""
    if symbol is None or not event.symbols:
        return True
    return symbol in event.symbols
