# intent: SCOUT (zero prod impact, throwaway research) the SINGLE-VENUE Polymarket STRUCTURAL ARB — the
# price-signal-FREE edge from the cross-disciplinary playbook (bridge #6a), the strictly-better pivot after the
# cross-venue Polymarket×Kalshi scout came back NO-GO (0 matched contracts; France-excluded Kalshi execution).
#
# THESIS: in a MUTUALLY-EXCLUSIVE, EXHAUSTIVE multi-outcome group (an N-candidate election, an N-band ladder),
# exactly ONE YES leg resolves to $1 and the rest to $0. So buying ONE share of EVERY YES leg redeems exactly $1.
# If `Σ(best-ask YES across all legs)` net of the real Polymarket taker fee is PERSISTENTLY < $1, that basket is a
# market-neutral, desk-invisible, tiny-ticket structural arb — single venue (no second account, no FR/jurisdiction
# wall), on a venue already wired for execution in-repo (cosmu/adapters/exec/polymarket.py).
#
# WHAT THIS DOES (keyless, read-only, one or more live snapshots — NOT a sweep, BOUNDED):
#   1. Discover multi-outcome groups via Gamma `/events` (keyless). Handles BOTH real Polymarket shapes:
#        Shape A — N binary Yes/No markets under one event (the neg-risk election shape).
#        Shape B — ONE market carrying N outcomes (a categorical market; outcomes partition the space).
#   2. For each leg, pull the live CLOB `/book` (keyless) → best ask + full ask DEPTH (needed for the haircut).
#   3. Price the box: `Σ(YES asks)` gross, then NET of the REAL per-category Polymarket taker fee
#      (cosmu/spine/asset_fees — the ONE in-repo fee model; NOT re-hardcoded here).
#   4. ⚠️ Apply the SEQUENTIAL-FILL ADVERSE-MOVE HAIRCUT: you can NOT fill all legs atomically, so (a) each leg is
#      filled by WALKING its real ask book to the ticket size (depth VWAP ≥ best ask), and (b) legs filled after
#      the first pay an adverse-drift buffer (the book moves while you work the sequence). Swept best/base/worst.
#   5. ⚠️ EXCLUDE thin / wide-spread / non-exhaustive / near-resolution / ambiguous-UMA-resolution groups (the
#      fat-tail guard: a basket is only an arb if mutual-exclusivity AND exhaustiveness AND reliable resolution
#      ALL hold; a UMA whale once falsely resolved a $7M market — never size as if resolution is risk-free).
#   6. Flag any basket whose net-of-haircut edge stays > 0; with `--snapshots N` re-sample to MEASURE persistence.
#
# It writes NOTHING to prod (no DB, no engine change, no Gate constant touched, no money path). It prints a table +
# a SUMMARY_JSON the scout report quotes. The pure math (price_basket / haircut / exclusions) is import-clean and
# offline-unit-tested (tests/test_polymarket_structural_arb.py) via injected fetchers — no live network in tests.
#
# Run (from a Polymarket-reachable environment — keyless, no account/key):
#   python3 apps/engine/scripts/research/polymarket_structural_arb_scout.py [--max-groups 50] [--ticket-shares 100]
#   python3 apps/engine/scripts/research/polymarket_structural_arb_scout.py --snapshots 6 --interval 120   # persistence
#
# ACCESS NOTE: Polymarket Gamma + CLOB are fully keyless. If THIS environment's egress policy blocks
# *.polymarket.com (e.g. a locked-down web session), the script reports `status=egress_blocked` and exits 0 —
# it does NOT fabricate numbers. Run it from an environment with Polymarket egress (the operator's local Mac).

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

# Make `cosmu` importable (this is the ONLY production touch — import-path plumbing for an offline research
# script; no prod behaviour). The fee model is the single in-repo source of truth; we never re-hardcode rates.
_ENGINE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ENGINE_ROOT not in sys.path:
    sys.path.insert(0, _ENGINE_ROOT)

