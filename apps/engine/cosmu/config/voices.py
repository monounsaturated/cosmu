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


# --------------------------------------------------------------------------------------------------------------
# THE STARTER PANEL — minimal, KEYLESS, easy to extend (the template default; see docs/epics/llm-lane-template.md).
# --------------------------------------------------------------------------------------------------------------
# Registering a voice is a deliberate, PRE-REGISTERED operator act (the anti-survivorship discipline: a voice is
# added BEFORE its future calls are scored, with a falsifiable `why` on the record). This MINIMAL panel is two
# voices on KEYLESS, free sources (Reddit public JSON + RSS) — NO X (which needs XAI_API_KEY) — so the whole lane
# runs at ~$0 with no key. NEITHER voice is asserted to HAVE skill: the `why` is the testable HYPOTHESIS, and the
# deterministic price-anchored scoreboard (Brier-skill vs base rate, echo-disconfirmed) confirms or refutes it OOS.
# Expect the honest first verdict to be "0/2 carry skill after the base rate" — that is the machine working.
#
# The OPERATOR edits this list (FLEXIBLE — not locked): add or remove a line and the next pass picks it up. Keep
# it small and keyless; widen it in a future chat. Every entity a voice speaks on should be in ENTITY_BARS_SYMBOL
# below, or its claims resolve as no_data (named, never guessed).
VOICE_PANEL: tuple[Voice, ...] = (
    # A broad retail crowd (keyless Reddit). HYPOTHESIS: breadth, not skill — the base-rate CONTROL that proves the
    # metric rewards calibrated foresight, not loudness. Expected to score ~base-rate; if it ever scores high the
    # metric is broken.
    Voice("r/CryptoCurrency", "reddit", "broad retail sentiment proxy (keyless); breadth not skill — the base-rate control that proves the scoreboard rewards skill not volume"),
    # An on-chain research desk (keyless RSS). HYPOTHESIS: original, slow, data-driven BTC/ETH reads that may LEAD
    # price rather than describe it — a low-frequency causal candidate the lead-lag tripwire will confirm or refute.
    Voice("https://insights.glassnode.com/feed/", "rss", "Glassnode 'Week On-Chain' newsletter (keyless RSS); original slow on-chain BTC/ETH research — test whether the directional framing leads the tape or merely narrates it"),
)

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


# --------------------------------------------------------------------------------------------------------------
# RATCHET — the LOCKED template decisions (see docs/epics/llm-lane-template.md for the full contract).
# These are the validated choices the template ratchets so a future chat EXTENDS rather than re-litigates them.
# What stays FLEXIBLE: the panel above (operator-edited), the source mix, the frequency, and the model id below
# (swappable — it is a constant, not a hardcoded call site). What is LOCKED: extraction runs on an OpenRouter
# `:free` variant (~$0), retrieval is keyless-first, and the whole lane is OBSERVE-ONLY (it proposes + scores; the
# Gate alone funds).
# --------------------------------------------------------------------------------------------------------------

# LOCKED: extraction uses an OpenRouter FREE model (a `:free` variant). `:free` models do NOT draw down the $5
# OpenRouter credit, so the lane is ~$0. SWAPPABLE: change this one constant to point at a different free model;
# the llm.py seam and the claim extractor read it — there is no other hardcoded model id on the live path.
OPENROUTER_FREE_MODEL = "meta-llama/llama-3.3-70b-instruct:free"

# LOCKED (default): the lane runs in MOCK / offline mode unless this env flag is explicitly set truthy. Mock mode
# = canned posts → deterministic claims → NO network, NO LLM spend (the CI/test default). Live-cheap mode (keyless
# Reddit/RSS retrieval + the OpenRouter `:free` extractor) is opt-in behind VOICES_LIVE_ENABLED=1 so a cron tick
# can never accidentally spend or block. Observe-only either way — neither mode opens a track/position/order.
VOICES_LIVE_ENABLED_ENV = "VOICES_LIVE_ENABLED"
