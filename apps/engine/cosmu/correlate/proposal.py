# intent: the typed CORRELATION-CONVICTION proposal — the artifact the LLM/Conviction lane emits when a watched
# Polymarket event MOVES: a propose-only, human-armed trade on a CORRELATED ASSET (oil, energy equities, crypto,
# gold…), NOT on the prediction market itself. It carries the full economic case (which PM market moved, by how
# much, which asset link, the derived side, the horizon) + a MANDATORY named DISCONFIRMER (was the asset move
# caused by THIS event, or by the named confound?). It executes nothing — the deterministic CorrelationConviction
# Gate (gate.py) disposes within hard caps. This lane is NOT the quant Gate: a cross-asset PM→asset transfer can't
# be backtested cleanly (the theory doc shows the edge is mostly co-incidence + confound), so it is routed through
# CONVICTION (credibility + a human arm + a disconfirmer), never funded by the statistical gate.
#
# THE SIDE RULE (the one subtlety, see correlation_map.py): a market's YES outcome can mean the event-type's risk
# RISING ("Hormuz closes", polarity +1) or FALLING ("Hormuz reopens", polarity −1). So:
#     asset_response = sign(pm_delta) × polarity × link.direction
#     side = "buy" if asset_response > 0 else "sell"   (asset_response == 0 → no trade)

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from cosmu.correlate.correlation_map import AssetLink, event_type_by_key
from cosmu.correlate.dates import NormalizedResolution, ProbMove
from cosmu.correlate.gate import CorrelationCaps
from cosmu.correlate.monitor import EventMove


def _now() -> datetime:
    return datetime.now(tz=UTC)


class CorrelationProposal(BaseModel):
    """One proposed trade on a CORRELATED ASSET, driven by a Polymarket event move. Every money-touching field is
    bounded here so a malformed/hallucinated proposal can't be constructed out of range. The agent reasons over
    the monitor's moves + the correlation map and emits THIS; the deterministic gate decides whether a dollar
    moves (and even then only with a human arm)."""

    proposal_id: str = Field(default_factory=lambda: uuid4().hex)
    lane: Literal["correlation_conviction"] = "correlation_conviction"  # NOT the quant gate; the conviction lane

    # The Polymarket event that triggered this (the "attention signal").
    event_type: str                                  # watchlist key, e.g. "middle_east_oil"
    condition_id: str                                # the PM conditionId that moved
    market_id: str
    market_question: str
    pm_prob: Decimal = Field(ge=0, le=1)             # the current YES probability
    pm_prob_prev: Decimal = Field(ge=0, le=1)        # the previous hoarded YES probability
    pm_delta: Decimal                                # signed move = pm_prob − pm_prob_prev
    polarity: Literal[-1, 1]                         # YES = risk rising (+1) or falling (−1)

    # The correlated-asset trade.
    asset: str                                       # the tradable symbol, e.g. "USO", "BTCUSDT"
    asset_class: str
    link_direction: Literal[-1, 1]                   # asset response when the event-type's RISK rises
    lag: str                                         # expected reaction speed (immediate/minutes/hours/days)
    side: Literal["buy", "sell"]
    size_usd: Decimal = Field(gt=0)                  # notional to stake (small by design)
    max_loss_usd: Decimal = Field(gt=0)              # the hard stop — max loss the operator accepts on this trade
    confidence: Decimal = Field(ge=0, le=1)          # the proposal's confidence in its own case
    horizon_days: float | None = None                # days-to-resolution of the PM event (sizes the hold)

    rationale: str = Field(min_length=1)             # the economic WHY (required — no naked conviction)
    disconfirmer: str = Field(min_length=1)          # what would prove this WRONG — the named confound (required)
    expiry: datetime                                 # do not act after this instant (the catalyst window closes)
    source: str = "agent"                            # agent run id, or "human"
    created_at: datetime = Field(default_factory=_now)

    def is_expired(self, now: datetime | None = None) -> bool:
        return (now or _now()) > self.expiry


# Expected catalyst window per reaction lag — how long the asset response plausibly plays out (the default expiry
# horizon, capped by the PM resolution deadline when known). A faster link has a shorter actionable window.
_LAG_WINDOW_DAYS = {"immediate": 1.0, "minutes": 1.0, "hours": 2.0, "days": 5.0}

# Confidence model (transparent + deterministic): base from the move magnitude, scaled by the link's qualitative
# strength and whether the PM tends to LEAD the asset (a lead is a real signal; a lag is mere confirmation).
_STRENGTH_MULT = {"strong": 1.0, "moderate": 0.85, "weak": 0.70}
_NOT_LEAD_MULT = 0.80   # an event-type whose PM does NOT lead the asset is confirmation, not signal → down-weight
_CONF_CAP = 0.95        # never claim certainty


def _move_base_confidence(abs_delta: float) -> float:
    """Map a |probability move| to a base confidence in [0.5, 0.85]. A 5pp move is a weak catalyst (0.50); a 30pp+
    move is a strong one (0.85). Linear in between, deliberately modest — the conviction lane is skeptical."""
    lo_move, hi_move, lo_conf, hi_conf = 0.05, 0.30, 0.50, 0.85
    if abs_delta <= lo_move:
        return lo_conf
    if abs_delta >= hi_move:
        return hi_conf
    frac = (abs_delta - lo_move) / (hi_move - lo_move)
    return lo_conf + frac * (hi_conf - lo_conf)