from cosmu.spine.asset_fees import polymarket_category_fee_rate  # noqa: E402

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

# ===============================================================================================================
# CONSTANTS — the scout's "param_space": every threshold is named, with the rationale it encodes. None is a bare
# magic number buried in a branch; the report quotes these and a real build would fit them, not copy them.
# ===============================================================================================================
TICK = 0.01                      # Polymarket trades on a 1-cent probability grid; one tick = $0.01.

# --- group shape ---
MIN_LEGS = 2                     # a "group" needs >= 2 mutually-exclusive outcomes to even be a basket.
MAX_LEGS = 24                    # cap legs/group (bounded compute; a 24-way book is already deep-tail liquidity).

# --- exclusions (the fat-tail / un-fillable guard) ---
MIN_GROUP_LIQUIDITY_USD = 5_000.0   # total group book depth floor; below this the basket is a paper mirage.
MIN_LEG_DEPTH_USD = 50.0            # per-leg top-of-book ask depth floor (USD); a leg you can't lift at the quote.
MAX_LEG_SPREAD = 0.05              # 5c: a wider leg spread means the "best ask" is unreliable (you pay through it).
UMA_SAFETY_LIQUIDITY_USD = 2_000.0  # a leg thinner than this is UMA-dispute-prone (fat-tail resolution risk).
FINAL_EXCLUDE_HOURS = 24.0         # skip groups resolving within a day — stale books, redemption/settlement noise.

# --- the sequential-fill adverse-move haircut (you can NOT fill all legs atomically) ---
DEFAULT_TICKET_SHARES = 100.0      # the basket ticket: buy K shares of every YES leg (tiny-ticket by design).
# Adverse drift, in TICKS, that each leg AFTER the first moves against you while you work the non-atomic sequence.
# Swept best/base/worst so the verdict carries an honest sensitivity band, never one optimistic point estimate.
ADVERSE_MOVE_TICKS = {"optimistic": 0.0, "base": 1.0, "conservative": 2.0}
ADVERSE_PRIMARY = "base"


# ===============================================================================================================
# DATA MODEL
# ===============================================================================================================
@dataclass
class Leg:
    """One YES outcome of a mutually-exclusive group: its label, the CLOB YES token, the per-category fee axis,
    the live ask book (price, size — sorted cheapest-first), and the metadata the exclusion guards read."""

    label: str
    yes_token: str
    category: str | None
    asks: list[tuple[float, float]]      # (price, size) ascending by price — the real CLOB ask ladder.
    bids: list[tuple[float, float]]      # (price, size) descending by price — for the touch spread.
    liquidity_usd: float = 0.0
    volume_usd: float = 0.0

    @property
    def best_ask(self) -> float | None:
        return self.asks[0][0] if self.asks else None

    @property
    def best_bid(self) -> float | None:
        return self.bids[0][0] if self.bids else None

    @property
    def spread(self) -> float | None:
        if not self.asks or not self.bids:
            return None
        return self.asks[0][0] - self.bids[0][0]


@dataclass
class Group:
    """A multi-outcome basket candidate: the legs, the mutual-exclusivity provenance (neg-risk set vs single
    categorical market vs un-linked binaries), and whether the listed outcomes are EXHAUSTIVE (one MUST win — the
    precondition that turns `Σ(YES) < $1` into a guaranteed $1 redemption rather than a punt)."""

    event_id: str
    title: str
    shape: str                  # "neg_risk" | "categorical" | "binaries"
    neg_risk: bool
    exhaustive: bool
    legs: list[Leg]
    end_ts: datetime | None = None
    notes: list[str] = field(default_factory=list)


