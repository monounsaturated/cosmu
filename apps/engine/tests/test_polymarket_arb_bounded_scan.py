# intent: offline unit tests for the BOUNDED driver around the on-main structural-arb scout
# (scripts/research/polymarket_arb_bounded_scan.py). The scout's pure math is already covered by
# test_polymarket_structural_arb.py; here we test ONLY the new bound logic the autonomous-run task added:
#   - the three budget walls (max_groups / wall-clock / API-call cap) each stop the scan and are reported
#     as the stop_reason, with HONEST partial coverage (never a raised timeout);
#   - the API-call counter wraps the real fetcher and counts every call;
#   - verdict() returns REAL_EDGE only on a clean, fully-filled, net-positive candidate, else KILL with
#     the dominant wall named.
# All via an INJECTED fetcher + injected clock — never a live socket.

from __future__ import annotations

from scripts.research.polymarket_arb_bounded_scan import (
    bounded_scan,
    verdict,
)

# --------------------------------------------------------------------------------------------------------------
# A tiny fake Gamma/CLOB world: N neg-risk events, each a 3-leg basket, with controllable best asks per event.
# --------------------------------------------------------------------------------------------------------------


def _book(best_ask: float, depth: float = 5000.0) -> dict:
    return {"asks": [{"price": str(best_ask), "size": str(depth)}],
            "bids": [{"price": str(round(best_ask - 0.01, 2)), "size": str(depth)}]}


def _event(eid: str, asks: list[float], *, neg_risk: bool = True, liq: float = 40_000.0,
           category: str = "geopolitics") -> dict:
    """A neg-risk event with len(asks) binary legs, each leg's YES token keyed eid_i."""
    return {
        "id": eid, "title": f"event {eid}", "negRisk": neg_risk,
        "markets": [
            {"question": f"cand {i}", "groupItemTitle": f"c{i}", "active": True, "closed": False,
             "enableOrderBook": True, "category": category,
             "clobTokenIds": f'["{eid}_{i}","{eid}_{i}_no"]', "liquidity": str(liq), "volume": "100000"}
            for i in range(len(asks))
        ],
    }


def _make_fetcher(events: list[dict], book_for_token):
    """Page-0 returns all events, later pages empty; token urls return their book."""

    def fetcher(url: str):
        if "/events" in url:
            return events if "offset=0" in url else []
        for ev in events:
            for i, _m in enumerate(ev["markets"]):
                tok = f"{ev['id']}_{i}"
                if f"token_id={tok}" in url:
                    return book_for_token(ev["id"], i)
        return {"asks": [], "bids": []}

    return fetcher


# --------------------------------------------------------------------------------------------------------------
# max_groups wall.
# --------------------------------------------------------------------------------------------------------------
def test_max_groups_wall_stops_at_cap():
    events = [_event(f"e{n}", [0.30, 0.30, 0.30]) for n in range(20)]
    fetcher = _make_fetcher(events, lambda eid, i: _book(0.30))
    scan = bounded_scan(fetcher, max_groups=5, budget_seconds=1e9, max_api_calls=1_000_000,
                        ticket_shares=100.0)
    assert scan.groups_scanned == 5
    assert scan.stop_reason == "max_groups"
    assert scan.target_groups == 5


# --------------------------------------------------------------------------------------------------------------
# wall-clock wall — injected monotonic clock that jumps past the budget after the first group.
# --------------------------------------------------------------------------------------------------------------
def test_budget_seconds_wall_stops_and_reports_partial():
    events = [_event(f"e{n}", [0.30, 0.30, 0.30]) for n in range(20)]
    fetcher = _make_fetcher(events, lambda eid, i: _book(0.30))
    # t0 + a few sub-budget checks (so 1-2 groups price) then a jump past the 1.0s budget.
    ticks = iter([0.0, 0.5, 0.5, 0.5, 5.0] + [100.0] * 200)

    def clock():
        try:
            return next(ticks)
        except StopIteration:
            return 1e6

    scan = bounded_scan(fetcher, max_groups=150, budget_seconds=1.0, max_api_calls=1_000_000,
                        ticket_shares=100.0, clock=clock)
    assert scan.stop_reason == "budget_seconds"
    assert 0 < scan.groups_scanned < 20      # honest partial — not the whole universe, no raise


