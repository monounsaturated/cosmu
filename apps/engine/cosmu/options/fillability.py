# intent: the BINDING test that separates a real options edge from a mid-price mirage. The wall in options is
# FILLABILITY: most "inefficiencies" computed off the MID evaporate across the wide off-ATM bid-ask. A camper owns
# the THEORY (it returns `mid_edge_usd`, its edge valued at the MIDs). This model owns the MICROSTRUCTURE — what
# moving from mid to the executable touch costs (or earns), plus Deribit's (maker==taker) fee, plus how big a fill
# the resting size supports. It is therefore theory-agnostic: it never re-derives parity/convexity, it only adjusts
# a mid edge for the spread you must cross (taker) or can earn (maker) and the fee you always pay.
#   - TAKER: you cross every leg now → you GIVE UP a half-spread per leg. taker_edge = mid − Σ½spread − fees.
#       A positive taker edge is a genuine riskless LOCK (executable this instant). Vanishingly rare; when it shows
#       it is almost always a stale quote about to vanish in ms — flagged, not celebrated.
#   - MAKER: you REST on the favorable touch → you EARN a half-spread per leg IF filled. maker_edge = mid + Σ½spread
#       − fees. The scanner is maker-by-nature (the sub-capacity, non-latency lane). A SINGLE-leg maker edge is
#       plausibly capturable (just provide liquidity). A MULTI-leg maker edge needs ALL legs to fill as maker at
#       once — that is LEGGING RISK, not a lock, so a multi-leg maker-only candidate is NOT confirmed by default.
# Sizing is honest: max_units = min over legs of (resting size at the touch / leg ratio); a leg with unknown size
# (book_summary-only, never order-book-enriched) → NO_SIZE (we never invent a size). PREMIUM candidates are never a
# lock → RISK_PREMIUM, is_real=False, with the hedging/capacity caveat. Propose-only; nothing here places an order.

from __future__ import annotations

from dataclasses import dataclass

from cosmu.options.fees import DeribitOptionFees
from cosmu.options.scanner import KIND_PREMIUM, Candidate, Leg

# Verdict classifications, most→least tradable:
RISKLESS_LOCK = "RISKLESS_LOCK"   # taker edge > 0 after fees — executable right now (rare; likely stale quote)
MAKER_ONLY = "MAKER_ONLY"         # only profitable resting on the touch (single-leg ok; multi-leg = legging risk)
RISK_PREMIUM = "RISK_PREMIUM"     # a premium harvest, not a lock — directional/hedged exposure
MIRAGE = "MIRAGE"                 # the edge is entirely inside the spread — dead after costs
NO_SIZE = "NO_SIZE"               # a leg has no resting size (not order-book-enriched) — cannot confirm a fill


@dataclass(frozen=True)
class FillVerdict:
    """The honest read on a candidate. Edges are USD PER ONE STRUCTURE UNIT, AFTER fees. `max_units` is how many
    complete structures the resting touch sizes support; `capacity_usd` = maker_edge_usd * max_units (0 when not
    fillable). `is_real` is the one bit a human acts on."""

    classification: str
    mid_edge_usd: float
    taker_edge_usd: float
    maker_edge_usd: float
    max_units: float
    n_legs: int
    is_real: bool
    note: str

    @property
    def capacity_usd(self) -> float:
        if self.maker_edge_usd <= 0 or self.max_units <= 0:
            return 0.0
        return self.maker_edge_usd * self.max_units