# ===============================================================================================================
# PURE MATH — no network; fully unit-tested. These are the load-bearing functions the report's numbers come from.
# ===============================================================================================================
def leg_fee_frac(category: str | None, price: float) -> float:
    """Polymarket taker fee as a FRACTION of the notional paid for one YES share at `price`, using the ONE in-repo
    per-category fee model. Polymarket charges fee = shares × rate(category) × price × (1 − price); per unit of
    notional (= price) that is rate × (1 − price). Unknown category → the conservative crypto rate (over-charge,
    never under). Fees are entry-only here: the winning leg REDEEMS at $1 (not a trade → no fee) and the losing
    legs expire worthless (no sell → no fee), so a hold-to-resolution basket pays exactly N entry taker fees."""
    p = max(0.0, min(1.0, price))
    return polymarket_category_fee_rate(category) * (1.0 - p)


def vwap_to_fill(asks: list[tuple[float, float]], ticket_shares: float) -> tuple[float | None, float]:
    """Walk the ask ladder to BUY `ticket_shares`, returning (volume-weighted avg fill price, shares actually
    filled). This is the STATIC depth haircut: a basket buyer is a taker who lifts offers, so the real cost of a
    leg is not its best ask but the VWAP up the book to the ticket size. Returns (None, 0) on an empty book; if the
    book is too thin to fill the full ticket, returns the VWAP of what WAS available + the (smaller) filled size,
    so the caller can flag the leg as not-fully-fillable."""
    if not asks or ticket_shares <= 0:
        return (None, 0.0)
    remaining = ticket_shares
    cost = 0.0
    filled = 0.0
    for price, size in sorted(asks):          # cheapest first regardless of returned order
        take = min(remaining, size)
        cost += take * price
        filled += take
        remaining -= take
        if remaining <= 1e-9:
            break
    if filled <= 0:
        return (None, 0.0)
    return (cost / filled, filled)


@dataclass
class LegFill:
    """The modeled fill of one leg at the basket ticket: the depth VWAP, the adverse-drift add-on, the all-in
    fill price, the per-share fee, and whether the book could supply the full ticket."""

    label: str
    vwap: float
    adverse_drift: float
    fill_price: float            # vwap + adverse_drift (the price you actually pay per share)
    fee_per_share: float         # fill_price × fee_frac(category, fill_price)
    filled_shares: float
    fully_filled: bool


@dataclass
class BasketQuote:
    """The priced basket at one ticket size + one adverse-drift assumption. `net_edge` is the per-$1-redemption
    profit after fees AND the sequential-fill haircut: > 0 ⇒ a fillable structural arb (subject to exclusions)."""

    n_legs: int
    ticket_shares: float
    adverse_ticks: float
    gross_cost: float            # Σ best-ask (the naive Σ(YES) the thesis names)
    haircut_cost: float          # Σ fill_price (depth VWAP + adverse drift), no fee
    total_cost: float            # Σ fill_price × (1 + fee_frac)  — all-in per 1 share of each leg
    fee_total: float             # Σ fee_per_share
    gross_edge: float            # 1 − gross_cost (best-ask only — the headline, pre-haircut/fee)
    net_edge: float              # 1 − total_cost  (the HONEST number: post-fee, post-haircut)
    all_filled: bool             # every leg could supply the full ticket
    leg_fills: list[LegFill]