# --------------------------------------------------------------------------------------------------------------
# API-call cap wall — counts real calls through the wrapped fetcher.
# --------------------------------------------------------------------------------------------------------------
def test_api_call_cap_wall_stops_scan():
    events = [_event(f"e{n}", [0.30, 0.30, 0.30]) for n in range(50)]
    counter = [0]

    def counting(url: str):
        counter[0] += 1
        base = _make_fetcher(events, lambda eid, i: _book(0.30))
        return base(url)

    # 1 events page + 3 book calls/group → cap of ~13 admits the page + ~4 groups, then trips.
    scan = bounded_scan(counting, max_groups=150, budget_seconds=1e9, max_api_calls=13,
                        ticket_shares=100.0, api_counter=counter)
    assert scan.stop_reason == "max_api_calls"
    assert scan.api_calls >= 13
    assert scan.groups_scanned < 50


def test_pages_exhausted_when_under_all_walls():
    events = [_event(f"e{n}", [0.30, 0.30, 0.30]) for n in range(3)]
    fetcher = _make_fetcher(events, lambda eid, i: _book(0.30))
    scan = bounded_scan(fetcher, max_groups=150, budget_seconds=1e9, max_api_calls=1_000_000,
                        ticket_shares=100.0)
    assert scan.groups_scanned == 3
    assert scan.stop_reason == "pages_exhausted"


# --------------------------------------------------------------------------------------------------------------
# verdict — REAL_EDGE vs KILL + the named wall.
# --------------------------------------------------------------------------------------------------------------
def test_verdict_real_edge_on_clean_sub_dollar_basket():
    # Σ asks = 0.27*3 = 0.81; geopolitics 0% fee; base drift 1 tick on 2 legs (+0.02) → net ~0.17 > 0.
    events = [_event("win", [0.27, 0.27, 0.27], liq=40_000.0)]
    fetcher = _make_fetcher(events, lambda eid, i: _book(0.27))
    scan = bounded_scan(fetcher, max_groups=150, budget_seconds=1e9, max_api_calls=1_000_000,
                        ticket_shares=100.0)
    vd = verdict(scan)
    assert vd["verdict"] == "REAL_EDGE"
    assert vd["live_test_warranted"] is True
    assert vd["net_haircut_candidates"] == 1
    assert vd["wall"] is None


def test_verdict_kill_when_over_dollar():
    events = [_event("lose", [0.40, 0.40, 0.40])]  # Σ = 1.20 > 1 → no gross sub-$1 basket at all
    fetcher = _make_fetcher(events, lambda eid, i: _book(0.40))
    scan = bounded_scan(fetcher, max_groups=150, budget_seconds=1e9, max_api_calls=1_000_000,
                        ticket_shares=100.0)
    vd = verdict(scan)
    assert vd["verdict"] == "KILL"
    assert vd["live_test_warranted"] is False
    assert vd["gross_sub_dollar_groups"] == 0


def test_verdict_kill_names_resolution_trust_wall_on_thin_uma_leg():
    # Gross sub-$1 (Σ=0.81) but one leg is below the UMA safety floor → excluded as fat-tail thin leg.
    events = [_event("thin", [0.27, 0.27, 0.27], liq=40_000.0)]

    def book_for_token(eid, i):
        return _book(0.27, depth=300.0) if i == 1 else _book(0.27, depth=5000.0)

    # Force one leg's liquidity below the UMA floor via a low event liquidity on that market only:
    events[0]["markets"][1]["liquidity"] = "1000"  # < UMA_SAFETY_LIQUIDITY_USD (2000)
    fetcher = _make_fetcher(events, book_for_token)
    scan = bounded_scan(fetcher, max_groups=150, budget_seconds=1e9, max_api_calls=1_000_000,
                        ticket_shares=100.0)
    vd = verdict(scan)
    assert vd["verdict"] == "KILL"
    assert vd["wall"] == "uma_fat_tail_thin_leg"
    assert vd["gross_sub_dollar_groups"] == 1  # it WAS gross sub-$1, the wall is resolution-trust


def test_verdict_kill_names_haircut_wall_on_thin_gross_arb():
    # Σ asks = 0.985 (gross +0.015) but the 1-tick base drift on 2 legs (+0.02) eats it → net < 0.
    events = [_event("thin_arb", [0.33, 0.33, 0.325], liq=40_000.0)]

    def book_for_token(eid, i):
        return _book([0.33, 0.33, 0.325][i])

    fetcher = _make_fetcher(events, book_for_token)
    scan = bounded_scan(fetcher, max_groups=150, budget_seconds=1e9, max_api_calls=1_000_000,
                        ticket_shares=100.0)
    vd = verdict(scan)
    assert vd["verdict"] == "KILL"
    assert vd["gross_sub_dollar_groups"] == 1
    assert vd["wall"] == "persistence_haircut_eats_edge"
