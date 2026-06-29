# The COMPOSITE AUTHORITY SCORER (cosmu/authority/scoring.py) — the heart of the feature. Pure + deterministic,
# no I/O, no LLM. These tests pin the behaviours the operator asked for:
#   * PROFIT > hit-rate: an account WRONG most of the time but HUGE on a few calls scores WELL on EV and the huge
#     calls surface as top movers; adding the big winner RAISES the composite (profit is rewarded, not buried).
#   * ECHO discard: a call tweeted AFTER the move already started is flagged is_echo and its payoff is discounted;
#     the same call made BEFORE the move is foresight (lead > 0, not discounted).
#   * TOP-3 movers: the three most profitable calls, ordered by payoff.
#   * Calibration core (Brier/BSS) still rewards a calibrated foreseer over an overconfident spammer.
#   * Honest UNTESTED (no resolved calls → None metrics, never 0) + determinism.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cosmu.authority.models import AccountCall, AuthorityScore, PricePoint, ResolvedCall
from cosmu.authority.scoring import (
    ECHO_DISCOUNT,
    EV_POSITION,
    rank_accounts,
    resolve_call,
    score_account,
    score_accounts,
)

T0 = datetime(2024, 1, 1, tzinfo=UTC)
NOW = T0 + timedelta(days=120)


def _daily(prices: list[float], *, start: datetime = T0) -> list[PricePoint]:
    return [PricePoint(ts=start + timedelta(days=i), price=float(p)) for i, p in enumerate(prices)]


def _rc(
    asset: str,
    signed_return: float,
    *,
    direction: str = "up",
    conviction: float = 0.6,
    hit: bool | None = None,
    base_rate: float = 0.3,
    is_echo: bool = False,
    lead_days: float = 2.0,
    day: int = 40,
    horizon: int = 7,
) -> ResolvedCall:
    """A hand-built ResolvedCall with a precise signed_return — lets the composite tests control payoff exactly
    without engineering a price path. signed_return is profit-positive (the move went the claimed way)."""
    hit = (signed_return > 0.01) if hit is None else hit
    raw = signed_return if direction == "up" else -signed_return
    call = AccountCall(account="acct", platform="x", asset=asset, direction=direction,  # type: ignore[arg-type]
                       ts=T0 + timedelta(days=day), conviction=conviction)
    return ResolvedCall(
        call=call, status="resolved", horizon_days=horizon, entry_price=100.0,
        exit_price=100.0 * (1.0 + raw), raw_return=raw, signed_return=signed_return,
        abs_move=abs(raw), hit=hit, base_rate=base_rate, base_abs_move=0.05,
        is_echo=is_echo, lead_days=(lead_days if hit and not is_echo else 0.0),
    )


# --------------------------------------------------------------------------- PROFIT > hit-rate


def test_wrong_majority_huge_minority_scores_on_ev_not_hit_rate():
    """The operator's headline case: an account wrong 80% of the time but HUGE on the other 20% has positive EV,
    the huge call as its top mover, and a higher composite WITH the winner than without (profit is rewarded)."""
    losers = [_rc(f"L{i}", -0.02, hit=False, base_rate=0.3) for i in range(4)]
    winner = _rc("MOON", 1.20, hit=True, base_rate=0.05)

    spike = score_account("@spike", "x", losers + [winner])
    losers_only = score_account("@spike", "x", losers)

    # Wrong majority, yet profitable.
    assert spike.n_resolved == 5
    assert spike.hit_rate == 0.2
    assert spike.ev is not None and spike.ev > 0.0          # the huge winner dominates the small losses
    assert spike.composite is not None and spike.composite > 0.0

    # Adding the big winner RAISES both EV and the composite — profit is rewarded, not buried under hit-rate.
    assert spike.ev > (losers_only.ev or 0.0)
    assert spike.composite > (losers_only.composite or 0.0)

    # The huge call surfaces as the #1 mover.
    assert spike.top_movers[0].asset == "MOON"
    assert spike.top_movers[0].signed_return == 1.20

    # One spike carrying all the gains → consistency near zero (low = concentrated, by design interesting).
    assert spike.consistency == 0.0