def price_basket(group: Group, *, ticket_shares: float, adverse_ticks: float) -> BasketQuote | None:
    """Price the buy-every-YES-leg basket for `group` at a ticket of `ticket_shares` per leg, applying the
    sequential-fill adverse-move haircut at `adverse_ticks` ticks of drift per post-first leg. Returns None if any
    leg has no ask book at all (un-priceable). The redemption is exactly $1 (one leg wins) regardless of the ticket
    size, so the per-$1 edge = 1 − Σ(all-in fill cost per share); scaling the ticket only changes the depth VWAP."""
    if len(group.legs) < MIN_LEGS:
        return None
    fills: list[LegFill] = []
    gross_cost = 0.0
    for i, leg in enumerate(group.legs):
        if leg.best_ask is None:
            return None
        vwap, filled = vwap_to_fill(leg.asks, ticket_shares)
        if vwap is None:
            return None
        # Leg 1 fills at the live snapshot; every later leg has had time to drift against you while you worked the
        # earlier legs (you can't fill atomically). Conservative & symmetric: drift only ADDS to the buy cost.
        drift = (adverse_ticks * TICK) if i >= 1 else 0.0
        fill_price = min(1.0, vwap + drift)
        fee = fill_price * leg_fee_frac(leg.category, fill_price)
        fills.append(
            LegFill(
                label=leg.label, vwap=round(vwap, 6), adverse_drift=round(drift, 6),
                fill_price=round(fill_price, 6), fee_per_share=round(fee, 6),
                filled_shares=round(filled, 4), fully_filled=filled >= ticket_shares - 1e-6,
            )
        )
        gross_cost += leg.best_ask
    haircut_cost = sum(f.fill_price for f in fills)
    fee_total = sum(f.fee_per_share for f in fills)
    total_cost = haircut_cost + fee_total
    return BasketQuote(
        n_legs=len(group.legs), ticket_shares=ticket_shares, adverse_ticks=adverse_ticks,
        gross_cost=round(gross_cost, 6), haircut_cost=round(haircut_cost, 6),
        total_cost=round(total_cost, 6), fee_total=round(fee_total, 6),
        gross_edge=round(1.0 - gross_cost, 6), net_edge=round(1.0 - total_cost, 6),
        all_filled=all(f.fully_filled for f in fills), leg_fills=fills,
    )


def exclusions(group: Group, *, now: datetime | None = None) -> list[str]:
    """Every reason `group` is NOT a clean, fillable structural arb — empty list ⇒ it clears the structural guards
    (it can still be a sub-$1 basket that we'd then trust). The guards encode the fat-tail lesson: a basket is only
    market-neutral if mutual-exclusivity AND exhaustiveness AND reliable resolution AND real fillable depth ALL
    hold. Order is stable so the report reads the same every run."""
    reasons: list[str] = []
    now = now or datetime.now(tz=UTC)

    if len(group.legs) < MIN_LEGS:
        reasons.append("too_few_legs")
    if len(group.legs) > MAX_LEGS:
        reasons.append("too_many_legs")

    # Exhaustiveness — the precondition that turns Σ(YES)<$1 into a guaranteed $1. A non-neg-risk set of separate
    # binary markets is NOT provably exhaustive (zero of them could resolve YES) → the basket can pay $0.
    if not group.exhaustive:
        reasons.append("non_exhaustive")

    group_liq = sum(leg.liquidity_usd for leg in group.legs)
    if group_liq < MIN_GROUP_LIQUIDITY_USD:
        reasons.append("group_too_thin")

    # Per-leg structural-quality guards.
    for leg in group.legs:
        if leg.liquidity_usd and leg.liquidity_usd < UMA_SAFETY_LIQUIDITY_USD:
            reasons.append("uma_fat_tail_thin_leg")
            break
    for leg in group.legs:
        sp = leg.spread
        if sp is not None and sp > MAX_LEG_SPREAD:
            reasons.append("leg_spread_too_wide")
            break
    for leg in group.legs:
        if leg.best_ask is not None:
            top_depth_usd = (leg.asks[0][0] * leg.asks[0][1]) if leg.asks else 0.0
            if top_depth_usd < MIN_LEG_DEPTH_USD:
                reasons.append("leg_top_depth_too_thin")
                break

    if group.end_ts is not None:
        hours_left = (group.end_ts - now).total_seconds() / 3600.0
        if hours_left <= FINAL_EXCLUDE_HOURS:
            reasons.append("resolves_too_soon")

    # De-dup while preserving first-seen order.
    seen: set[str] = set()
    return [r for r in reasons if not (r in seen or seen.add(r))]


# ===============================================================================================================
# LIVE FETCH (network — injectable `fetcher` seam so tests never open a socket).
# ===============================================================================================================
def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:  # pragma: no cover - sandbox fallback
        return ssl.create_default_context()


