# intent: the MACHINE-READABLE cross-asset correlation map + Pareto-ranked Polymarket event-TYPE watchlist that
# the event monitor scans and the conviction template trades off of. This is the typed embodiment of the prose
# theory doc (docs/research/polymarket-correlation-theory-2026-06-29.md) — the doc carries the citations and the
# mechanism prose; THIS carries the structured (event-type → asset → direction/lag/mechanism/confound) edges the
# code consumes. Pure data + pure helpers (no I/O), so the watchlist is testable + diff-reviewable.
#
# DIRECTION SEMANTICS (the one subtlety): each AssetLink.direction is the asset's response when the event-type's
# underlying RISK RISES (escalation / disruption / the "bad" tail). The SIGN of a specific market's YES outcome is
# NOT fixed — "Strait of Hormuz CLOSES" (YES = risk up, polarity +1) and "Strait of Hormuz REOPENS" (YES = risk
# down, polarity −1) are the same event-type with opposite polarity. `infer_polarity()` reads the question text to
# decide; the conviction template then composes:  side = sign( sign(prob_delta) × polarity × link.direction ).

from __future__ import annotations

from dataclasses import dataclass

# ── asset classes (kept coarse — the template only needs the bucket for guardrail defaults) ────────────────────
COMMODITY = "commodity"
EQUITY_ETF = "equity_etf"
CRYPTO = "crypto"
FX = "fx"
RATES = "rates"
VOLATILITY = "volatility"


@dataclass(frozen=True)
class AssetLink:
    """One correlated-asset edge of an event-type. `direction` is the asset's response when the event-type's RISK
    RISES (+1 = the asset goes UP on escalation, −1 = DOWN). `confound` is the NAMED alternative cause of an
    observed asset move — the seed of the conviction proposal's mandatory disconfirmer (was the move THIS event,
    or the confound?)."""

    asset: str            # a liquid, tradable symbol (ETF / crypto pair) the operator can reach
    asset_class: str
    direction: int        # +1 | −1: asset response when the event-type's RISK RISES
    lag: str              # "immediate" | "minutes" | "hours" | "days" — how fast the asset reacts
    strength: str         # "strong" | "moderate" | "weak" — qualitative linkage confidence
    mechanism: str        # cited plain-English mechanism (full citation in the theory doc)
    confound: str         # the named confounder (the disconfirmer seed)


@dataclass(frozen=True)
class EventType:
    """A Polymarket event-TYPE on the watchlist: how to discover its markets (keywords/tags), how to read a
    market's polarity (does YES mean risk up or down), its correlated-asset links, and WHY it ranks where it does
    (Pareto rank, skeptical edge note). `pm_leads` flags the event-types where the prediction market tends to
    move BEFORE the correlated asset — the only case a PM-driven trade has timing edge rather than chasing a move
    already priced in."""

    key: str
    label: str
    rank: int             # Pareto rank — 1 = highest ROI for a small autonomous fund
    pm_leads: bool        # does the PM tend to LEAD the correlated asset? (edge condition)
    edge_note: str        # skeptical note on where the edge is / isn't
    discovery_keywords: tuple[str, ...]   # substrings matched against a market's question (lowercased)
    gamma_tags: tuple[str, ...]           # Polymarket Gamma event tags to scan
    risk_up_keywords: tuple[str, ...]     # in the question → YES means the RISK is RISING (polarity +1)
    risk_down_keywords: tuple[str, ...]   # in the question → YES means the RISK is FALLING (polarity −1)
    links: tuple[AssetLink, ...]


# ── the Pareto-ranked watchlist ───────────────────────────────────────────────────────────────────────────────
# Ranking criteria (see theory doc §3): (a) cleanliness of the asset linkage, (b) Polymarket liquidity of the
# event family, (c) does the PM LEAD the asset (edge) or lag it (no edge), (d) confound risk. The top ranks are
# supply-shock / binary-catalyst families where the asset linkage is cleanest and the PM most plausibly leads.

