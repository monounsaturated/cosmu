# intent: three example "campers" demonstrating the spectrum the framework must hold — each watches ONE class of
# inefficiency on a logged ChainSnapshot, emits CANDIDATEs at MID, and leaves the executability verdict entirely to
# the FillabilityModel. They are deliberately distinct in NATURE so the README's honesty argument is concrete:
#   - PutCallParityCamper  (ARB)     — a static no-arb that needs a FUTURE hedge leg (the option spread is the wall).
#   - VerticalArbCamper    (ARB)     — a PURE-options static no-arb (monotonicity + vertical-spread bound); needs no
#                                      underlying leg, so it is the cleanest "if it filled it would be riskless".
#   - VolRiskPremiumCamper (PREMIUM) — IV-vs-RV: NOT an arb at all, a risk premium you must hedge; included to show
#                                      the framework classifies a premium harvest differently from a lock.
# All prices are COIN; ×index → USD. Edges are valued at MID (the optimistic number); the spread/fees/size haircut
# is the FillabilityModel's job. Strikes are USD. Discounting is approximated DF≈1 (short crypto tenors, ~0 rates) —
# documented, and immaterial because fillability, not the carry model, is what kills these. Pure; no network.

from __future__ import annotations

from collections import defaultdict
from datetime import date

from cosmu.options.chain import ChainSnapshot, OptionQuote
from cosmu.options.scanner import KIND_ARB, KIND_PREMIUM, Candidate, Leg


def _two_sided(snapshot: ChainSnapshot) -> list[OptionQuote]:
    return [q for q in snapshot.quotes if q.is_two_sided and q.mid_price is not None]


class PutCallParityCamper:
    """Put-call parity (conversion/reversal). For a (expiry, strike) with BOTH a call and a put quoted, European
    parity says C − P = DF·(F − K) in USD, where F is the forward (Deribit's per-instrument `underlying_price`) and
    DF≈1. A residual means the option pair (the SYNTHETIC forward) is mispriced vs the real forward. The arb needs a
    FUTURE leg to hedge — but the binding cost is the OPTION spread (futures are tight), which is exactly what
    fillability tests on the two option legs. `min_mid_edge_usd` floors the residual we bother emitting."""

    name = "put_call_parity"
    kind = KIND_ARB

    def __init__(self, *, min_mid_edge_usd: float = 1.0) -> None:
        self.min_mid_edge_usd = min_mid_edge_usd

    def scan(self, snapshot: ChainSnapshot, *, context: dict | None = None) -> list[Candidate]:
        s = snapshot.index_price
        if not s or s <= 0:
            return []
        pairs: dict[tuple[date, float], dict[bool, OptionQuote]] = defaultdict(dict)
        for q in _two_sided(snapshot):
            pairs[(q.expiry, q.strike)][q.is_call] = q
        out: list[Candidate] = []
        for (expiry, strike), legs_by_call in pairs.items():
            call = legs_by_call.get(True)
            put = legs_by_call.get(False)
            if call is None or put is None:
                continue
            forward = call.underlying_price or put.underlying_price or s
            residual = (call.mid_price - put.mid_price) * s - (forward - strike)  # type: ignore[operator]
            if abs(residual) < self.min_mid_edge_usd:
                continue
            if residual > 0:  # call rich vs put → sell the synthetic (SELL call, BUY put), hedge by BUYing the future
                legs = (Leg(call, "SELL"), Leg(put, "BUY"))
                hedge = "BUY future"
            else:  # call cheap vs put → BUY call, SELL put, hedge by SELLing the future
                legs = (Leg(call, "BUY"), Leg(put, "SELL"))
                hedge = "SELL future"
            out.append(
                Candidate(
                    camper=self.name,
                    kind=self.kind,
                    description=(f"{snapshot.currency} {expiry:%d%b%y} {strike:g} parity residual "
                                 f"${residual:+.2f} (needs {hedge} @ {forward:.0f})"),
                    legs=legs,
                    mid_edge_usd=abs(residual),
                    detail={
                        "expiry": expiry.isoformat(), "strike": strike, "forward_usd": forward,
                        "residual_usd": residual, "requires_future_hedge": hedge,
                        "call": call.instrument, "put": put.instrument,
                    },
                )
            )
        return out