class EgressBlocked(RuntimeError):
    """Raised when the environment's egress policy denies *.polymarket.com (proxy 403/407 on CONNECT). The scout
    catches this at the top level and reports `status=egress_blocked` rather than fabricating numbers."""


def _live_fetch(url: str, *, retries: int = 3, ctx: ssl.SSLContext | None = None) -> object:
    ctx = ctx or _ssl_context()
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cosmu-engine/0.1 (structural-arb-scout)"})
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (403, 407):
                raise EgressBlocked(f"proxy/policy denied {url} (HTTP {e.code})") from e
            if e.code in (400, 401, 404):
                raise
            last = e
        except urllib.error.URLError as e:
            # A proxy CONNECT denial surfaces as a tunnel error, not an HTTPError.
            if "403" in str(e.reason) or "407" in str(e.reason) or "Tunnel connection failed" in str(e.reason):
                raise EgressBlocked(f"proxy/policy denied {url}: {e.reason}") from e
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(0.4 * (attempt + 1))
    if last:
        raise last
    return None


def _as_list(raw: object) -> list:
    """Gamma encodes vectors as JSON strings ('["a","b"]') OR real lists. Coerce to a list, [] on anything else."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    return raw if isinstance(raw, list) else []


def _f(raw: object) -> float | None:
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def fetch_book(token: str, fetcher: Callable[[str], object]) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """The live CLOB order book for one YES token → (asks ascending, bids descending), each (price, size). Empty
    on any failure (one dead book never aborts the scan). The depth ladder is what the haircut walks."""
    try:
        b = fetcher(f"{CLOB}/book?token_id={urllib.parse.quote(token)}")
    except EgressBlocked:
        raise
    except Exception:  # noqa: BLE001 — one dead/empty book is skipped, never aborts the scan
        return ([], [])
    if not isinstance(b, dict):
        return ([], [])
    asks: list[tuple[float, float]] = []
    for x in b.get("asks", []) or []:
        p, s = _f(x.get("price")), _f(x.get("size"))
        if p is not None and s is not None and s > 0:
            asks.append((p, s))
    bids: list[tuple[float, float]] = []
    for x in b.get("bids", []) or []:
        p, s = _f(x.get("price")), _f(x.get("size"))
        if p is not None and s is not None and s > 0:
            bids.append((p, s))
    return (sorted(asks), sorted(bids, reverse=True))


def _coerce_end_ts(raw: object) -> datetime | None:
    if raw is None or raw == "":
        return None
    try:
        s = str(raw).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _market_leg(m: dict, fetcher: Callable[[str], object], *, label: str) -> Leg | None:
    """Build a Leg from a Gamma market row (Shape A — a binary Yes/No market is one leg) by pulling its YES book."""
    tokens = _as_list(m.get("clobTokenIds"))
    if not tokens:
        return None
    yes_token = str(tokens[0])
    asks, bids = fetch_book(yes_token, fetcher)
    return Leg(
        label=label, yes_token=yes_token, category=(m.get("category") or None),
        asks=asks, bids=bids,
        liquidity_usd=float(m.get("liquidityClob") or m.get("liquidity") or 0.0),
        volume_usd=float(m.get("volume") or m.get("volumeClob") or 0.0),
    )


def _categorical_legs(m: dict, fetcher: Callable[[str], object]) -> list[Leg]:
    """Build legs from a single multi-outcome market (Shape B): each (outcome, token) pair is one leg. A single
    categorical market's outcomes PARTITION the space, so the group is mutually-exclusive AND exhaustive."""
    tokens = _as_list(m.get("clobTokenIds"))
    outcomes = _as_list(m.get("outcomes"))
    legs: list[Leg] = []
    cat = m.get("category") or None
    liq = float(m.get("liquidityClob") or m.get("liquidity") or 0.0)
    vol = float(m.get("volume") or m.get("volumeClob") or 0.0)
    for i, tok in enumerate(tokens):
        asks, bids = fetch_book(str(tok), fetcher)
        label = str(outcomes[i]) if i < len(outcomes) else f"outcome_{i}"
        # Split the market-level liquidity across legs as a conservative per-leg proxy (real per-token depth is
        # measured from the book itself; this only feeds the coarse group/leg liquidity guards).
        legs.append(Leg(label=label, yes_token=str(tok), category=cat, asks=asks, bids=bids,
                        liquidity_usd=liq / max(1, len(tokens)), volume_usd=vol / max(1, len(tokens))))
    return legs