DEFAULT_WATCHLIST: tuple[EventType, ...] = (
    EventType(
        key="middle_east_oil",
        label="Middle-East conflict / oil-supply shock",
        rank=1,
        pm_leads=True,
        edge_note=(
            "Cleanest linkage on the board: an oil-supply tail (Hormuz, Iran–Israel strikes, OPEC) maps near-"
            "mechanically to crude, and Polymarket's geopolitical markets often reprice an escalation HOURS "
            "before the oil tape fully does. Confound is real (inventory prints, demand) — carry the disconfirmer."
        ),
        discovery_keywords=(
            "hormuz", "strait", "iran", "israel", "opec", "oil", "crude", "saudi", "middle east",
            "nuclear deal", "ceasefire",
        ),
        gamma_tags=("Geopolitics", "Middle East", "War"),
        risk_up_keywords=("close", "closes", "attack", "strike", "war", "invade", "escalat", "block", "halt"),
        risk_down_keywords=("reopen", "ceasefire", "deal", "peace", "de-escalat", "resolve", "lift"),
        links=(
            AssetLink("USO", COMMODITY, +1, "minutes", "strong",
                      "Crude is the first-order claim on Gulf supply; a credible Hormuz/Iran disruption removes "
                      "barrels and spikes the front of the curve (≈20% of seaborne crude transits Hormuz).",
                      "An EIA/API inventory print or an OPEC quota change moved oil the same day."),
            AssetLink("XLE", EQUITY_ETF, +1, "hours", "strong",
                      "Energy equities track crude with a beta; producers' cash flows rise with the oil price.",
                      "A broad-equity risk-off day dragged XLE down even as crude rose (beta to SPY)."),
            AssetLink("JETS", EQUITY_ETF, -1, "hours", "moderate",
                      "Airlines are short crude (jet fuel is a top cost); a supply spike compresses margins.",
                      "Airline-specific news (capacity, demand) or broad equities, not the oil leg."),
            AssetLink("GLD", COMMODITY, +1, "hours", "moderate",
                      "Gold is the safe-haven bid in a geopolitical-risk spike; real-rate moves can offset.",
                      "A USD/real-rate move (Fed) drove gold independently of the conflict."),
            AssetLink("ITA", EQUITY_ETF, +1, "days", "moderate",
                      "Defense primes rerate on a higher-conflict regime (order-book expectations).",
                      "Budget/appropriations news, not the specific conflict probability."),
            AssetLink("SPY", EQUITY_ETF, -1, "hours", "weak",
                      "An oil shock is a stagflationary tax on the broad market; the effect is small and noisy.",
                      "Almost anything — SPY has a thousand drivers; the weakest, most-confounded leg."),
        ),
    ),
    EventType(
        key="crypto_etf_regulation",
        label="Crypto ETF approval / regulation / listing",
        rank=2,
        pm_leads=True,
        edge_note=(
            "The canonical Polymarket lead: binary regulatory catalysts (a spot-ETF approval by a date, a "
            "favorable ruling) are exactly what prediction markets price well, and the crypto asset is a direct "
            "claim on the outcome. The 2024 ETH-ETF re-rating is the textbook case. Edge decays as the date nears."
        ),
        discovery_keywords=(
            "etf", "bitcoin", "ethereum", "solana", "sec", "crypto", "approve", "spot etf", "btc", "eth",
        ),
        gamma_tags=("Crypto", "Regulation", "SEC"),
        risk_up_keywords=("approve", "approved", "listing", "legal", "win", "pass"),  # YES = bullish-for-asset
        risk_down_keywords=("reject", "denied", "ban", "delay", "sue", "lawsuit"),
        links=(
            AssetLink("BTCUSDT", CRYPTO, +1, "minutes", "strong",
                      "A spot-ETF approval / friendly ruling opens regulated demand; BTC is the direct claim and "
                      "reprices fast on the headline.",
                      "A macro risk-on/off move (Fed, equities) drove BTC, not the regulatory event."),
            AssetLink("ETHUSDT", CRYPTO, +1, "minutes", "strong",
                      "Same mechanism on ETH for ETH-specific catalysts (the 2024 ETH-ETF surprise is the case).",
                      "BTC-led beta dragged ETH; the move was not ETH-idiosyncratic."),
            AssetLink("COIN", EQUITY_ETF, +1, "minutes", "moderate",
                      "Coinbase's revenue is levered to crypto volume + a friendlier US regime; a direct equity "
                      "proxy for the regulatory outcome.",
                      "An earnings print or company-specific news, not the regulatory probability."),
            AssetLink("MSTR", EQUITY_ETF, +1, "minutes", "moderate",
                      "MicroStrategy is a leveraged BTC holding; it amplifies BTC on a catalyst.",
                      "Equity-financing / dilution news specific to MSTR, or BTC beta."),
        ),
    ),
    EventType(
        key="fed_rate_decision",
        label="Fed rate decision / CPI / monetary policy",
        rank=3,
        pm_leads=False,
        edge_note=(
            "Strongest, cleanest mechanism — but the LOWEST edge: rates/FX/gold price a Fed move within seconds "
            "and the fixed-income market is far deeper than Polymarket, so the PM LAGS rather than leads. Trade "
            "this as confirmation/context, not as a lead signal. Heavy confound from the data calendar."
        ),
        discovery_keywords=(
            "fed", "fomc", "rate cut", "rate hike", "interest rate", "powell", "cpi", "inflation",
            "basis points",  # NOT "recession" — that routes to us_recession_macro (a distinct event-type)
        ),
        gamma_tags=("Economy", "Fed", "Finance"),
        risk_up_keywords=("hike", "raise", "higher", "no cut", "hold"),    # YES = HAWKISH (risk = tighter policy)
        risk_down_keywords=("cut", "lower", "ease", "pause", "dovish"),     # YES = DOVISH
        links=(
            AssetLink("TLT", EQUITY_ETF, -1, "immediate", "strong",
                      "Long Treasuries fall when policy turns HAWKISH (yields up = price down).",
                      "A growth/CPI surprise moved yields independent of the policy-path probability."),
            AssetLink("UUP", FX, +1, "immediate", "strong",
                      "The dollar rallies on a hawkish path (rate-differential bid).",
                      "A foreign-CB move (ECB/BoJ) drove the cross, not the Fed leg."),
            AssetLink("GLD", COMMODITY, -1, "immediate", "moderate",
                      "Gold falls when real rates rise on a hawkish path (it pays no yield).",
                      "A safe-haven/geopolitical bid offset the rate effect."),
            AssetLink("SPY", EQUITY_ETF, -1, "immediate", "moderate",
                      "Equities (esp. long-duration growth) de-rate on a hawkish path (higher discount rate).",
                      "Earnings/idiosyncratic flows; SPY is over-determined."),
            AssetLink("BTCUSDT", CRYPTO, -1, "minutes", "weak",
                      "Crypto trades as a long-duration risk asset — soft to a hawkish liquidity path.",
                      "Crypto-idiosyncratic flow (regulation, ETF) usually dominates the macro leg."),
        ),
    ),
    EventType(
        key="russia_ukraine_energy",
        label="Russia–Ukraine / European energy",
        rank=4,
        pm_leads=True,
        edge_note=(
            "Clean on European gas + wheat + defense, but the most-liquid Polymarket markets are ceasefire-timing "
            "(noisy, headline-whipsawed). Best traded on a decisive escalation/de-escalation step, not the daily "
            "ceasefire-odds chop."
        ),
        discovery_keywords=(
            "russia", "ukraine", "putin", "zelensky", "ceasefire", "nato", "nord stream", "gas", "wheat",
        ),
        gamma_tags=("Geopolitics", "War", "Russia"),
        risk_up_keywords=("invade", "escalat", "attack", "strike", "cut off", "halt", "war"),
        risk_down_keywords=("ceasefire", "peace", "deal", "withdraw", "truce", "end"),
        links=(
            AssetLink("UNG", COMMODITY, +1, "hours", "moderate",
                      "European supply fear bids natural gas (TTF leads; UNG is the US-traded proxy).",
                      "A US weather/storage print drove Henry Hub independent of the conflict."),
            AssetLink("WEAT", COMMODITY, +1, "hours", "moderate",
                      "Black-Sea grain disruption bids wheat (the 2022 spike is the case).",
                      "USDA crop reports / global harvest news moved wheat, not the conflict."),
            AssetLink("ITA", EQUITY_ETF, +1, "days", "moderate",
                      "Defense primes rerate on a higher-conflict European regime.",
                      "Budget/appropriations news, not the specific conflict probability."),
            AssetLink("VGK", EQUITY_ETF, -1, "hours", "moderate",
                      "European equities carry the energy-shock + proximity risk; they sell on escalation.",
                      "An ECB move or global risk-off, not the conflict leg."),
            AssetLink("FXE", FX, -1, "hours", "weak",
                      "The euro weakens on a European energy/geopolitical shock (terms-of-trade hit).",
                      "A rate-differential (ECB vs Fed) move dominated the cross."),
        ),
    ),
    EventType(
        key="govt_shutdown_debt_ceiling",
        label="US government shutdown / debt-ceiling",
        rank=5,
        pm_leads=True,
        edge_note=(
            "Episodic but very clean NEAR the deadline: a binary fiscal cliff with a known date is exactly what "
            "Polymarket prices, and the safe-haven / front-bill reaction is well documented (2011, 2023). Dead "
            "between episodes."
        ),
        discovery_keywords=(
            "shutdown", "debt ceiling", "default", "government funding", "congress", "appropriations",
        ),
        gamma_tags=("Politics", "Economy", "US"),
        risk_up_keywords=("shutdown", "default", "fail", "breach", "no deal"),
        risk_down_keywords=("avert", "deal", "raise", "pass", "fund", "resolve"),
        links=(
            AssetLink("GLD", COMMODITY, +1, "hours", "moderate",
                      "Gold catches the fiscal-uncertainty safe-haven bid (2011 debt-ceiling case).",
                      "A Fed/real-rate move drove gold independent of the fiscal standoff."),
            AssetLink("SPY", EQUITY_ETF, -1, "hours", "moderate",
                      "Equities de-rate into a fiscal cliff and on a downgrade (2011 −17% drawdown).",
                      "Earnings/macro data, not the shutdown probability."),
            AssetLink("VIXY", VOLATILITY, +1, "hours", "moderate",
                      "Volatility bids into a binary fiscal deadline (hedging demand).",
                      "A separate risk event drove the vol bid (earnings, geopolitics)."),
            AssetLink("BIL", RATES, -1, "days", "weak",
                      "T-bills maturing across the x-date cheapen (default-timing premium) — a subtle, slow leg.",
                      "General front-end rate moves, not the x-date premium."),
        ),
    ),
    EventType(
        key="us_recession_macro",
        label="US recession / macro-regime",
        rank=6,
        pm_leads=False,
        edge_note=(
            "The mechanism is textbook but the edge is weakest: 'recession by 2026' is SLOW-moving and the broad "
            "market continuously prices the same probability, so the PM rarely leads. Useful as a regime CONTEXT "
            "overlay (risk-on/off) rather than a standalone catalyst trade."
        ),
        discovery_keywords=("recession", "gdp", "unemployment", "soft landing", "hard landing", "jobs report"),
        gamma_tags=("Economy", "Finance"),
        risk_up_keywords=("recession", "contract", "rise", "above", "hard landing"),  # YES = recession likelier
        risk_down_keywords=("soft landing", "avoid", "no recession", "growth"),
        links=(
            AssetLink("HYG", EQUITY_ETF, -1, "days", "moderate",
                      "High-yield credit spreads widen as recession odds rise (default risk repriced).",
                      "A rate move (duration) drove HYG, not the credit/recession leg."),
            AssetLink("TLT", EQUITY_ETF, +1, "days", "moderate",
                      "Long Treasuries rally on recession odds (flight-to-quality + cut expectations).",
                      "A supply/inflation surprise moved yields the other way."),
            AssetLink("CPER", COMMODITY, -1, "days", "moderate",
                      "Dr. Copper falls as global growth expectations fade.",
                      "A China-specific stimulus/supply story drove copper independent of US recession."),
            AssetLink("SPY", EQUITY_ETF, -1, "days", "weak",
                      "Equities de-rate on rising recession odds — but the link is slow and over-determined.",
                      "Liquidity/Fed-path moves dominate the recession leg most days."),
        ),
    ),
    EventType(
        key="us_election_policy",
        label="US election / policy-regime change",
        rank=7,
        pm_leads=True,
        edge_note=(
            "Polymarket IS the canonical election signal (deep, well-calibrated), but the asset effect is a SLOW "
            "sector rotation, not a fast catalyst, and the big repricings cluster on debate/result nights. Trade "
            "the sharp odds jumps (a debate, a candidate event), not the daily drift."
        ),
        discovery_keywords=(
            "election", "president", "trump", "harris", "senate", "house", "nominee", "tariff", "policy",
        ),
        gamma_tags=("Politics", "Elections", "US"),
        # polarity here is candidate-specific, not risk-up/down; left mostly neutral (default +1), template
        # leans on per-link mechanism. Tariff/energy/defense keywords flag the rotation direction.
        risk_up_keywords=("tariff", "deregulat", "drill", "ban"),
        risk_down_keywords=("green", "climate", "regulate"),
        links=(
            AssetLink("ITA", EQUITY_ETF, +1, "days", "weak",
                      "Defense rerates on a higher-spending / hawkish policy regime.",
                      "Budget cycle / global conflict, not the election odds."),
            AssetLink("XLE", EQUITY_ETF, +1, "days", "weak",
                      "Energy rerates on a drill-friendly / deregulatory policy regime.",
                      "The oil price itself drove XLE, not the policy regime."),
            AssetLink("KRE", EQUITY_ETF, +1, "days", "weak",
                      "Regional banks rerate on a deregulatory regime (lighter capital rules).",
                      "Rate-path / credit news drove banks, not the policy regime."),
            AssetLink("BTCUSDT", CRYPTO, +1, "days", "weak",
                      "Crypto rerates on a friendlier-regulation policy regime expectation.",
                      "A macro or crypto-idiosyncratic move dominated the policy leg."),
        ),
    ),
)