class VerticalArbCamper:
    """Pure-options static no-arb across adjacent strikes of the SAME expiry & type. Two violations per side:
      (A) MONOTONICITY: a call must be non-increasing in strike (a put non-decreasing). If C(K_hi) > C(K_lo) you
          BUY the cheaper-strike call and SELL the dearer higher-strike call for a CREDIT whose payoff is always
          ≥ 0 — free money. (B) SPREAD BOUND: a vertical spread cannot cost more than its max payoff (K_hi−K_lo).
          If C(K_lo)−C(K_hi) exceeds it, SELL the spread for more than it can ever pay out.
    No underlying leg is needed (self-contained), so a confirmed fill here is a true riskless lock. Edges at MID."""

    name = "vertical_arb"
    kind = KIND_ARB

    def __init__(self, *, min_mid_edge_usd: float = 1.0) -> None:
        self.min_mid_edge_usd = min_mid_edge_usd

    def scan(self, snapshot: ChainSnapshot, *, context: dict | None = None) -> list[Candidate]:
        s = snapshot.index_price
        if not s or s <= 0:
            return []
        groups: dict[tuple[date, bool], list[OptionQuote]] = defaultdict(list)
        for q in _two_sided(snapshot):
            groups[(q.expiry, q.is_call)].append(q)
        out: list[Candidate] = []
        for (expiry, is_call), quotes in groups.items():
            quotes.sort(key=lambda q: q.strike)
            for lo, hi in zip(quotes, quotes[1:], strict=False):
                if hi.strike <= lo.strike:
                    continue
                width = hi.strike - lo.strike  # USD, the spread's max payoff
                cand = (self._call_arb(snapshot, expiry, lo, hi, width, s)
                        if is_call else self._put_arb(snapshot, expiry, lo, hi, width, s))
                if cand is not None:
                    out.append(cand)
        return out

    def _emit(self, snapshot, expiry, kind_s, lo, hi, legs, edge_usd, detail) -> Candidate | None:
        if edge_usd < self.min_mid_edge_usd:
            return None
        return Candidate(
            camper=self.name, kind=self.kind,
            description=(f"{snapshot.currency} {expiry:%d%b%y} {kind_s} {lo.strike:g}/{hi.strike:g} "
                        f"vertical arb ${edge_usd:.2f}"),
            legs=legs, mid_edge_usd=edge_usd, detail=detail,
        )

    def _call_arb(self, snapshot, expiry, lo, hi, width, s) -> Candidate | None:
        c_lo, c_hi = lo.mid_price, hi.mid_price
        if c_hi > c_lo:  # (A) higher strike call dearer → credit + non-negative payoff
            edge = (c_hi - c_lo) * s
            legs = (Leg(lo, "BUY"), Leg(hi, "SELL"))
            return self._emit(snapshot, expiry, "C", lo, hi, legs, edge,
                              {"type": "monotonicity", "lo": lo.instrument, "hi": hi.instrument})
        spread_cost_usd = (c_lo - c_hi) * s
        if spread_cost_usd > width:  # (B) spread costs more than it can ever pay → sell it
            edge = spread_cost_usd - width
            legs = (Leg(lo, "SELL"), Leg(hi, "BUY"))
            return self._emit(snapshot, expiry, "C", lo, hi, legs, edge,
                              {"type": "spread_bound", "width_usd": width, "lo": lo.instrument, "hi": hi.instrument})
        return None

    def _put_arb(self, snapshot, expiry, lo, hi, width, s) -> Candidate | None:
        p_lo, p_hi = lo.mid_price, hi.mid_price
        if p_lo > p_hi:  # (A) lower strike put dearer → credit + non-negative payoff
            edge = (p_lo - p_hi) * s
            legs = (Leg(hi, "BUY"), Leg(lo, "SELL"))
            return self._emit(snapshot, expiry, "P", lo, hi, legs, edge,
                              {"type": "monotonicity", "lo": lo.instrument, "hi": hi.instrument})
        spread_cost_usd = (p_hi - p_lo) * s
        if spread_cost_usd > width:  # (B) bear put spread costs more than it can pay → sell it
            edge = spread_cost_usd - width
            legs = (Leg(hi, "SELL"), Leg(lo, "BUY"))
            return self._emit(snapshot, expiry, "P", lo, hi, legs, edge,
                              {"type": "spread_bound", "width_usd": width, "lo": lo.instrument, "hi": hi.instrument})
        return None


class VolRiskPremiumCamper:
    """IV-vs-RV — the implied/realized vol-risk premium. NOT an arbitrage: when an option's mark_iv sits well above
    realized vol you can SELL it to collect the premium, but you then carry delta/vega you must hedge — capacity
    sits in the (arbed) ATM majors and the 'edge' is a risk premium, not a lock. Emits a single SELL leg on the
    nearest-ATM two-sided option per expiry whose mark_iv exceeds realized vol by `min_vrp_points`. Realized vol
    (annualized %) is read from `context['realized_vol']`; with no context it emits nothing (no RV → no signal)."""

    name = "vol_risk_premium"
    kind = KIND_PREMIUM

    def __init__(self, *, min_vrp_points: float = 5.0) -> None:
        self.min_vrp_points = min_vrp_points

    def scan(self, snapshot: ChainSnapshot, *, context: dict | None = None) -> list[Candidate]:
        s = snapshot.index_price
        rv = (context or {}).get("realized_vol")
        if not s or s <= 0 or not isinstance(rv, (int, float)):
            return []
        nearest: dict[date, OptionQuote] = {}
        for q in _two_sided(snapshot):
            if q.mark_iv is None:
                continue
            cur = nearest.get(q.expiry)
            if cur is None or abs(q.strike - s) < abs(cur.strike - s):
                nearest[q.expiry] = q
        out: list[Candidate] = []
        for expiry, q in nearest.items():
            vrp = q.mark_iv - float(rv)  # type: ignore[operator]
            if vrp < self.min_vrp_points:
                continue
            premium_usd = q.mid_price * s  # type: ignore[operator]
            out.append(
                Candidate(
                    camper=self.name, kind=self.kind,
                    description=(f"{snapshot.currency} {expiry:%d%b%y} {q.strike:g}{'C' if q.is_call else 'P'} "
                                 f"IV {q.mark_iv:.1f} vs RV {float(rv):.1f} (+{vrp:.1f} vol pts) — sell vol"),
                    legs=(Leg(q, "SELL"),),
                    mid_edge_usd=premium_usd,
                    detail={"expiry": expiry.isoformat(), "strike": q.strike, "mark_iv": q.mark_iv,
                            "realized_vol": float(rv), "vrp_points": vrp, "instrument": q.instrument},
                )
            )
        return out


def default_campers() -> list:
    """The example camper set the scanner ships with — two static-arb campers + one premium camper."""
    return [PutCallParityCamper(), VerticalArbCamper(), VolRiskPremiumCamper()]
