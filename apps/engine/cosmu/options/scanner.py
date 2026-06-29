# intent: the "camper" framework — the lightweight skeleton where each camper watches ONE class of options
# inefficiency on a LOGGED ChainSnapshot and emits CANDIDATEs. A candidate is only a *mid-price* observation (the
# mirage number); it becomes a real opportunity ONLY after the FillabilityModel re-prices it at the executable
# touch with realistic MAKER fills + fees (fillability.py). This module owns the TYPES (Leg / Candidate / Camper /
# Opportunity) and the deterministic orchestrator run_scan(); it deliberately does NOT import fillability (the
# model is injected) so the dependency runs one-way and the framework stays a thin, reviewable seam. Propose-only:
# nothing here places an order or moves money — it surfaces candidates and an honest verdict for a human.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from cosmu.options.chain import ChainSnapshot, OptionQuote

if TYPE_CHECKING:  # avoid a module-level cycle — fillability imports our types, not the reverse
    from cosmu.options.fillability import FillabilityModel, FillVerdict

# A candidate's economic nature, which decides how fillability judges it:
KIND_ARB = "ARB"          # a static no-arbitrage violation — should be a riskless lock IF it fills
KIND_PREMIUM = "PREMIUM"  # a risk-premium harvest (e.g. sell rich IV) — directional/​hedged, NEVER a free lock


@dataclass(frozen=True)
class Leg:
    """One option leg of a candidate. `side` is BUY or SELL; `ratio` is how many contracts of THIS leg make up one
    unit of the structure (e.g. a butterfly body is 2). The quote carries the touch prices/sizes fillability needs."""

    quote: OptionQuote
    side: str  # "BUY" | "SELL"
    ratio: float = 1.0

    @property
    def is_buy(self) -> bool:
        return self.side == "BUY"


@dataclass(frozen=True)
class Candidate:
    """A camper's raw finding BEFORE fillability. `mid_edge_usd` is the edge valued at MID per one structure unit —
    the optimistic mirage. `legs` are the trades that would capture it. `detail` is camper-specific diagnostics."""

    camper: str
    kind: str  # KIND_ARB | KIND_PREMIUM
    description: str
    legs: tuple[Leg, ...]
    mid_edge_usd: float
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Opportunity:
    """A candidate joined to its fillability verdict — the unit a human reviews. `is_real` mirrors the verdict."""

    candidate: Candidate
    verdict: FillVerdict

    @property
    def is_real(self) -> bool:
        return self.verdict.is_real


class Camper(Protocol):
    """A camper watches ONE inefficiency class. `name` labels it; `kind` is KIND_ARB or KIND_PREMIUM. `scan` is
    PURE over the snapshot (+ optional context like realized vol) and returns candidates — never does fillability,
    never places an order."""

    name: str
    kind: str

    def scan(self, snapshot: ChainSnapshot, *, context: dict | None = None) -> list[Candidate]: ...


def run_scan(
    snapshot: ChainSnapshot,
    campers: list[Camper],
    fillability: FillabilityModel,
    *,
    context: dict | None = None,
    confirmed_only: bool = False,
) -> list[Opportunity]:
    """Run every camper over the snapshot, fill-check each candidate, and return Opportunities sorted by the most
    capturable maker edge first. Deterministic and side-effect-free. With `confirmed_only`, drop everything whose
    verdict is not `is_real` (the mirages) — the honest short-list. `index_price` for the USD valuation comes from
    the snapshot; a candidate on a chain with no index is judged NO_SIZE (can't value it)."""
    index = snapshot.index_price or 0.0
    out: list[Opportunity] = []
    for camper in campers:
        for cand in camper.scan(snapshot, context=context):
            verdict = fillability.assess(cand, index)
            if confirmed_only and not verdict.is_real:
                continue
            out.append(Opportunity(candidate=cand, verdict=verdict))
    out.sort(key=lambda o: o.verdict.capacity_usd, reverse=True)
    return out