def test_steady_account_is_more_consistent_and_better_calibrated():
    """A balanced control: steady small wins → high hit-rate, well-calibrated (positive BSS), and HIGHER gain
    spread (consistency) than the one-spike account. The scorer values more than raw EV."""
    steady = score_account("@steady", "x", [_rc(f"S{i}", 0.04, hit=True, base_rate=0.3, conviction=0.5) for i in range(6)])
    spike = score_account("@spike", "x", [_rc(f"L{i}", -0.02, hit=False, base_rate=0.3) for i in range(4)] + [_rc("MOON", 1.2, hit=True, base_rate=0.05)])

    assert steady.hit_rate == 1.0
    assert steady.brier_skill_score is not None and steady.brier_skill_score > 0.0  # beats the base rate
    assert steady.consistency is not None and spike.consistency is not None
    assert steady.consistency > spike.consistency


# --------------------------------------------------------------------------- echo discard


def test_resolve_flags_echo_when_move_already_underway():
    """A call made AFTER the asset already ran in the claimed direction is an echo (lean timestamp+price check)."""
    # Flat 100 → ramps up BEFORE the call (the move already happened) → drifts up a touch after.
    prices = [100.0] * 36 + [110.0, 120.0, 130.0, 130.0, 130.0] + [130.0 + (10.0 * (d / 7.0)) for d in range(1, 8)] + [140.0] * 12
    series = _daily(prices)
    call = AccountCall(account="@late", platform="x", asset="ECHO", direction="up",
                       ts=T0 + timedelta(days=40), conviction=0.7)
    resolved = resolve_call(call, series, now=NOW, horizon_days=7)

    assert resolved.status == "resolved"
    assert resolved.hit is True            # it still went up after the call
    assert resolved.is_echo is True        # but the move was already underway → echo
    assert resolved.lead_days == 0.0       # an echo led by nothing


def test_resolve_flags_foresight_when_move_comes_after():
    """The SAME winning call made BEFORE the move is foresight: not an echo, positive lead time."""
    # Flat 100 through the call, then ramps up AFTER it.
    prices = [100.0] * 41 + [100.0 + (30.0 * (d / 7.0)) for d in range(1, 8)] + [130.0] * 12
    series = _daily(prices)
    call = AccountCall(account="@early", platform="x", asset="FORE", direction="up",
                       ts=T0 + timedelta(days=40), conviction=0.7)
    resolved = resolve_call(call, series, now=NOW, horizon_days=7)

    assert resolved.status == "resolved"
    assert resolved.hit is True
    assert resolved.is_echo is False
    assert resolved.lead_days > 0.0


def test_echo_payoff_is_discounted_in_the_score():
    """Two identical winning calls — one echo, one foresight — and the echo's payoff is down-weighted by
    ECHO_DISCOUNT, so the echo account's EV is strictly lower."""
    fore = score_account("@early", "x", [_rc("A", 0.50, hit=True, is_echo=False)])
    echo = score_account("@late", "x", [_rc("A", 0.50, hit=True, is_echo=True)])

    assert fore.ev is not None and echo.ev is not None
    assert echo.ev < fore.ev
    # The mover payoff reflects the discount exactly.
    assert abs(echo.top_movers[0].payoff - EV_POSITION * ECHO_DISCOUNT * 0.50) < 1e-9
    assert abs(fore.top_movers[0].payoff - EV_POSITION * 0.50) < 1e-9


# --------------------------------------------------------------------------- top-3 movers


def test_top_three_movers_are_the_three_most_profitable():
    calls = [_rc(f"A{i}", r, hit=True) for i, r in enumerate([0.1, 0.5, 0.3, 0.9, 0.2])]
    score = score_account("@m", "x", calls)
    assert len(score.top_movers) == 3
    assert [round(m.signed_return, 2) for m in score.top_movers] == [0.9, 0.5, 0.3]


# --------------------------------------------------------------------------- honest empty + determinism


def test_untested_account_has_none_metrics_never_zero():
    """An account with calls on record but NONE resolved yet (all pending) is UNTESTED: counts present, every
    derived metric None — never a fabricated 0 that would read as 'tested and unskilled'."""
    call = AccountCall(account="@pending", platform="x", asset="BTC", direction="up",
                       ts=T0 + timedelta(days=115), conviction=0.6)
    # Series ends before the horizon resolves relative to `now` → pending.
    series = _daily([100.0] * 117)
    resolved = resolve_call(call, series, now=T0 + timedelta(days=116), horizon_days=7)
    assert resolved.status == "pending"

    score = score_account("@pending", "x", [resolved], n_calls=1)
    assert score.n_calls == 1 and score.n_resolved == 0
    assert score.composite is None and score.hit_rate is None and score.ev is None
    assert score.last_call_ts == call.ts


