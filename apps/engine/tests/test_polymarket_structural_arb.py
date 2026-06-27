# intent: offline unit tests for the SINGLE-VENUE Polymarket structural-arb scout (scripts/research/
# polymarket_structural_arb_scout.py). Covers the LOAD-BEARING pure math the scout report's numbers come from:
# the depth-walk VWAP, the box pricing net of the REAL per-category fee, the SEQUENTIAL-FILL adverse-move
# haircut, the exclusion guards, and the Gamma/CLOB parsing (Shape A neg-risk binaries + Shape B categorical) via
# an INJECTED fetcher — never a live socket (the session-wide network guard would fail a real connection anyway).
# These tests assert the arb sign convention is right (a sub-$1 basket is +edge; fee + haircut only ever REDUCE
# it) so a future build can't ship a sign-flipped "edge".

from __future__ import annotations

import pytest

from cosmu.spine.asset_fees import polymarket_category_fee_rate
from scripts.research.polymarket_structural_arb_scout import (
    ADVERSE_MOVE_TICKS,
    TICK,
    Group,
    Leg,
    discover_groups,
    exclusions,
    leg_fee_frac,
    price_basket,
    vwap_to_fill,
)


# --------------------------------------------------------------------------------------------------------------
# vwap_to_fill — the static depth haircut (walk the ask ladder to the ticket).
# --------------------------------------------------------------------------------------------------------------
def test_vwap_single_level_is_best_ask():
    vwap, filled = vwap_to_fill([(0.30, 1000.0)], 100.0)
    assert vwap == pytest.approx(0.30)
    assert filled == pytest.approx(100.0)


def test_vwap_walks_up_the_book_when_top_is_thin():
    # 40 shares @ 0.30 then 60 @ 0.32 to fill 100 → VWAP = (40*.30 + 60*.32)/100 = 0.312
    vwap, filled = vwap_to_fill([(0.30, 40.0), (0.32, 60.0)], 100.0)
    assert vwap == pytest.approx(0.312)
    assert filled == pytest.approx(100.0)


def test_vwap_unsorted_book_is_handled():
    vwap, _ = vwap_to_fill([(0.32, 60.0), (0.30, 40.0)], 100.0)  # cheapest must be taken first regardless
    assert vwap == pytest.approx(0.312)


def test_vwap_partial_fill_reports_what_was_available():
    vwap, filled = vwap_to_fill([(0.30, 40.0)], 100.0)  # book only has 40 of the 100 wanted
    assert vwap == pytest.approx(0.30)
    assert filled == pytest.approx(40.0)


def test_vwap_empty_book_returns_none():
    assert vwap_to_fill([], 100.0) == (None, 0.0)


# --------------------------------------------------------------------------------------------------------------
# leg_fee_frac — uses the ONE in-repo per-category fee model, not a re-hardcoded rate.
# --------------------------------------------------------------------------------------------------------------
def test_leg_fee_matches_canonical_model():
    # fee/notional = rate(category) * (1 - price)
    assert leg_fee_frac("politics", 0.40) == pytest.approx(polymarket_category_fee_rate("politics") * 0.60)


def test_unknown_category_uses_conservative_crypto_rate():
    assert leg_fee_frac("nonexistent", 0.50) == pytest.approx(polymarket_category_fee_rate("crypto") * 0.50)


def test_zero_fee_category_is_zero():
    assert leg_fee_frac("geopolitics", 0.50) == pytest.approx(0.0)


# --------------------------------------------------------------------------------------------------------------
# price_basket — the box. Sign convention + fee/haircut monotonicity.
# --------------------------------------------------------------------------------------------------------------
def _leg(label, ask, depth=10_000.0, category="geopolitics", bid=None):
    """A leg with a single deep ask level (so the static VWAP == best ask) and a tight bid (no spread guard hit).
    geopolitics has a 0% fee so the fee term is isolated out of the sign tests unless overridden."""
    bid = ask - TICK if bid is None else bid
    return Leg(label=label, yes_token=f"tok_{label}", category=category,
               asks=[(ask, depth)], bids=[(bid, depth)], liquidity_usd=50_000.0, volume_usd=50_000.0)


def _group(legs, *, neg_risk=True, exhaustive=True, shape="neg_risk"):
    return Group(event_id="e1", title="Who wins?", shape=shape, neg_risk=neg_risk,
                 exhaustive=exhaustive, legs=legs, end_ts=None)


def test_sub_dollar_basket_is_positive_edge():
    # Σ asks = 0.30 + 0.30 + 0.30 = 0.90 < 1 → gross edge +0.10. Zero-fee category, optimistic (0-tick) haircut.
    g = _group([_leg("A", 0.30), _leg("B", 0.30), _leg("C", 0.30)])
    q = price_basket(g, ticket_shares=100.0, adverse_ticks=0.0)
    assert q is not None
    assert q.gross_cost == pytest.approx(0.90)
    assert q.gross_edge == pytest.approx(0.10)
    assert q.net_edge == pytest.approx(0.10)  # no fee (geopolitics), no drift → net == gross
    assert q.all_filled is True


