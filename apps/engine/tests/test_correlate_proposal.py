# Correlation-conviction proposal + gate tests. Pure, offline. Proves the side rule (sign × polarity ×
# link.direction), the transparent confidence, the mandatory named disconfirmer, the small-size + max-loss
# guardrails, and — the lane's defining safety — the HUMAN-ARMED interlock: it never auto-fires.

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from cosmu.correlate.correlation_map import event_type_by_key, infer_polarity
from cosmu.correlate.dates import ProbMove, normalize_resolution
from cosmu.correlate.gate import (
    CorrelationCaps,
    CorrelationConvictionGate,
    CorrelationState,
)
from cosmu.correlate.monitor import EventMove, EventObservation
from cosmu.correlate.proposal import (
    CorrelationProposal,
    build_correlation_proposal,
    proposals_for_move,
)
from cosmu.snipe import ExecutionMode

_NOW = datetime(2026, 6, 29, tzinfo=UTC)
_FUTURE = datetime(2026, 12, 31, tzinfo=UTC)


def _event_move(*, polarity: int, delta: float, prob: float, question: str, event_type: str) -> EventMove:
    obs = EventObservation(
        event_type=event_type, condition_id="0xhormuz", market_id="1", question=question,
        yes_prob=prob, polarity=polarity, ts=_NOW, available_at=_NOW,
    )
    mv = ProbMove(ts=_NOW, prob=prob, prev_ts=_NOW, prev_prob=prob - delta, delta=delta)
    return EventMove(observation=obs, move=mv)


# ── the side rule ────────────────────────────────────────────────────────────────────────────────────────────

def test_side_rule_close_then_buy_oil() -> None:
    # "Hormuz CLOSES" (polarity +1) + odds RISING (+0.15) + oil link (+1) → BUY oil.
    em = _event_move(polarity=+1, delta=+0.15, prob=0.45,
                     question="Will the Strait of Hormuz close before August 2026?",
                     event_type="middle_east_oil")
    uso = event_type_by_key("middle_east_oil").links[0]
    assert uso.asset == "USO"
    p = build_correlation_proposal(em, uso, as_of=_NOW)
    assert p is not None and p.side == "buy" and p.asset == "USO"


def test_side_rule_reopen_then_sell_oil() -> None:
    # "Hormuz REOPENS" (polarity −1) + odds RISING (+0.15) + oil link (+1) → de-escalation → SELL oil.
    em = _event_move(polarity=-1, delta=+0.15, prob=0.45,
                     question="Will the Strait of Hormuz reopen before July 1?",
                     event_type="middle_east_oil")
    uso = event_type_by_key("middle_east_oil").links[0]
    p = build_correlation_proposal(em, uso, as_of=_NOW)
    assert p is not None and p.side == "sell"


def test_side_rule_negative_link_flips() -> None:
    # JETS (airlines, direction −1) under a risk-rising move → SELL JETS.
    em = _event_move(polarity=+1, delta=+0.15, prob=0.45,
                     question="Will the Strait of Hormuz close before August 2026?",
                     event_type="middle_east_oil")
    jets = next(link for link in event_type_by_key("middle_east_oil").links if link.asset == "JETS")
    p = build_correlation_proposal(em, jets, as_of=_NOW)
    assert p is not None and p.side == "sell"


def test_directionless_move_yields_no_proposal() -> None:
    em = _event_move(polarity=+1, delta=0.0, prob=0.45,
                     question="Will the Strait of Hormuz close before August 2026?",
                     event_type="middle_east_oil")
    uso = event_type_by_key("middle_east_oil").links[0]
    assert build_correlation_proposal(em, uso, as_of=_NOW) is None


# ── guardrails baked into the proposal ───────────────────────────────────────────────────────────────────────

def test_builder_sets_small_size_max_loss_and_named_disconfirmer() -> None:
    caps = CorrelationCaps(per_trade_usd=Decimal("25"), max_loss_pct=Decimal("0.50"))
    em = _event_move(polarity=+1, delta=+0.15, prob=0.45,
                     question="Will the Strait of Hormuz close before August 2026?",
                     event_type="middle_east_oil")
    uso = event_type_by_key("middle_east_oil").links[0]
    p = build_correlation_proposal(em, uso, caps=caps, as_of=_NOW)
    assert p is not None
    assert p.size_usd == Decimal("25")               # small by design
    assert p.max_loss_usd == Decimal("12.50")        # 0.50 × stake
    assert 0.0 < float(p.confidence) <= 0.95         # transparent, never certain
    # the disconfirmer NAMES the confound + carries the universal "moved before the PM / scheduled print" check.
    assert uso.confound in p.disconfirmer
    assert "before the PM" in p.disconfirmer.lower() or "before the pm" in p.disconfirmer.lower()
    assert len(p.disconfirmer) >= 20