class FillabilityModel:
    """Re-prices candidates at the executable touch. `min_units` is the smallest fill worth confirming (in
    structures); `min_edge_usd` is the per-unit edge floor after fees (an edge a hair of rounding could erase is
    not real). `allow_legging` lets a MULTI-leg maker-only candidate count as real (default False — legging risk)."""

    def __init__(
        self,
        fees: DeribitOptionFees | None = None,
        *,
        min_units: float = 0.1,
        min_edge_usd: float = 1.0,
        allow_legging: bool = False,
    ) -> None:
        self.fees = fees or DeribitOptionFees()
        self.min_units = min_units
        self.min_edge_usd = min_edge_usd
        self.allow_legging = allow_legging

    @staticmethod
    def _half_spread_usd(cand: Candidate, index_price: float) -> float | None:
        """Σ over legs of (ask−bid)/2 · ratio, converted coin→USD. This is the cost a taker pays / a maker earns to
        move from mid to the touch on the whole structure. None if ANY leg is one-sided (no honest spread)."""
        total = 0.0
        for leg in cand.legs:
            q = leg.quote
            if q.bid_price is None or q.ask_price is None:
                return None
            total += (q.ask_price - q.bid_price) / 2.0 * leg.ratio
        return total * index_price

    def _fees_usd(self, cand: Candidate, index_price: float, *, maker: bool) -> float:
        """Σ trade fee over legs, priced at each leg's fill price for the regime (BUY fills at ask taker / bid maker;
        SELL at bid taker / ask maker). The fill price drives the 12.5% premium cap. Maker==taker on Deribit options
        — `maker` only changes which price feeds the cap, never the rate."""
        total = 0.0
        for leg in cand.legs:
            q = leg.quote
            if maker:
                px = q.bid_price if leg.is_buy else q.ask_price
            else:
                px = q.ask_price if leg.is_buy else q.bid_price
            total += self.fees.trade_fee_usd(index_price, px, leg.ratio, is_maker=maker)
        return total

    @staticmethod
    def _leg_fill_size(leg: Leg, *, maker: bool) -> float | None:
        """Resting SIZE (contracts) to fill `leg` under the regime. TAKER consumes the opposite touch (buy lifts the
        ask → ask_size; sell hits the bid → bid_size). MAKER joins the favorable touch (buy rests on the bid →
        bid_size; sell rests on the ask → ask_size). None if not order-book-enriched (unknown size)."""
        q = leg.quote
        if maker:
            return q.bid_size if leg.is_buy else q.ask_size
        return q.ask_size if leg.is_buy else q.bid_size

    def _max_units(self, cand: Candidate, *, maker: bool) -> float | None:
        """Complete structures the touch sizes support = min over legs of (size / ratio). None if ANY leg has
        unknown size (book never enriched) — we never invent a size."""
        best: float | None = None
        for leg in cand.legs:
            size = self._leg_fill_size(leg, maker=maker)
            if size is None:
                return None
            units = size / leg.ratio if leg.ratio else 0.0
            best = units if best is None else min(best, units)
        return best if best is not None else 0.0

    def assess(self, cand: Candidate, index_price: float) -> FillVerdict:
        """Classify `cand`. `index_price` is the snapshot's underlying USD index (0 → can't value → MIRAGE)."""
        n = len(cand.legs)
        mid = cand.mid_edge_usd

        # A premium harvest is never an arb lock — report the maker take, but it stays directional/hedged.
        if cand.kind == KIND_PREMIUM:
            half = self._half_spread_usd(cand, index_price) or 0.0
            maker_edge = mid + half - self._fees_usd(cand, index_price, maker=True) if index_price > 0 else 0.0
            return FillVerdict(
                RISK_PREMIUM, mid, 0.0, maker_edge, self._max_units(cand, maker=True) or 0.0, n, False,
                "risk premium, NOT a lock — collecting it means carrying delta/vega you must hedge continuously; "
                "capacity sits in the arbed ATM majors. Route to a vol strategy, not the arb book.",
            )

        if index_price <= 0:
            return FillVerdict(MIRAGE, mid, 0.0, 0.0, 0.0, n, False,
                               "no underlying index on the snapshot — cannot value the structure in USD.")

        half = self._half_spread_usd(cand, index_price)
        if half is None:
            return FillVerdict(MIRAGE, mid, 0.0, 0.0, 0.0, n, False,
                               "a leg is one-sided (no two-way market) — not executable as a structure.")

        taker_edge = mid - half - self._fees_usd(cand, index_price, maker=False)
        maker_edge = mid + half - self._fees_usd(cand, index_price, maker=True)
        taker_units = self._max_units(cand, maker=False)
        maker_units = self._max_units(cand, maker=True)

        # Can't size a leg → cannot honestly confirm a fill (book_summary-only, never order-book-enriched).
        if taker_units is None or maker_units is None:
            return FillVerdict(
                NO_SIZE, mid, taker_edge, maker_edge, 0.0, n, False,
                "a leg has no resting size (not order-book-enriched) — enrich_with_order_book before trusting it.",
            )

        # TAKER lock — executable this instant. Real, but almost always a stale quote about to vanish.
        if taker_edge >= self.min_edge_usd and taker_units >= self.min_units:
            return FillVerdict(
                RISKLESS_LOCK, mid, taker_edge, maker_edge, taker_units, n, True,
                f"crossable NOW for ${taker_edge:.2f}/unit on {taker_units:.2f} units — verify it is not a stale quote.",
            )

        # MAKER-only — profitable only by resting on the touch.
        if maker_edge >= self.min_edge_usd and maker_units >= self.min_units:
            if n <= 1 or self.allow_legging:
                note = (f"rest for ${maker_edge:.2f}/unit on ~{maker_units:.2f} units; taker is "
                        f"${taker_edge:.2f} (you must NOT cross).")
                if n > 1:
                    note += " MULTI-leg: needs all legs to fill as maker — real legging risk even when allowed."
                return FillVerdict(MAKER_ONLY, mid, taker_edge, maker_edge, maker_units, n, True, note)
            return FillVerdict(
                MAKER_ONLY, mid, taker_edge, maker_edge, maker_units, n, False,
                f"maker edge ${maker_edge:.2f}/unit exists but needs {n} simultaneous maker fills — legging risk, "
                "not confirmed (set allow_legging to surface it).",
            )

        # Otherwise the whole 'edge' lived inside the spread.
        return FillVerdict(
            MIRAGE, mid, taker_edge, maker_edge, max(maker_units, 0.0), n, False,
            f"mid edge ${mid:.2f}/unit collapses across the spread (maker ${maker_edge:.2f}, taker ${taker_edge:.2f}) "
            "— a mirage after costs.",
        )