def test_over_dollar_basket_is_negative_edge():
    g = _group([_leg("A", 0.40), _leg("B", 0.40), _leg("C", 0.40)])  # Σ = 1.20 > 1
    q = price_basket(g, ticket_shares=100.0, adverse_ticks=0.0)
    assert q.net_edge == pytest.approx(-0.20)


def test_fee_only_reduces_edge():
    # Same sub-$1 basket but a FEE-bearing category (politics) → net edge strictly below the gross edge.
    g0 = _group([_leg("A", 0.30, category="geopolitics"), _leg("B", 0.30, category="geopolitics"),
                 _leg("C", 0.30, category="geopolitics")])
    gf = _group([_leg("A", 0.30, category="politics"), _leg("B", 0.30, category="politics"),
                 _leg("C", 0.30, category="politics")])
    q0 = price_basket(g0, ticket_shares=100.0, adverse_ticks=0.0)
    qf = price_basket(gf, ticket_shares=100.0, adverse_ticks=0.0)
    assert qf.fee_total > 0.0
    assert qf.net_edge < q0.net_edge
    # politics rate 0.04, price 0.30 → fee/share 0.04*0.30*0.70 = 0.0084; ×3 legs = 0.0252
    assert qf.fee_total == pytest.approx(3 * (0.04 * 0.30 * 0.70))


def test_sequential_fill_haircut_monotonic_in_adverse_ticks():
    g = _group([_leg("A", 0.30), _leg("B", 0.30), _leg("C", 0.30)])
    nets = [price_basket(g, ticket_shares=100.0, adverse_ticks=t).net_edge
            for t in (ADVERSE_MOVE_TICKS["optimistic"], ADVERSE_MOVE_TICKS["base"],
                      ADVERSE_MOVE_TICKS["conservative"])]
    # More adverse drift can only ever REDUCE the edge (never improve it).
    assert nets[0] >= nets[1] >= nets[2]
    # base = 1 tick on the 2 post-first legs → cost +0.02 → edge 0.10 - 0.02 = 0.08
    assert nets[1] == pytest.approx(0.10 - 2 * TICK)


def test_haircut_can_flip_a_thin_gross_arb_negative():
    # Σ asks = 0.985 (gross +0.015), but 2 ticks of drift on 2 legs (+0.04) eats it → net negative.
    g = _group([_leg("A", 0.33), _leg("B", 0.33), _leg("C", 0.325)])
    q_opt = price_basket(g, ticket_shares=100.0, adverse_ticks=0.0)
    q_cons = price_basket(g, ticket_shares=100.0, adverse_ticks=2.0)
    assert q_opt.net_edge > 0
    assert q_cons.net_edge < 0


def test_depth_haircut_walks_book_and_reduces_edge():
    # Each leg's top is thin (40 @ 0.30) then deeper @ 0.34; a 100-share ticket pays the VWAP, not the best ask.
    thin = [Leg(label=f"L{i}", yes_token=f"t{i}", category="geopolitics",
                asks=[(0.30, 40.0), (0.34, 1000.0)], bids=[(0.29, 1000.0)],
                liquidity_usd=50_000.0, volume_usd=50_000.0) for i in range(3)]
    g = _group(thin)
    q = price_basket(g, ticket_shares=100.0, adverse_ticks=0.0)
    # VWAP per leg = (40*.30 + 60*.34)/100 = 0.324; Σ = 0.972 → net edge 0.028 (vs a naive best-ask Σ=0.90).
    assert q.gross_cost == pytest.approx(0.90)            # best-ask headline
    assert q.haircut_cost == pytest.approx(3 * 0.324)     # depth-walked reality
    assert q.net_edge == pytest.approx(1.0 - 3 * 0.324)


def test_unpriceable_group_returns_none():
    g = _group([_leg("A", 0.30), Leg(label="B", yes_token="t", category=None, asks=[], bids=[])])
    assert price_basket(g, ticket_shares=100.0, adverse_ticks=0.0) is None


# --------------------------------------------------------------------------------------------------------------
# exclusions — the fat-tail / un-fillable guard.
# --------------------------------------------------------------------------------------------------------------
def test_clean_neg_risk_group_has_no_exclusions():
    g = _group([_leg("A", 0.30), _leg("B", 0.30), _leg("C", 0.30)])
    assert exclusions(g) == []


def test_non_exhaustive_group_is_excluded():
    g = _group([_leg("A", 0.30), _leg("B", 0.30)], neg_risk=False, exhaustive=False, shape="binaries")
    assert "non_exhaustive" in exclusions(g)


def test_thin_leg_is_uma_fat_tail_excluded():
    legs = [_leg("A", 0.30), _leg("B", 0.30)]
    legs[1].liquidity_usd = 100.0  # below UMA_SAFETY_LIQUIDITY_USD
    g = _group(legs)
    assert "uma_fat_tail_thin_leg" in exclusions(g)


def test_wide_spread_leg_excluded():
    legs = [_leg("A", 0.30), _leg("B", 0.30, bid=0.20)]  # 10c spread > MAX_LEG_SPREAD
    g = _group(legs)
    assert "leg_spread_too_wide" in exclusions(g)