def _group_from_event(ev: dict, fetcher: Callable[[str], object]) -> Group | None:
    """Turn one Gamma event into a Group (or None if it is not a multi-outcome basket). Detects Shape A (>=2
    binary Yes/No markets, neg-risk or not) vs Shape B (a single market with >=3 outcomes)."""
    raw_markets = ev.get("markets") or []
    neg_risk = bool(ev.get("negRisk"))
    title = str(ev.get("title") or ev.get("slug") or "")
    event_id = str(ev.get("id") or "")
    end_ts = _coerce_end_ts(ev.get("endDate"))

    # Only live, order-book-enabled, non-closed binary markets count as legs.
    active = [
        m for m in raw_markets
        if isinstance(m, dict) and m.get("active") and not m.get("closed") and m.get("enableOrderBook")
    ]

    # Shape B: a single market carrying many outcomes (a categorical market) — mutually-exclusive AND exhaustive.
    if len(active) == 1:
        m = active[0]
        outcomes = _as_list(m.get("outcomes"))
        tokens = _as_list(m.get("clobTokenIds"))
        if len(outcomes) >= 3 and len(tokens) == len(outcomes):
            legs = _categorical_legs(m, fetcher)[:MAX_LEGS]
            if len(legs) >= MIN_LEGS:
                return Group(event_id=event_id, title=title, shape="categorical", neg_risk=neg_risk,
                             exhaustive=True, legs=legs, end_ts=end_ts,
                             notes=["single categorical market — outcomes partition the space"])
        return None

    # Shape A: >=2 binary Yes/No markets under one event.
    if len(active) >= MIN_LEGS:
        legs: list[Leg] = []
        for m in active[:MAX_LEGS]:
            label = str(m.get("groupItemTitle") or m.get("question") or "")[:60]
            leg = _market_leg(m, fetcher, label=label)
            if leg is not None:
                legs.append(leg)
        if len(legs) < MIN_LEGS:
            return None
        # neg-risk events are a mutually-exclusive-AND-exhaustive set by construction (exactly one resolves YES).
        # Un-linked binaries are NOT provably exhaustive — flagged so the exclusion guard refuses them.
        exhaustive = neg_risk
        shape = "neg_risk" if neg_risk else "binaries"
        notes = [] if neg_risk else ["non-neg-risk binaries: exhaustiveness UNVERIFIED (basket may pay $0)"]
        return Group(event_id=event_id, title=title, shape=shape, neg_risk=neg_risk,
                     exhaustive=exhaustive, legs=legs, end_ts=end_ts, notes=notes)
    return None


def discover_groups(fetcher: Callable[[str], object], *, max_groups: int) -> list[Group]:
    """Discover up to `max_groups` multi-outcome basket candidates from the most-liquid open Gamma events. Pages
    `/events` (keyless) and turns each into a Group. Bounded: stops at `max_groups` or when the pages run out."""
    groups: list[Group] = []
    for off in range(0, 1000, 100):
        if len(groups) >= max_groups:
            break
        url = (f"{GAMMA}/events?closed=false&active=true&limit=100&offset={off}"
               f"&order=liquidity&ascending=false")
        events = fetcher(url)
        if not isinstance(events, list) or not events:
            break
        for ev in events:
            if len(groups) >= max_groups:
                break
            if not isinstance(ev, dict):
                continue
            g = _group_from_event(ev, fetcher)
            if g is not None:
                groups.append(g)
    return groups


