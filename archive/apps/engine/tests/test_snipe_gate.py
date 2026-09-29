# The snipe lane's deterministic money envelope — offline, pure, no LLM, no network. This is the safety-critical
# core: it proves a proposal can ONLY move money inside the operator's caps, the autonomy dial behaves, the
# kill-switch is absolute, and there is NO revenge/up-sizing path. If this suite is green, a hallucinated
# proposal is bounded by construction.

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from cosmu.snipe import (
    ConvictionCaps,
    ConvictionGate,
    ConvictionProposal,
    ExecutionMode,
    GateState,
)

_NOW = datetime(2026, 6, 15, tzinfo=UTC)
_FUTURE = datetime(2026, 12, 31, tzinfo=UTC)


def _proposal(**over) -> ConvictionProposal:
    base = dict(
        market_id="0xmarket",
        market_question="Will X win?",
        outcome="Yes",
        token_id="0xtoken",
        side="buy",
        size_usd=Decimal("10"),
        limit_price=Decimal("0.40"),
        fair_prob=Decimal("0.55"),  # 15-pt edge vs 40c
        confidence=Decimal("0.80"),
        rationale="model fair 0.55 vs 0.40 price",
        disconfirmer="resolves No / new poll closes the gap",
        expiry=_FUTURE,
    )
    base.update(over)
    return ConvictionProposal(**base)


def _state(**over) -> GateState:
    base = dict(staked_today_usd=Decimal("0"), open_exposure_usd=Decimal("0"), open_bets=0, now=_NOW)
    base.update(over)
    return GateState(**base)


# ── the autonomy dial ───────────────────────────────────────────────────────────────────────────────────────

def test_clean_proposal_passes_but_propose_only_never_executes() -> None:
    d = ConvictionGate().evaluate(_proposal(), ConvictionCaps(), _state())  # default mode = PROPOSE_ONLY
    assert d.ok and d.reasons == ["pass"]
    assert d.would_execute is False and d.requires_human is False  # surfaced, but moves nothing


def test_human_confirm_passes_and_asks_but_does_not_auto_fire() -> None:
    caps = ConvictionCaps(mode=ExecutionMode.HUMAN_CONFIRM)
    d = ConvictionGate().evaluate(_proposal(), caps, _state())
    assert d.ok and d.requires_human is True and d.would_execute is False


def test_bounded_autonomous_auto_fires_a_passing_proposal() -> None:
    caps = ConvictionCaps(mode=ExecutionMode.BOUNDED_AUTONOMOUS)
    d = ConvictionGate().evaluate(_proposal(), caps, _state())
    assert d.ok and d.would_execute is True and d.requires_human is False


def test_kill_switch_blocks_even_in_autonomous_mode() -> None:
    caps = ConvictionCaps(mode=ExecutionMode.BOUNDED_AUTONOMOUS, kill_switch=True)
    d = ConvictionGate().evaluate(_proposal(), caps, _state())
    assert d.ok is False and "kill_switch_on" in d.reasons and d.would_execute is False


# ── the money caps (each alone blocks) ──────────────────────────────────────────────────────────────────────

def test_size_over_per_bet_cap_is_rejected() -> None:
    d = ConvictionGate().evaluate(_proposal(size_usd=Decimal("26")), ConvictionCaps(per_bet_usd=Decimal("25")), _state())
    assert d.ok is False and any("size_over_per_bet_cap" in r for r in d.reasons)


def test_over_daily_cap_is_rejected() -> None:
    caps = ConvictionCaps(daily_usd=Decimal("100"))
    d = ConvictionGate().evaluate(_proposal(size_usd=Decimal("20")), caps, _state(staked_today_usd=Decimal("90")))
    assert d.ok is False and any("over_daily_cap" in r for r in d.reasons)


def test_over_total_exposure_is_rejected() -> None:
    caps = ConvictionCaps(total_exposure_usd=Decimal("250"))
    d = ConvictionGate().evaluate(_proposal(size_usd=Decimal("20")), caps, _state(open_exposure_usd=Decimal("240")))
    assert d.ok is False and any("over_total_exposure" in r for r in d.reasons)


def test_too_many_open_bets_is_rejected() -> None:
    d = ConvictionGate().evaluate(_proposal(), ConvictionCaps(max_open_bets=10), _state(open_bets=10))
    assert d.ok is False and any("too_many_open_bets" in r for r in d.reasons)