def test_confidence_reflects_strength_and_lead() -> None:
    # A weak, non-lead link earns LESS confidence than a strong, leading one off the same move.
    strong_lead = _event_move(polarity=+1, delta=+0.20, prob=0.50,
                              question="Will the Strait of Hormuz close before August 2026?",
                              event_type="middle_east_oil")  # pm_leads=True
    uso = event_type_by_key("middle_east_oil").links[0]              # strong
    spy = next(link for link in event_type_by_key("middle_east_oil").links if link.asset == "SPY")  # weak
    p_strong = build_correlation_proposal(strong_lead, uso, as_of=_NOW)
    p_weak = build_correlation_proposal(strong_lead, spy, as_of=_NOW)
    assert p_strong.confidence > p_weak.confidence


def test_proposals_for_move_one_per_link_sorted() -> None:
    em = _event_move(polarity=+1, delta=+0.15, prob=0.45,
                     question="Will the Strait of Hormuz close before August 2026?",
                     event_type="middle_east_oil")
    props = proposals_for_move(em, as_of=_NOW)
    assert len(props) == len(event_type_by_key("middle_east_oil").links)
    confidences = [float(p.confidence) for p in props]
    assert confidences == sorted(confidences, reverse=True)  # strongest first
    assert all(p.side in ("buy", "sell") for p in props)


def test_resolution_horizon_feeds_proposal() -> None:
    res = normalize_resolution("close before August 2026", as_of=_NOW)
    em = _event_move(polarity=+1, delta=+0.15, prob=0.45,
                     question="Will the Strait of Hormuz close before August 2026?",
                     event_type="middle_east_oil")
    uso = event_type_by_key("middle_east_oil").links[0]
    p = build_correlation_proposal(em, uso, resolution=res, as_of=_NOW)
    assert p.horizon_days is not None and p.horizon_days > 0
    # expiry never runs past the PM resolution deadline.
    assert p.expiry <= res.deadline


# ── the deterministic gate ───────────────────────────────────────────────────────────────────────────────────

def _prop(**over) -> CorrelationProposal:
    base = dict(
        event_type="middle_east_oil", condition_id="0xhormuz", market_id="1",
        market_question="Will the Strait of Hormuz close before August 2026?",
        pm_prob=Decimal("0.45"), pm_prob_prev=Decimal("0.30"), pm_delta=Decimal("0.15"), polarity=1,
        asset="USO", asset_class="commodity", link_direction=1, lag="minutes", side="buy",
        size_usd=Decimal("25"), max_loss_usd=Decimal("12.50"), confidence=Decimal("0.64"),
        horizon_days=33.0,
        rationale="oil supply-risk up → buy USO",
        disconfirmer="Was the USO move caused by THIS event, or a weekly EIA inventory print? Skip if priced in.",
        expiry=_FUTURE,
    )
    base.update(over)
    return CorrelationProposal(**base)


def _state(**over) -> CorrelationState:
    base = dict(now=_NOW)
    base.update(over)
    return CorrelationState(**base)


def test_clean_proposal_passes_propose_only_surfaces_nothing() -> None:
    d = CorrelationConvictionGate().evaluate(_prop(), CorrelationCaps(), _state())
    assert d.ok and d.reasons == ["pass"]
    assert d.would_execute is False and d.requires_human is False


def test_human_confirm_requires_human() -> None:
    caps = CorrelationCaps(mode=ExecutionMode.HUMAN_CONFIRM)
    d = CorrelationConvictionGate().evaluate(_prop(), caps, _state())
    assert d.ok and d.requires_human is True and d.would_execute is False


def test_human_armed_interlock_blocks_autonomous_auto_fire() -> None:
    # THE defining safety: even in BOUNDED_AUTONOMOUS, the default human-armed interlock forbids auto-fire.
    caps = CorrelationCaps(mode=ExecutionMode.BOUNDED_AUTONOMOUS)  # human_armed_required defaults True
    d = CorrelationConvictionGate().evaluate(_prop(), caps, _state())
    assert d.ok and d.requires_human is True and d.would_execute is False
    # Only an operator who EXPLICITLY drops the interlock can auto-fire.
    unsafe = CorrelationCaps(mode=ExecutionMode.BOUNDED_AUTONOMOUS, human_armed_required=False)
    d2 = CorrelationConvictionGate().evaluate(_prop(), unsafe, _state())
    assert d2.would_execute is True