# ===============================================================================================================
# SCAN — one snapshot (or N, for persistence) over the discovered groups.
# ===============================================================================================================
@dataclass
class GroupResult:
    group: Group
    quote_primary: BasketQuote | None        # at the PRIMARY (base) adverse-drift assumption
    quotes_band: dict[str, BasketQuote | None]  # optimistic / base / conservative
    excl: list[str]

    @property
    def is_candidate(self) -> bool:
        """A fillable structural arb: clears ALL exclusions, fully fillable at the ticket, and net-of-haircut
        edge > 0 even at the PRIMARY (base) adverse-drift assumption."""
        q = self.quote_primary
        return (not self.excl) and q is not None and q.all_filled and q.net_edge > 0.0


def scan_once(fetcher: Callable[[str], object], *, max_groups: int, ticket_shares: float,
              now: datetime | None = None) -> list[GroupResult]:
    now = now or datetime.now(tz=UTC)
    results: list[GroupResult] = []
    for g in discover_groups(fetcher, max_groups=max_groups):
        band = {
            name: price_basket(g, ticket_shares=ticket_shares, adverse_ticks=ticks)
            for name, ticks in ADVERSE_MOVE_TICKS.items()
        }
        results.append(GroupResult(group=g, quote_primary=band[ADVERSE_PRIMARY],
                                   quotes_band=band, excl=exclusions(g, now=now)))
    return results


# ===============================================================================================================
# REPORT
# ===============================================================================================================
def _fmt(x: float | None, d: int = 4) -> str:
    return f"{x:.{d}f}" if isinstance(x, (int, float)) else "—"


def summarize(results: list[GroupResult], *, ticket_shares: float) -> dict:
    candidates = [r for r in results if r.is_candidate]
    # Sub-$1 on best-ask ALONE (pre-haircut/fee) — the naive headline the thesis names, for contrast.
    gross_sub_dollar = [r for r in results if r.quote_primary and r.quote_primary.gross_edge > 0]
    excl_counts: dict[str, int] = {}
    for r in results:
        for e in r.excl:
            excl_counts[e] = excl_counts.get(e, 0) + 1
    shapes: dict[str, int] = {}
    for r in results:
        shapes[r.group.shape] = shapes.get(r.group.shape, 0) + 1
    return {
        "groups_scanned": len(results),
        "ticket_shares": ticket_shares,
        "shapes": shapes,
        "gross_sub_dollar_groups": len(gross_sub_dollar),     # Σ(best-ask YES) < $1 ignoring fees + haircut
        "net_haircut_candidates": len(candidates),            # survive fees + sequential-fill haircut + exclusions
        "exclusion_counts": excl_counts,
        "adverse_move_ticks_band": ADVERSE_MOVE_TICKS,
        "adverse_primary": ADVERSE_PRIMARY,
        "candidates": [
            {
                "title": r.group.title[:80], "shape": r.group.shape, "n_legs": len(r.group.legs),
                "gross_cost": r.quote_primary.gross_cost,
                "net_edge_base": r.quote_primary.net_edge,
                "net_edge_optimistic": (r.quotes_band["optimistic"].net_edge
                                        if r.quotes_band["optimistic"] else None),
                "net_edge_conservative": (r.quotes_band["conservative"].net_edge
                                          if r.quotes_band["conservative"] else None),
            }
            for r in candidates
        ],
    }


