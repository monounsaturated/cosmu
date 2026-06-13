# intent: the PRE-REGISTERED VOICE PANEL — the single, operator-edited list of voices (X handles, subreddits,
# RSS/newsletter feeds) the credibility pipeline follows, plus the hard per-pass cost caps. inputs: none (this
# IS the configuration); outputs: VOICE_PANEL + entity→bar-symbol routing + caps the voices pass enforces.
# invariants: the panel is PRE-REGISTERED — a voice is added BEFORE its future calls are scored, never because
# a post went viral after the fact (that is survivorship selection, the exact bias the pipeline exists to kill);
# the pass collects COMPLETE recent timelines of panel voices, never individual cherry-picked posts; an empty
# panel means the pass honestly does nothing (no fabricated sources). Edit THIS file to register voices — one
# line each, with a one-line WHY so the registration reasoning is on the record.

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Platform = Literal["x", "reddit", "rss"]


@dataclass(frozen=True)
class Voice:
    """One followed voice. `handle` is platform-shaped: '@name' for X, 'u/name' or 'r/sub' for Reddit, a feed
    URL for RSS. `why` is the registration rationale — written at ADD time, before any outcome is known."""

    handle: str
    platform: Platform
    why: str


# The panel. EMPTY by default — registering a voice is a deliberate operator act (pre-registration is the
# anti-survivorship discipline). Examples of the shape:
#   Voice("@example_analyst", "x", "macro analyst; called the 2024-08 vol spike before the tape moved"),
#   Voice("r/CryptoMarkets", "reddit", "broad retail sentiment proxy; breadth not skill"),
#   Voice("https://example.substack.com/feed", "rss", "on-chain research letter; slow but original"),
VOICE_PANEL: tuple[Voice, ...] = ()

# Claim entities (the extractor emits short tickers like "BTC") → the venue symbol whose bars resolve the
# claim. An entity with no mapping resolves as no_data (named, never guessed). Extend as the panel widens.
ENTITY_BARS_SYMBOL: dict[str, str] = {
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT", "BNB": "BNBUSDT",
    "XRP": "XRPUSDT", "DOGE": "DOGEUSDT", "ADA": "ADAUSDT", "AVAX": "AVAXUSDT",
    "LINK": "LINKUSDT", "DOT": "DOTUSDT", "LTC": "LTCUSDT",
}

# Hard per-pass cost caps (the LLM bill is bounded by these, not by cron cadence):
MAX_POSTS_PER_VOICE_PER_PASS = 25   # newest-N timeline pull per voice per pass
MAX_EXTRACTIONS_PER_PASS = 100      # NEW posts sent to the claim extractor per pass, across the whole panel