# ── pure helpers the monitor + template consume ───────────────────────────────────────────────────────────────

def event_type_by_key(key: str) -> EventType | None:
    """The watchlist EventType with this key, or None."""
    for et in DEFAULT_WATCHLIST:
        if et.key == key:
            return et
    return None


def watchlist_ranked() -> list[EventType]:
    """The watchlist sorted by Pareto rank ascending (rank 1 = highest ROI first)."""
    return sorted(DEFAULT_WATCHLIST, key=lambda et: et.rank)


def match_event_type(question: str) -> EventType | None:
    """The FIRST (lowest-rank = highest-ROI) watchlist event-type whose discovery keywords hit this market
    question, or None. Lowercased substring match — deliberately simple + deterministic (the LLM lane adds nuance
    downstream; this is the cheap pre-filter that decides whether a market is even on the watchlist)."""
    q = (question or "").lower()
    for et in watchlist_ranked():
        if any(kw in q for kw in et.discovery_keywords):
            return et
    return None


def infer_polarity(event_type: EventType, question: str) -> int:
    """Does this specific market's YES outcome mean the event-type's RISK is RISING (+1) or FALLING (−1)?

    'Strait of Hormuz CLOSES' → +1 (risk up); 'Strait of Hormuz REOPENS' → −1 (risk down). Reads the question for
    the event-type's risk_up / risk_down keywords. Default +1 (the affirmative framing); if BOTH families hit, the
    one that appears FIRST in the question wins (the head verb usually carries the polarity)."""
    q = (question or "").lower()
    up_at = min((q.find(kw) for kw in event_type.risk_up_keywords if kw in q), default=-1)
    down_at = min((q.find(kw) for kw in event_type.risk_down_keywords if kw in q), default=-1)
    if down_at == -1:
        return +1
    if up_at == -1:
        return -1
    return +1 if up_at <= down_at else -1


def all_gamma_tags() -> list[str]:
    """The de-duplicated union of every watchlist event-type's Gamma tags — the discovery surface to scan."""
    seen: dict[str, None] = {}
    for et in DEFAULT_WATCHLIST:
        for tag in et.gamma_tags:
            seen.setdefault(tag, None)
    return list(seen)


__all__ = [
    "COMMODITY",
    "CRYPTO",
    "DEFAULT_WATCHLIST",
    "EQUITY_ETF",
    "FX",
    "RATES",
    "VOLATILITY",
    "AssetLink",
    "EventType",
    "all_gamma_tags",
    "event_type_by_key",
    "infer_polarity",
    "match_event_type",
    "watchlist_ranked",
]
