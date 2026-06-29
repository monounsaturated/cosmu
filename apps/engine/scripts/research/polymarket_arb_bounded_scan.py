# intent: BOUNDED live driver around the on-main single-venue Polymarket structural-arb SCOUT
# (scripts/research/polymarket_structural_arb_scout.py, shipped in PR #449). The scout's PURE math
# (price_basket / vwap_to_fill / exclusions / leg_fee_frac) and its Gamma/CLOB parsing
# (_group_from_event / fetch_book) are reused verbatim — this file adds ONLY the three things the
# bounded autonomous-run task requires and the scout did not enforce:
#
#   1. VOLUME-ORDERED discovery: the scout pages /events by `liquidity`; the arb is only fillable on
#      LIQUID-AND-TRADED markets, so we page by `volume24hr` (the operator's "top ~150 most-liquid
#      multi-outcome markets by 24h volume") and STOP at MAX_GROUPS.
#   2. A HARD COMPUTE BUDGET — a prior unbounded sweep timed out at 27 min. We enforce BOTH a
#      wall-clock wall (BUDGET_SECONDS) AND an API-call cap (MAX_API_CALLS); the first to trip stops
#      the scan and we emit an HONEST PARTIAL verdict reporting COVERAGE (groups scanned vs the liquid
#      universe target), never a timeout, never a fabricated number.
#   3. COVERAGE accounting + a single pre-registered VERDICT block the report/PR quote directly.
#
# It writes NOTHING to prod (no DB, no engine change, no Gate constant, no money path) and NEVER places
# a trade — read-only scan + analysis only. Keyless (Gamma + CLOB). On an egress-blocked environment it
# reports status=egress_blocked and exits 0 (no fabrication), exactly like the scout.
#
# Run (from a Polymarket-reachable env — the operator's local Mac):
#   python3 scripts/research/polymarket_arb_bounded_scan.py [--max-groups 150] [--budget-seconds 720]
#       [--max-api-calls 300] [--ticket-shares 100] [--json-out path]

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

_ENGINE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

# Reuse the on-main scout verbatim — the load-bearing math + parsing live there and are unit-tested.
from scripts.research.polymarket_structural_arb_scout import (  # noqa: E402
    ADVERSE_MOVE_TICKS,
    ADVERSE_PRIMARY,
    EgressBlocked,
    GroupResult,
    _group_from_event,
    _live_fetch,
    exclusions,
    price_basket,
)

GAMMA = "https://gamma-api.polymarket.com"

# --- the hard compute budget (a prior unbounded run timed out at 27 min) ---
DEFAULT_MAX_GROUPS = 150          # the operator's "top ~150 most-liquid multi-outcome markets".
DEFAULT_BUDGET_SECONDS = 720.0    # ~12 min wall-clock wall; whichever wall trips first stops the scan.
DEFAULT_MAX_API_CALLS = 300       # API-call cap; one /book per leg dominates the call count.


@dataclass
class BoundedScan:
    """The bounded scan result: the per-group results plus the COVERAGE accounting the verdict needs to
    be honest about how much of the liquid universe was actually seen before the budget tripped."""

    results: list[GroupResult]
    groups_scanned: int            # multi-outcome groups fully priced
    events_seen: int               # Gamma events inspected (incl. non-basket ones skipped)
    api_calls: int                 # total Gamma + CLOB calls made
    elapsed_s: float
    stop_reason: str               # "max_groups" | "budget_seconds" | "max_api_calls" | "pages_exhausted"
    target_groups: int


def _budgeted_fetcher(base: Callable[[str], object], counter: list[int]) -> Callable[[str], object]:
    """Wrap the live fetcher to COUNT every API call (so the cap is enforced on the real call count, not
    a guess). The counter is a 1-element list so the closure mutates the caller's tally."""

    def fetch(url: str) -> object:
        counter[0] += 1
        return base(url)

    return fetch


