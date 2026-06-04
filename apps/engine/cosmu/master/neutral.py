# intent: the TWO-LEG delta-neutral track (DERIVATIVES_PLAN P0.3, §6) — pair a LONG-SPOT leg with a SHORT-PERP
# leg held under ONE strategy_version_id, mark BOTH legs on real closes, and accrue perp funding into
# Position.funding_accrued as cash P&L. inputs: the store's persisted positions (signed qty: long spot qty>0,
# short perp qty<0) + latest real marks + a point-in-time funding rate per perp leg; outputs: a marked neutral
# view per track (both legs' unrealized P&L + cumulative funding) and a funding-accrual event row. invariants:
# delta-neutral (the short perp hedges the long spot's beta) so the pair's P&L is funding-carry + basis, NOT
# direction; funding flows the carry way (short perp RECEIVES positive funding, long perp PAYS); SIM only — marks
# only, never an order; deterministic for a fixed store + marks + funding; NO schema change — funding_accrued is
# persisted on the existing events.payload JSON column and read back as the running total. The single-leg spot
# path is untouched: a track with no short-perp leg is simply not a neutral pair and is skipped here.

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal

from cosmu.knowledge.store import Store
from cosmu.master.portfolio import PositionView

# The event kind under which a perp leg's cumulative funding P&L is journaled (append-only, JSON payload — no
# schema change). The latest row for a (version_id, instrument_id) pair IS that leg's `funding_accrued`.
FUNDING_EVENT_KIND = "neutral_funding_accrued"


@dataclass(frozen=True)
class NeutralLeg:
    """One side of a delta-neutral pair, resolved from a persisted position. `is_perp` marks the funded/funding
    leg; `funding_accrued` is the running funding cash flow read back from the journal (zero on the spot leg)."""

    instrument_id: str
    symbol: str
    venue: str
    qty: Decimal            # signed: long spot > 0, short perp < 0
    avg_price: Decimal
    is_perp: bool
    funding_accrued: Decimal

    def unrealized_pnl(self, mark: Decimal) -> Decimal:
        """(mark - basis) * signed qty — correct for BOTH sides: a long (qty>0) gains as the mark rises, a short
        (qty<0) gains as it falls. The same expression the spot PositionView uses, now carrying the short sign."""
        return (mark - self.avg_price) * self.qty


@dataclass(frozen=True)
class NeutralTrack:
    """A paired long-spot / short-perp track, marked on real closes. `net_unrealized` is BOTH legs' price P&L
    (≈ basis move, the direction cancelling out by construction); `funding_accrued` is the carry the short perp
    has booked. The track's marked value contribution = net_unrealized + funding_accrued."""

    strategy_version_id: str
    spot: NeutralLeg
    perp: NeutralLeg

    def net_unrealized(self, marks: dict[str, Decimal]) -> Decimal:
        spot_mark = marks.get(self.spot.instrument_id, self.spot.avg_price)
        perp_mark = marks.get(self.perp.instrument_id, self.perp.avg_price)
        return self.spot.unrealized_pnl(spot_mark) + self.perp.unrealized_pnl(perp_mark)

    @property
    def funding_accrued(self) -> Decimal:
        return self.perp.funding_accrued

    def marked_value(self, marks: dict[str, Decimal]) -> Decimal:
        """The pair's total marked contribution: price P&L on both legs + the perp's accrued funding carry."""
        return self.net_unrealized(marks) + self.funding_accrued


def _funding_accrued(store: Store, version_id: str, instrument_id: str) -> Decimal:
    """Read back the latest journaled cumulative funding for a perp leg (the existing events.payload column —
    no schema change). Absent journal => zero (a freshly opened leg has accrued nothing)."""
    row = store.row(
        "SELECT payload FROM events WHERE kind = ? AND ref_type = 'neutral_leg' AND ref_id = ? ORDER BY id DESC LIMIT 1",
        (FUNDING_EVENT_KIND, _leg_ref(version_id, instrument_id)),
    )
    if not row:
        return Decimal("0")
    payload = row["payload"]
    data = json.loads(payload) if isinstance(payload, str) else payload
    return Decimal(str(data.get("funding_accrued", "0")))


