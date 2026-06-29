# intent: the CORRELATION-CONVICTION LANE — the flagship LLM-strategy archetype that uses Polymarket as a DATA
# SOURCE / attention signal (our hedge vs big funds who ignore it) to trade CORRELATED assets. A geopolitical/
# macro event's Polymarket probability MOVES → a correlated asset reacts (Hormuz-closure odds ↑ → oil ↑ → energy
# equities ↑ → broad equities ↓). The pipeline: monitor (poll Gamma for the watchlist event-types, forward-hoard
# PIT-stamped) → dates (normalize the resolution string + the probability series, detect moves) → correlation_map
# (the typed event→asset edges) → proposal (a typed, human-armed conviction trade on the correlated asset, with a
# named confound disconfirmer) → gate (the deterministic money envelope). This lane is NOT the quant Gate: the
# transfer can't be backtested cleanly, so it is routed through CONVICTION + a human arm, never funded statistically.
# Theory + citations: docs/research/polymarket-correlation-theory-2026-06-29.md.

from cosmu.correlate.correlation_map import (
    DEFAULT_WATCHLIST,
    AssetLink,
    EventType,
    event_type_by_key,
    infer_polarity,
    match_event_type,
    watchlist_ranked,
)
from cosmu.correlate.dates import (
    NormalizedResolution,
    ProbMove,
    ProbPoint,
    detect_moves,
    latest_move,
    normalize_prob_series,
    normalize_resolution,
)
from cosmu.correlate.gate import (
    CorrelationCaps,
    CorrelationConvictionGate,
    CorrelationState,
)
from cosmu.correlate.monitor import (
    DEFAULT_MIN_MOVE,
    EventMove,
    EventObservation,
    MonitorResult,
    PolymarketEventMonitor,
)
from cosmu.correlate.proposal import (
    CorrelationProposal,
    build_correlation_proposal,
    proposals_for_move,
)

__all__ = [
    "DEFAULT_MIN_MOVE",
    "DEFAULT_WATCHLIST",
    "AssetLink",
    "CorrelationCaps",
    "CorrelationConvictionGate",
    "CorrelationProposal",
    "CorrelationState",
    "EventMove",
    "EventObservation",
    "EventType",
    "MonitorResult",
    "NormalizedResolution",
    "PolymarketEventMonitor",
    "ProbMove",
    "ProbPoint",
    "build_correlation_proposal",
    "detect_moves",
    "event_type_by_key",
    "infer_polarity",
    "latest_move",
    "match_event_type",
    "normalize_prob_series",
    "normalize_resolution",
    "proposals_for_move",
    "watchlist_ranked",
]