def test_no_data_when_no_tape_or_call_precedes_tape():
    call = AccountCall(account="@x", platform="x", asset="BTC", direction="up", ts=T0 + timedelta(days=40))
    assert resolve_call(call, [], now=NOW).status == "no_data"
    late_series = _daily([100.0] * 10, start=T0 + timedelta(days=100))  # all after the call
    assert resolve_call(call, late_series, now=NOW).status == "no_data"


def test_score_accounts_is_deterministic_and_ranks_composite_desc():
    calls = [
        AccountCall(account="@a", platform="x", asset="BTC", direction="up", ts=T0 + timedelta(days=10), conviction=0.6),
        AccountCall(account="@b", platform="x", asset="BTC", direction="down", ts=T0 + timedelta(days=12), conviction=0.6),
    ]
    # BTC ramps steadily up: @a (up) is right, @b (down) is wrong.
    prices = {"BTC": _daily([100.0 + i for i in range(60)])}
    first = score_accounts(calls, prices, now=NOW)
    second = score_accounts(calls, prices, now=NOW)
    assert [s.to_row() for s in first] == [s.to_row() for s in second]  # deterministic
    # @a (the correct up-caller) outranks @b; ranking is composite DESC.
    comps = [s.composite or -1.0 for s in first]
    assert comps == sorted(comps, reverse=True)
    assert first[0].account == "@a"


def test_empty_corpus_scores_to_empty():
    assert score_accounts([], {}, now=NOW) == []


# --------------------------------------------------------------------------- multi-account RANKING (relative)


def _scored(account: str, composite: float | None) -> AuthorityScore:
    """A bare AuthorityScore with a fixed composite — lets the ranking tests control the roster exactly."""
    return AuthorityScore(account=account, platform="x", n_calls=5, n_resolved=(5 if composite is not None else 0),
                          n_echo=0, composite=composite)


def test_rank_accounts_assigns_relative_standing():
    """Authority is RELATIVE: rank (1 = best), percentile (1.0 = best, 0.0 = worst) and z vs the roster mean."""
    ranked = {s.account: s for s in rank_accounts([_scored("@a", 0.8), _scored("@b", 0.5), _scored("@c", 0.2)])}
    assert ranked["@a"].rank == 1 and ranked["@b"].rank == 2 and ranked["@c"].rank == 3
    assert ranked["@a"].percentile == 1.0 and ranked["@b"].percentile == 0.5 and ranked["@c"].percentile == 0.0
    # mean 0.5: @a above (z>0), @c below (z<0), @b at the mean (z==0).
    assert ranked["@a"].composite_z is not None and ranked["@a"].composite_z > 0
    assert ranked["@c"].composite_z is not None and ranked["@c"].composite_z < 0
    assert abs(ranked["@b"].composite_z) < 1e-9


def test_untested_account_is_unranked():
    """An UNTESTED account (None composite) carries no rank/percentile/z; a lone tested account is percentile 1.0
    with no z (a roster of one has no relative frame)."""
    ranked = {s.account: s for s in rank_accounts([_scored("@a", 0.8), _scored("@u", None)])}
    assert ranked["@u"].rank is None and ranked["@u"].percentile is None and ranked["@u"].composite_z is None
    assert ranked["@a"].rank == 1 and ranked["@a"].percentile == 1.0 and ranked["@a"].composite_z is None


def test_zero_spread_roster_has_no_z():
    """A roster with no composite spread (all equal) yields ranks + percentiles but no z (std == 0)."""
    ranked = {s.account: s for s in rank_accounts([_scored("@a", 0.5), _scored("@b", 0.5)])}
    assert ranked["@a"].composite_z is None and ranked["@b"].composite_z is None
    assert {ranked["@a"].rank, ranked["@b"].rank} == {1, 2}


def test_score_accounts_stamps_ranking_end_to_end():
    """score_accounts wires ranking in: the top account is rank 1, percentile 1.0."""
    calls = [
        AccountCall(account="@a", platform="x", asset="BTC", direction="up", ts=T0 + timedelta(days=10), conviction=0.6),
        AccountCall(account="@b", platform="x", asset="BTC", direction="down", ts=T0 + timedelta(days=12), conviction=0.6),
    ]
    prices = {"BTC": _daily([100.0 + i for i in range(60)])}  # ramps up → @a (up) right, @b (down) wrong
    ranked = score_accounts(calls, prices, now=NOW)
    assert ranked[0].account == "@a" and ranked[0].rank == 1 and ranked[0].percentile == 1.0
    assert ranked[1].account == "@b" and ranked[1].rank == 2