def _proposal_confidence(move: ProbMove, link: AssetLink, *, pm_leads: bool) -> float:
    base = _move_base_confidence(move.abs_delta)
    mult = _STRENGTH_MULT.get(link.strength, 0.70) * (1.0 if pm_leads else _NOT_LEAD_MULT)
    return round(min(base * mult, _CONF_CAP), 4)


def _side(move_delta: float, polarity: int, link_direction: int) -> Literal["buy", "sell"] | None:
    """asset_response = sign(move_delta) × polarity × link_direction → 'buy' (>0) / 'sell' (<0) / None (==0)."""
    response = (1 if move_delta > 0 else -1 if move_delta < 0 else 0) * polarity * link_direction
    if response > 0:
        return "buy"
    if response < 0:
        return "sell"
    return None


def _expiry(as_of: datetime, lag: str, resolution: NormalizedResolution | None) -> datetime:
    """The catalyst window close: as_of + the lag's window, but never past the PM resolution deadline (once the
    event resolves, the move has played out — there is nothing left to trade)."""
    window = timedelta(days=_LAG_WINDOW_DAYS.get(lag, 2.0))
    exp = as_of + window
    if resolution is not None and resolution.deadline is not None and resolution.deadline > as_of:
        exp = min(exp, resolution.deadline)
    return exp


def build_correlation_proposal(
    event_move: EventMove,
    link: AssetLink,
    *,
    caps: CorrelationCaps | None = None,
    resolution: NormalizedResolution | None = None,
    as_of: datetime | None = None,
    source: str = "agent",
) -> CorrelationProposal | None:
    """Compose a typed CorrelationProposal from a monitor EventMove + one correlated-asset link. Returns None when
    the move is directionless (delta == 0 → no side). Size = caps.per_trade_usd (small by design); the max-loss
    stop = caps.max_loss_pct × size. The disconfirmer NAMES the link's confound + the universal "did the asset
    move BEFORE the PM / on a scheduled print" check — the question the human arm must answer before any capital."""
    caps = caps or CorrelationCaps()
    now = (as_of or _now()).astimezone(UTC)
    obs, move = event_move.observation, event_move.move

    side = _side(move.delta, obs.polarity, link.direction)
    if side is None:
        return None

    et = event_type_by_key(obs.event_type)
    pm_leads = bool(et.pm_leads) if et is not None else False
    confidence = _proposal_confidence(move, link, pm_leads=pm_leads)

    size = caps.per_trade_usd
    max_loss = (caps.max_loss_pct * size).quantize(Decimal("0.01"))
    horizon = resolution.days_to_event if resolution is not None else None

    lead_word = "LEADS" if pm_leads else "confirms (no documented lead — treat as context)"
    rationale = (
        f"Polymarket [{obs.event_type}] '{obs.question}' YES "
        f"{move.prev_prob:.2f}→{move.prob:.2f} ({move.delta:+.2f}). Polarity {obs.polarity:+d} "
        f"(YES = risk {'rising' if obs.polarity > 0 else 'falling'}). Mechanism: {link.mechanism} "
        f"⇒ {side.upper()} {link.asset} (lag {link.lag}, linkage {link.strength}). PM {lead_word}."
    )
    disconfirmer = (
        f"Was the {link.asset} move caused by THIS event, or by the confound: {link.confound}? "
        f"SKIP/close if (a) {link.asset} already moved BEFORE the PM did (you're chasing a priced-in move), "
        f"(b) a scheduled print/calendar event drove it, or (c) the PM market is thin/illiquid (its 'move' is a "
        f"microstructure artifact — PMs underreact ~0.64-for-1 and worse when illiquid)."
    )

    return CorrelationProposal(
        event_type=obs.event_type,
        condition_id=obs.condition_id,
        market_id=obs.market_id,
        market_question=obs.question,
        pm_prob=Decimal(str(round(move.prob, 6))),
        pm_prob_prev=Decimal(str(round(move.prev_prob, 6))),
        pm_delta=Decimal(str(round(move.delta, 6))),
        polarity=obs.polarity,  # type: ignore[arg-type]  (infer_polarity returns ±1)
        asset=link.asset,
        asset_class=link.asset_class,
        link_direction=link.direction,  # type: ignore[arg-type]  (always ±1 in the map)
        lag=link.lag,
        side=side,
        size_usd=size,
        max_loss_usd=max_loss,
        confidence=Decimal(str(confidence)),
        horizon_days=horizon,
        rationale=rationale,
        disconfirmer=disconfirmer,
        expiry=_expiry(now, link.lag, resolution),
        source=source,
    )


def proposals_for_move(
    event_move: EventMove,
    *,
    caps: CorrelationCaps | None = None,
    resolution: NormalizedResolution | None = None,
    as_of: datetime | None = None,
    source: str = "agent",
) -> list[CorrelationProposal]:
    """One proposal per correlated-asset link of the moved event-type — the full candidate set for an event move,
    confidence-ranked (strongest first). The gate filters; the human arm chooses. Directionless links are dropped."""
    et = event_type_by_key(event_move.observation.event_type)
    if et is None:
        return []
    out: list[CorrelationProposal] = []
    for link in et.links:
        p = build_correlation_proposal(
            event_move, link, caps=caps, resolution=resolution, as_of=as_of, source=source,
        )
        if p is not None:
            out.append(p)
    out.sort(key=lambda p: p.confidence, reverse=True)
    return out


__all__ = [
    "CorrelationProposal",
    "build_correlation_proposal",
    "proposals_for_move",
]