def test_low_confidence_is_rejected() -> None:
    d = ConvictionGate().evaluate(_proposal(confidence=Decimal("0.50")), ConvictionCaps(min_confidence=Decimal("0.60")), _state())
    assert d.ok is False and any("confidence_below_min" in r for r in d.reasons)


def test_price_out_of_band_is_rejected_both_ends() -> None:
    g, caps = ConvictionGate(), ConvictionCaps(min_price=Decimal("0.05"), max_price=Decimal("0.95"))
    hi = g.evaluate(_proposal(limit_price=Decimal("0.97"), fair_prob=Decimal("0.99")), caps, _state())
    lo = g.evaluate(_proposal(limit_price=Decimal("0.03"), fair_prob=Decimal("0.20")), caps, _state())
    assert hi.ok is False and any("price_out_of_band" in r for r in hi.reasons)
    assert lo.ok is False and any("price_out_of_band" in r for r in lo.reasons)


def test_edge_below_min_is_rejected() -> None:
    # fair 0.42 vs price 0.40 → 2-pt edge, below the 5-pt floor.
    d = ConvictionGate().evaluate(_proposal(fair_prob=Decimal("0.42")), ConvictionCaps(min_edge_prob=Decimal("0.05")), _state())
    assert d.ok is False and any("edge_below_min" in r for r in d.reasons)


def test_book_fraction_caps_size_and_is_skipped_when_depth_unknown() -> None:
    g = ConvictionGate()
    caps = ConvictionCaps(max_book_fraction=Decimal("0.10"))
    # 10 USDC vs a $50 book → 20% of depth > 10% cap → rejected.
    thin = g.evaluate(_proposal(size_usd=Decimal("10")), caps, _state(book_depth_usd=Decimal("50")))
    assert thin.ok is False and any("over_book_fraction" in r for r in thin.reasons)
    # Same bet vs a $500 book (2%) passes; and with depth unknown the check is skipped (other caps still bind).
    assert g.evaluate(_proposal(size_usd=Decimal("10")), caps, _state(book_depth_usd=Decimal("500"))).ok is True
    assert g.evaluate(_proposal(size_usd=Decimal("10")), caps, _state(book_depth_usd=None)).ok is True


def test_expired_proposal_is_rejected() -> None:
    d = ConvictionGate().evaluate(_proposal(expiry=datetime(2026, 1, 1, tzinfo=UTC)), ConvictionCaps(), _state(now=_NOW))
    assert d.ok is False and "proposal_expired" in d.reasons


# ── invariants: determinism + NO revenge/up-sizing ─────────────────────────────────────────────────────────

def test_evaluation_is_pure_and_deterministic() -> None:
    p, caps, st = _proposal(), ConvictionCaps(mode=ExecutionMode.BOUNDED_AUTONOMOUS), _state()
    a, b = ConvictionGate().evaluate(p, caps, st), ConvictionGate().evaluate(p, caps, st)
    assert (a.ok, a.would_execute, a.requires_human, a.reasons) == (b.ok, b.would_execute, b.requires_human, b.reasons)


def test_gate_never_upsizes_no_revenge_path() -> None:
    # The gate has NO loss/P&L input and returns a verdict, never a size — so it cannot grow a bet to "win it
    # back". A heavier prior loss (modeled as more staked today / more exposure) can only make it STRICTER,
    # never permit a bigger bet. Here the same proposal that passed flat is REJECTED once the day is near-cap —
    # the opposite of revenge sizing.
    caps = ConvictionCaps(daily_usd=Decimal("100"))
    flat = ConvictionGate().evaluate(_proposal(size_usd=Decimal("20")), caps, _state(staked_today_usd=Decimal("0")))
    after_losses = ConvictionGate().evaluate(_proposal(size_usd=Decimal("20")), caps, _state(staked_today_usd=Decimal("95")))
    assert flat.ok is True
    assert after_losses.ok is False  # more spent already → tighter, never a bigger "recovery" bet


def test_buy_edge_semantics() -> None:
    assert _proposal(side="buy", fair_prob=Decimal("0.55"), limit_price=Decimal("0.40")).edge_prob() == Decimal("0.15")
    assert _proposal(side="sell", fair_prob=Decimal("0.40"), limit_price=Decimal("0.55")).edge_prob() == Decimal("0.15")