def bounded_scan(
    fetcher: Callable[[str], object],
    *,
    max_groups: int,
    budget_seconds: float,
    max_api_calls: int,
    ticket_shares: float,
    now: datetime | None = None,
    api_counter: list[int] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> BoundedScan:
    """Discover the top-`max_groups` multi-outcome groups by 24h volume and price each, STOPPING the
    moment any budget wall trips (groups / wall-clock / API calls). Honest-partial by construction: a
    half-finished scan returns what it priced plus the stop reason, never raises a timeout.

    `clock`, `api_counter`, and `now` are injectable so the bound logic is unit-testable offline."""
    now = now or datetime.now(tz=UTC)
    counter = api_counter if api_counter is not None else [0]
    t0 = clock()
    results: list[GroupResult] = []
    events_seen = 0
    stop_reason = "pages_exhausted"

    def budget_tripped() -> str | None:
        if len(results) >= max_groups:
            return "max_groups"
        if (clock() - t0) >= budget_seconds:
            return "budget_seconds"
        if counter[0] >= max_api_calls:
            return "max_api_calls"
        return None

    # Page /events by 24h VOLUME descending (the fillable-universe order). Gamma caps limit at 100/page;
    # 1000 offset ceiling matches the scout and is far past where MAX_GROUPS is hit on liquid markets.
    for off in range(0, 1000, 100):
        tripped = budget_tripped()
        if tripped:
            stop_reason = tripped
            break
        url = (f"{GAMMA}/events?closed=false&active=true&limit=100&offset={off}"
               f"&order=volume24hr&ascending=false")
        events = fetcher(url)
        if not isinstance(events, list) or not events:
            stop_reason = "pages_exhausted"
            break
        for ev in events:
            tripped = budget_tripped()
            if tripped:
                stop_reason = tripped
                break
            if not isinstance(ev, dict):
                continue
            events_seen += 1
            g = _group_from_event(ev, fetcher)   # pulls each leg's CLOB book (the API-call hot path)
            if g is None:
                continue
            band = {
                name: price_basket(g, ticket_shares=ticket_shares, adverse_ticks=ticks)
                for name, ticks in ADVERSE_MOVE_TICKS.items()
            }
            results.append(
                GroupResult(group=g, quote_primary=band[ADVERSE_PRIMARY],
                            quotes_band=band, excl=exclusions(g, now=now))
            )
        else:
            continue
        break  # inner loop broke on a budget trip → stop paging too

    return BoundedScan(
        results=results, groups_scanned=len(results), events_seen=events_seen,
        api_calls=counter[0], elapsed_s=round(clock() - t0, 2),
        stop_reason=stop_reason, target_groups=max_groups,
    )


def verdict(scan: BoundedScan) -> dict:
    """The pre-registered VERDICT. REAL edge ⇔ at least one group clears ALL exclusions, is fully fillable
    at the ticket, AND keeps net-of-fee-and-haircut edge > 0 at the PRIMARY (base) adverse-drift band.
    Otherwise KILL, naming the dominant WALL (the most common exclusion / failure mode)."""
    results = scan.results
    candidates = [r for r in results if r.is_candidate]
    gross_sub_dollar = [r for r in results if r.quote_primary and r.quote_primary.gross_edge > 0]
    # Of the gross sub-$1 baskets, why did each fail to become a real candidate? Name the wall.
    walls: dict[str, int] = {}
    for r in gross_sub_dollar:
        if r.is_candidate:
            continue
        if r.excl:
            for e in r.excl:
                walls[e] = walls.get(e, 0) + 1
        elif r.quote_primary and not r.quote_primary.all_filled:
            walls["fillability_partial_fill"] = walls.get("fillability_partial_fill", 0) + 1
        elif r.quote_primary and r.quote_primary.net_edge <= 0:
            walls["persistence_haircut_eats_edge"] = walls.get("persistence_haircut_eats_edge", 0) + 1
    dominant_wall = max(walls, key=lambda k: walls[k]) if walls else None

    is_real = len(candidates) > 0
    return {
        "verdict": "REAL_EDGE" if is_real else "KILL",
        "wall": None if is_real else (dominant_wall or "no_gross_sub_dollar_basket_found"),
        "live_test_warranted": is_real,
        "net_haircut_candidates": len(candidates),
        "gross_sub_dollar_groups": len(gross_sub_dollar),
        "wall_breakdown": dict(sorted(walls.items(), key=lambda kv: -kv[1])),
        "candidates": [
            {
                "title": r.group.title[:90], "shape": r.group.shape, "n_legs": len(r.group.legs),
                "gross_cost": r.quote_primary.gross_cost,
                "net_edge_optimistic": (r.quotes_band["optimistic"].net_edge
                                        if r.quotes_band["optimistic"] else None),
                "net_edge_base": r.quote_primary.net_edge,
                "net_edge_conservative": (r.quotes_band["conservative"].net_edge
                                          if r.quotes_band["conservative"] else None),
                "exclusions": r.excl,
            }
            for r in candidates
        ],
    }


def _coverage(scan: BoundedScan) -> dict:
    return {
        "target_groups": scan.target_groups,
        "groups_scanned": scan.groups_scanned,
        "coverage_pct": (round(100.0 * scan.groups_scanned / scan.target_groups, 1)
                         if scan.target_groups else None),
        "events_seen": scan.events_seen,
        "api_calls": scan.api_calls,
        "elapsed_s": scan.elapsed_s,
        "stop_reason": scan.stop_reason,
    }


def _print_table(scan: BoundedScan) -> None:
    print(f"\n{'group (title)':52s} {'shape':10s} {'legs':>4s} {'Σask':>7s} "
          f"{'net(base)':>9s} {'net(cons)':>9s}  exclusions")
    print("-" * 122)
    ranked = sorted(scan.results,
                    key=lambda x: (x.quote_primary.net_edge if x.quote_primary else -9), reverse=True)
    for r in ranked:
        q = r.quote_primary
        qc = r.quotes_band["conservative"]
        flag = "REAL " if r.is_candidate else "     "
        gross = f"{q.gross_cost:.4f}" if q else "—"
        nb = f"{q.net_edge:.4f}" if q else "—"
        nc = f"{qc.net_edge:.4f}" if qc else "—"
        print(f"{flag}{r.group.title[:47]:47s} {r.group.shape:10s} {len(r.group.legs):>4d} "
              f"{gross:>7s} {nb:>9s} {nc:>9s}  {','.join(r.excl) if r.excl else '-'}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="BOUNDED live scan of the on-main single-venue Polymarket Σ(YES)<$1 structural-arb scout.")
    ap.add_argument("--max-groups", type=int, default=DEFAULT_MAX_GROUPS)
    ap.add_argument("--budget-seconds", type=float, default=DEFAULT_BUDGET_SECONDS)
    ap.add_argument("--max-api-calls", type=int, default=DEFAULT_MAX_API_CALLS)
    ap.add_argument("--ticket-shares", type=float, default=100.0)
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    print("# BOUNDED Polymarket structural-arb scan — Σ(YES legs) < $1, top markets by 24h volume "
          "(keyless, read-only)\n")
    counter = [0]
    fetcher = _budgeted_fetcher(_live_fetch, counter)
    try:
        scan = bounded_scan(
            fetcher, max_groups=args.max_groups, budget_seconds=args.budget_seconds,
            max_api_calls=args.max_api_calls, ticket_shares=args.ticket_shares, api_counter=counter,
        )
    except EgressBlocked as e:
        blocked = {
            "status": "egress_blocked", "detail": str(e),
            "note": ("egress policy denies *.polymarket.com — run from a Polymarket-reachable env "
                     "(operator's local Mac). No numbers fabricated."),
        }
        print("\nEGRESS BLOCKED — Polymarket unreachable from this environment.")
        print("SUMMARY_JSON:", json.dumps(blocked))
        if args.json_out:
            with open(args.json_out, "w", encoding="utf-8") as fh:
                json.dump(blocked, fh, indent=2)
        return 0

    _print_table(scan)
    cov = _coverage(scan)
    vd = verdict(scan)
    summary = {
        "status": "ok",
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "ticket_shares": args.ticket_shares,
        "adverse_move_ticks_band": ADVERSE_MOVE_TICKS,
        "adverse_primary": ADVERSE_PRIMARY,
        "coverage": cov,
        **vd,
    }
    print(f"\n[coverage] scanned {cov['groups_scanned']}/{cov['target_groups']} groups "
          f"({cov['coverage_pct']}%), events_seen={cov['events_seen']}, api_calls={cov['api_calls']}, "
          f"elapsed={cov['elapsed_s']}s, stop={cov['stop_reason']}")
    print(f"[verdict] {vd['verdict']} (wall={vd['wall']}) — "
          f"gross_sub_$1={vd['gross_sub_dollar_groups']}, net_haircut_candidates="
          f"{vd['net_haircut_candidates']}, live_test_warranted={vd['live_test_warranted']}")
    print("\nSUMMARY_JSON:", json.dumps(summary))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