def test_kill_switch_blocks_everything() -> None:
    caps = CorrelationCaps(mode=ExecutionMode.BOUNDED_AUTONOMOUS, human_armed_required=False, kill_switch=True)
    d = CorrelationConvictionGate().evaluate(_prop(), caps, _state())
    assert d.ok is False and "kill_switch_on" in d.reasons and d.would_execute is False


def test_size_over_cap_rejected() -> None:
    d = CorrelationConvictionGate().evaluate(_prop(size_usd=Decimal("30")), CorrelationCaps(), _state())
    assert d.ok is False and any("size_over_per_trade_cap" in r for r in d.reasons)


def test_move_below_min_rejected() -> None:
    d = CorrelationConvictionGate().evaluate(_prop(pm_delta=Decimal("0.02")), CorrelationCaps(), _state())
    assert d.ok is False and any("move_below_min" in r for r in d.reasons)


def test_confidence_below_min_rejected() -> None:
    d = CorrelationConvictionGate().evaluate(_prop(confidence=Decimal("0.50")), CorrelationCaps(), _state())
    assert d.ok is False and any("confidence_below_min" in r for r in d.reasons)


def test_max_loss_over_cap_rejected() -> None:
    # 20 > 0.50 × 25 = 12.5 → over the stop cap (but ≤ the 25 stake, so NOT over-stake).
    d = CorrelationConvictionGate().evaluate(_prop(max_loss_usd=Decimal("20")), CorrelationCaps(), _state())
    assert d.ok is False and any("max_loss_over_cap" in r for r in d.reasons)


def test_max_loss_over_stake_rejected() -> None:
    d = CorrelationConvictionGate().evaluate(
        _prop(size_usd=Decimal("10"), max_loss_usd=Decimal("15")), CorrelationCaps(), _state(),
    )
    assert d.ok is False and any("max_loss_over_stake" in r for r in d.reasons)


def test_thin_disconfirmer_rejected() -> None:
    d = CorrelationConvictionGate().evaluate(_prop(disconfirmer="n/a"), CorrelationCaps(), _state())
    assert d.ok is False and any("disconfirmer_too_thin" in r for r in d.reasons)


def test_over_daily_and_exposure_caps_rejected() -> None:
    g = CorrelationConvictionGate()
    daily = g.evaluate(_prop(), CorrelationCaps(daily_usd=Decimal("100")), _state(staked_today_usd=Decimal("90")))
    assert daily.ok is False and any("over_daily_cap" in r for r in daily.reasons)
    expo = g.evaluate(
        _prop(), CorrelationCaps(total_exposure_usd=Decimal("250")), _state(open_exposure_usd=Decimal("240")),
    )
    assert expo.ok is False and any("over_total_exposure" in r for r in expo.reasons)


def test_expired_proposal_rejected() -> None:
    d = CorrelationConvictionGate().evaluate(
        _prop(expiry=datetime(2026, 1, 1, tzinfo=UTC)), CorrelationCaps(), _state(),
    )
    assert d.ok is False and "proposal_expired" in d.reasons


def test_gate_is_deterministic_and_never_upsizes() -> None:
    p, caps = _prop(), CorrelationCaps(daily_usd=Decimal("100"))
    gate = CorrelationConvictionGate()
    a = gate.evaluate(p, caps, _state(staked_today_usd=Decimal("0")))
    b = gate.evaluate(p, caps, _state(staked_today_usd=Decimal("0")))
    assert (a.ok, a.reasons, a.would_execute) == (b.ok, b.reasons, b.would_execute)
    assert a.requires_human == b.requires_human
    # more already staked → STRICTER, never a bigger "recovery" trade.
    after = gate.evaluate(_prop(size_usd=Decimal("20")), caps, _state(staked_today_usd=Decimal("95")))
    assert after.ok is False


# ── end-to-end: a monitor move → proposals → gate ────────────────────────────────────────────────────────────

def test_end_to_end_move_to_gated_proposal() -> None:
    em = _event_move(polarity=+1, delta=+0.15, prob=0.45,
                     question="Will the Strait of Hormuz close before August 2026?",
                     event_type="middle_east_oil")
    props = proposals_for_move(em, as_of=_NOW)
    assert props, "a 15pp Hormuz-close move should produce candidate trades"
    gate, caps, state = CorrelationConvictionGate(), CorrelationCaps(), _state()
    # The top (strongest-link) proposal clears the deterministic envelope but executes nothing (propose-only).
    top = gate.evaluate(props[0], caps, state)
    assert top.ok and top.would_execute is False and top.requires_human is False


def test_infer_polarity_is_consistent_with_map() -> None:
    et = event_type_by_key("middle_east_oil")
    assert infer_polarity(et, "Will the Strait of Hormuz close before August?") == 1
    assert infer_polarity(et, "Will the Strait of Hormuz reopen before August?") == -1