def _leg_ref(version_id: str, instrument_id: str) -> str:
    return f"{version_id}:{instrument_id}"


def neutral_tracks(
    store: Store,
    positions: list[PositionView],
) -> list[NeutralTrack]:
    """Pair each track's positions into a delta-neutral (long-spot, short-perp) track.

    A track qualifies as NEUTRAL iff, under one strategy_version_id, it holds exactly one long leg (qty>0) AND
    one short leg (qty<0). By the carry construction (DERIVATIVES_PLAN §6) the long leg is the spot bag and the
    short leg is the perp hedge — the funding-bearing side. Single-leg spot tracks (the prior behaviour) have one
    long leg and no short leg, so they never match here — the spot mark path in portfolio.mark_to_market still
    owns them, untouched. Pairing is DERIVED from the persisted signed quantities, so no extra schema is needed to
    remember the pairing (the venue catalog's Instrument has no product_type to key off; the sign IS the marker)."""
    by_track: dict[str, list[PositionView]] = {}
    for p in positions:
        if p.strategy_version_id is None or p.qty == 0:
            continue
        by_track.setdefault(p.strategy_version_id, []).append(p)

    out: list[NeutralTrack] = []
    for version_id, legs in by_track.items():
        longs = [p for p in legs if p.qty > 0]
        shorts = [p for p in legs if p.qty < 0]
        if len(longs) != 1 or len(shorts) != 1:
            continue  # not a clean two-leg pair — leave it to the single-leg path
        spot_pos, perp_pos = longs[0], shorts[0]
        out.append(
            NeutralTrack(
                strategy_version_id=version_id,
                spot=NeutralLeg(
                    instrument_id=spot_pos.instrument_id, symbol=spot_pos.symbol, venue=spot_pos.venue,
                    qty=spot_pos.qty, avg_price=spot_pos.avg_price, is_perp=False, funding_accrued=Decimal("0"),
                ),
                perp=NeutralLeg(
                    instrument_id=perp_pos.instrument_id, symbol=perp_pos.symbol, venue=perp_pos.venue,
                    qty=perp_pos.qty, avg_price=perp_pos.avg_price, is_perp=True,
                    funding_accrued=_funding_accrued(store, version_id, perp_pos.instrument_id),
                ),
            )
        )
    return out


def accrue_funding(
    store: Store,
    track: NeutralTrack,
    *,
    funding_rate: Decimal,
    perp_mark: Decimal,
) -> Decimal:
    """Accrue ONE funding period on the short-perp leg and journal the new cumulative total (events.payload — no
    schema change). Returns the updated cumulative funding.

    Sign: funding flow on a perp position = `-sign(qty) * rate * notional` (the SAME convention as the backtest's
    `-d * rate * notional`). For our SHORT perp (qty<0) and a POSITIVE rate this is +flow — the short RECEIVES the
    carry; a negative rate flips it to a cost. notional uses the current perp mark (the venue charges funding on
    live notional, not entry basis). A zero rate accrues nothing — a true no-op, so an inert funding feed never
    perturbs the marked value."""
    if funding_rate == 0 or track.perp.qty == 0 or perp_mark <= 0:
        return track.perp.funding_accrued
    sign = Decimal("1") if track.perp.qty > 0 else Decimal("-1")
    notional = abs(track.perp.qty) * perp_mark
    flow = -sign * funding_rate * notional
    new_total = track.perp.funding_accrued + flow
    store.append_event(
        actor="master",
        kind=FUNDING_EVENT_KIND,
        ref_type="neutral_leg",
        ref_id=_leg_ref(track.strategy_version_id, track.perp.instrument_id),
        payload={
            "strategy_version_id": track.strategy_version_id,
            "instrument_id": track.perp.instrument_id,
            "funding_rate": str(funding_rate),
            "flow": str(flow.quantize(Decimal("0.00000001"))),
            "funding_accrued": str(new_total.quantize(Decimal("0.00000001"))),
        },
    )
    return new_total
