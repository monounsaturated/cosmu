# intent: the AUTHORITY feature — PROPRIETARY DATA, not a strategy. A lean store of (mostly Twitter) accounts +
# a COMPOSITE authority score derived from whether each account's past asset CALLS corroborated the later tape.
# This package is the whole feature: the typed ingest unit + the data-agnostic parser (`ingest`), the pure
# deterministic composite scorer (`scoring`: Brier · hit-rate · EV/payoff · magnitude · lead-time · consistency
# · top-3 movers · echo-discard), and the proprietary-data persistence (`store`). A high-score account LATER
# powers an LLM strategy that obeys its signals — that is OUT OF SCOPE here (this only SCORES; it never funds or
# fires an order). The LLM only EXTRACTS/formats the raw calls; the SCORE is math (no hallucination on the
# number). Replaces the retired autonomous "voice panel" / citation-PageRank machinery (see cosmu.ingest.voices_pass,
# now quarantined) with one lean, reviewable, offline-testable scoring dashboard.

from __future__ import annotations

from cosmu.authority.ingest import (
    DIRECTION_SYNONYMS,
    parse_call,
    parse_calls,
)
from cosmu.authority.models import (
    AccountCall,
    AuthorityScore,
    Direction,
    Mover,
    PricePoint,
    ResolvedCall,
)
from cosmu.authority.scoring import (
    resolve_call,
    score_account,
    score_accounts,
)
from cosmu.authority.store import (
    build_scoreboard,
    load_calls,
    load_scoreboard,
    persist_calls,
    persist_scoreboard,
    prices_from_bars,
)

__all__ = [
    "AccountCall",
    "AuthorityScore",
    "DIRECTION_SYNONYMS",
    "Direction",
    "Mover",
    "PricePoint",
    "ResolvedCall",
    "build_scoreboard",
    "load_calls",
    "load_scoreboard",
    "parse_call",
    "parse_calls",
    "persist_calls",
    "persist_scoreboard",
    "prices_from_bars",
    "resolve_call",
    "score_account",
    "score_accounts",
]