def print_table(results: list[GroupResult]) -> None:
    print(f"\n{'group (title)':52s} {'shape':10s} {'legs':>4s} {'Σask':>7s} "
          f"{'net(base)':>9s} {'net(cons)':>9s}  exclusions")
    print("-" * 120)
    for r in sorted(results, key=lambda x: (x.quote_primary.net_edge if x.quote_primary else -9), reverse=True):
        q = r.quote_primary
        qc = r.quotes_band["conservative"]
        flag = "✅" if r.is_candidate else "  "
        print(f"{flag}{r.group.title[:50]:50s} {r.group.shape:10s} {len(r.group.legs):>4d} "
              f"{_fmt(q.gross_cost if q else None, 4):>7s} {_fmt(q.net_edge if q else None, 4):>9s} "
              f"{_fmt(qc.net_edge if qc else None, 4):>9s}  {','.join(r.excl) if r.excl else '-'}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Single-venue Polymarket Σ(YES)<$1 structural-arb scout (keyless).")
    ap.add_argument("--max-groups", type=int, default=50, help="multi-outcome groups to scan (bounded).")
    ap.add_argument("--ticket-shares", type=float, default=DEFAULT_TICKET_SHARES,
                    help="basket ticket: shares of every YES leg to fill (drives the depth haircut).")
    ap.add_argument("--snapshots", type=int, default=1, help="re-sample N times to MEASURE persistence.")
    ap.add_argument("--interval", type=float, default=120.0, help="seconds between persistence snapshots.")
    ap.add_argument("--json-out", default="", help="optional path to write the SUMMARY_JSON.")
    args = ap.parse_args()

    print("# Single-venue Polymarket structural-arb scout — Σ(YES legs) < $1 (keyless, read-only)\n")
    fetcher = _live_fetch

    # Persistence: track, per UNIQUE event_id (NOT the truncated title — two events can share a prefix), the
    # fraction of snapshots its base-case net edge stayed > 0. `titles` keeps the display label per id.
    persist: dict[str, list[int]] = {}
    titles: dict[str, str] = {}
    last_summary: dict = {}
    try:
        for snap in range(max(1, args.snapshots)):
            results = scan_once(fetcher, max_groups=args.max_groups, ticket_shares=args.ticket_shares)
            print_table(results)
            last_summary = summarize(results, ticket_shares=args.ticket_shares)
            for r in results:
                if r.quote_primary is None:
                    continue
                hit = 1 if r.is_candidate else 0
                key = r.group.event_id or r.group.title[:80]
                persist.setdefault(key, []).append(hit)
                titles[key] = r.group.title[:80]
            print(f"\n[snapshot {snap + 1}/{args.snapshots}] scanned={last_summary['groups_scanned']} "
                  f"gross_sub_$1={last_summary['gross_sub_dollar_groups']} "
                  f"net_haircut_candidates={last_summary['net_haircut_candidates']}")
            if snap + 1 < args.snapshots:
                time.sleep(max(0.0, args.interval))
    except EgressBlocked as e:
        blocked = {
            "status": "egress_blocked",
            "detail": str(e),
            "note": ("This environment's egress policy denies *.polymarket.com. Polymarket Gamma + CLOB are "
                     "keyless — run this script from an environment with Polymarket egress (e.g. the operator's "
                     "local Mac) to get the live snapshot. No numbers are fabricated."),
        }
        print("\n⚠️  EGRESS BLOCKED — Polymarket is unreachable from this environment.")
        print("SUMMARY_JSON:", json.dumps(blocked))
        if args.json_out:
            with open(args.json_out, "w", encoding="utf-8") as fh:
                json.dump(blocked, fh, indent=2)
        return 0

    if args.snapshots > 1:
        persistence = {
            titles[key]: {"snapshots": len(hits), "hit_rate": round(sum(hits) / len(hits), 3)}
            for key, hits in persist.items() if sum(hits) > 0
        }
        last_summary["persistence_of_candidates"] = persistence
        print(f"\n[persistence over {args.snapshots} snapshots] "
              f"{len([t for t, h in persist.items() if sum(h) > 0])} group(s) flagged at least once; "
              f"persistently-sub-$1 (hit_rate==1.0): "
              f"{len([t for t, h in persist.items() if h and sum(h) == len(h)])}")

    last_summary["status"] = "ok"
    last_summary["generated"] = datetime.now(UTC).isoformat(timespec="seconds")
    print("\nSUMMARY_JSON:", json.dumps(last_summary))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(last_summary, fh, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
