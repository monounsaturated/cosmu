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


# The panel. Registering a voice is a deliberate, PRE-REGISTERED operator act (the anti-survivorship discipline:
# a voice is added BEFORE its future calls are scored, with a falsifiable `why` on the record). This STARTER panel
# is conservative and diverse — a mix of genuinely-early analysts, an on-chain desk, a macro voice, a funding/
# derivs voice, and breadth proxies — every entity it speaks on is in ENTITY_BARS_SYMBOL below. None of these
# voices is asserted to HAVE skill: the `why` is the testable HYPOTHESIS, and the deterministic price-anchored
# scoreboard (Brier-skill vs base rate, echo-disconfirmed) will confirm or refute it OOS. Expect the honest first
# verdict to be "0/N carry skill after the base rate" — that is the machine working. The OPERATOR edits this list;
# remove or add a line and the next pass picks it up. Keyless platforms (reddit/rss) run with no API key; X needs
# XAI_API_KEY (degrades to [] honestly without it).
VOICE_PANEL: tuple[Voice, ...] = (
    # --- genuinely-early directional analysts (the "called it first" hypothesis) ---
    Voice("@CredibleCrypto", "x", "swing-trader who posts dated, falsifiable BTC/ETH levels ahead of moves; test whether the calls lead the tape or echo it"),
    Voice("@RaoulGMI", "x", "ex-GLG macro PM (Real Vision); frames BTC/ETH on a liquidity/cycle thesis with a horizon — test foresight vs hindsight narration"),
    Voice("@ColdBloodShill", "x", "alt-focused TA who publishes timestamped ETH/SOL/LINK setups; primacy candidate — is he first or an echo of the move"),
    # --- macro / cross-asset voice (the "right regime, right asset class" hypothesis) ---
    Voice("@CryptoHayes", "x", "Arthur Hayes — funding/liquidity-driven macro essays mapping rates & USD to BTC; test if the directional macro reads beat the BTC base rate"),
    # --- funding / derivatives desk (the "positioning-aware" hypothesis) ---
    Voice("@Tradermayne", "x", "derivs-native trader who calls funding/positioning flushes on BTC/SOL; test whether the perp-state reads precede the move (lead-lag)"),
    Voice("@52kskew", "x", "options/derivs flow commentator (skew, gamma) on BTC/ETH; hypothesis: derivs-microstructure reads carry short-horizon foresight"),
    # --- on-chain research desk (the "original data, slow but causal" hypothesis) ---
    Voice("@glassnode", "x", "on-chain analytics desk; data-driven BTC/ETH supply/flow reads — test whether the directional framing leads price or merely describes it"),
    Voice("https://insights.glassnode.com/feed/", "rss", "Glassnode 'Week On-Chain' newsletter — long-form on-chain BTC/ETH research; original, slow, keyless — a low-frequency causal candidate"),
    Voice("@MustStopMurad", "x", "narrative/rotation caller across SOL/AVAX/LINK alts; hypothesis: early on rotations — but a strong echo/hype risk the disconfirmer must catch"),
    # --- breadth / retail sentiment proxies (NOT skill — the base-rate control) ---
    Voice("r/CryptoCurrency", "reddit", "broad retail sentiment proxy (keyless); breadth not skill — expected to score ~base-rate, the control that proves the metric rewards skill not loudness"),
    Voice("r/ethfinance", "reddit", "ETH-focused community (keyless); a more curated retail crowd than r/CryptoCurrency — test if the curation buys any excess over base rate"),
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