def test_thin_top_depth_excluded():
    # Top-of-book ask USD = price*size = 0.30 * 100 = $30 < MIN_LEG_DEPTH_USD ($50).
    legs = [Leg(label="A", yes_token="a", category="geopolitics", asks=[(0.30, 100.0)],
                bids=[(0.29, 5000.0)], liquidity_usd=50_000.0),
            _leg("B", 0.30)]
    g = _group(legs)
    assert "leg_top_depth_too_thin" in exclusions(g)


def test_resolves_too_soon_excluded():
    from datetime import UTC, datetime, timedelta
    now = datetime(2026, 6, 27, tzinfo=UTC)
    g = _group([_leg("A", 0.30), _leg("B", 0.30)])
    g.end_ts = now + timedelta(hours=2)  # within FINAL_EXCLUDE_HOURS
    assert "resolves_too_soon" in exclusions(g, now=now)


# --------------------------------------------------------------------------------------------------------------
# discovery parsing — Shape A (neg-risk binaries) + Shape B (categorical), via an INJECTED fetcher (no socket).
# --------------------------------------------------------------------------------------------------------------
def _book(best_ask):
    return {"asks": [{"price": str(best_ask), "size": "5000"}],
            "bids": [{"price": str(round(best_ask - 0.01, 2)), "size": "5000"}]}


def test_discover_shape_a_neg_risk_event():
    events = [{
        "id": "ev1", "title": "Who wins the 2026 election?", "negRisk": True,
        "markets": [
            {"question": "Candidate A", "groupItemTitle": "A", "active": True, "closed": False,
             "enableOrderBook": True, "category": "politics", "clobTokenIds": '["a_yes","a_no"]',
             "liquidity": "40000", "volume": "100000"},
            {"question": "Candidate B", "groupItemTitle": "B", "active": True, "closed": False,
             "enableOrderBook": True, "category": "politics", "clobTokenIds": '["b_yes","b_no"]',
             "liquidity": "40000", "volume": "100000"},
        ],
    }]
    asks = {"a_yes": _book(0.55), "b_yes": _book(0.40)}

    def fetcher(url: str):
        if "/events" in url and "offset=0" in url:
            return events
        if "/events" in url:
            return []  # later pages empty
        for tok, b in asks.items():
            if f"token_id={tok}" in url:
                return b
        return {"asks": [], "bids": []}

    groups = discover_groups(fetcher, max_groups=10)
    assert len(groups) == 1
    g = groups[0]
    assert g.shape == "neg_risk" and g.neg_risk and g.exhaustive
    assert len(g.legs) == 2
    assert g.legs[0].best_ask == pytest.approx(0.55)
    # Σ(YES asks) = 0.95 < $1 → a (gross) sub-dollar basket the scan would price.
    q = price_basket(g, ticket_shares=100.0, adverse_ticks=0.0)
    assert q.gross_cost == pytest.approx(0.95)


def test_discover_shape_b_categorical_market():
    events = [{
        "id": "ev2", "title": "Who wins the cup?", "negRisk": False,
        "markets": [{
            "question": "Cup winner", "active": True, "closed": False, "enableOrderBook": True,
            "category": "sports", "outcomes": '["Team X","Team Y","Team Z"]',
            "clobTokenIds": '["x","y","z"]', "liquidity": "30000", "volume": "60000",
        }],
    }]
    books = {"x": _book(0.50), "y": _book(0.30), "z": _book(0.18)}

    def fetcher(url: str):
        if "/events" in url and "offset=0" in url:
            return events
        if "/events" in url:
            return []
        for tok, b in books.items():
            if f"token_id={tok}" in url:
                return b
        return {"asks": [], "bids": []}

    groups = discover_groups(fetcher, max_groups=10)
    assert len(groups) == 1
    g = groups[0]
    assert g.shape == "categorical" and g.exhaustive  # outcomes partition → exhaustive
    assert [leg.label for leg in g.legs] == ["Team X", "Team Y", "Team Z"]
    q = price_basket(g, ticket_shares=100.0, adverse_ticks=0.0)
    assert q.gross_cost == pytest.approx(0.98)  # 0.50 + 0.30 + 0.18


def test_non_neg_risk_binaries_flagged_non_exhaustive():
    events = [{
        "id": "ev3", "title": "Two unrelated binaries", "negRisk": False,
        "markets": [
            {"question": "Q1", "groupItemTitle": "Q1", "active": True, "closed": False,
             "enableOrderBook": True, "category": "politics", "clobTokenIds": '["q1","q1n"]',
             "liquidity": "40000"},
            {"question": "Q2", "groupItemTitle": "Q2", "active": True, "closed": False,
             "enableOrderBook": True, "category": "politics", "clobTokenIds": '["q2","q2n"]',
             "liquidity": "40000"},
        ],
    }]

    def fetcher(url: str):
        if "/events" in url and "offset=0" in url:
            return events
        if "/events" in url:
            return []
        return _book(0.45)

    g = discover_groups(fetcher, max_groups=10)[0]
    assert g.shape == "binaries" and not g.exhaustive
    assert "non_exhaustive" in exclusions(g)
