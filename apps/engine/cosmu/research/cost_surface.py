# intent: answer "does this strategy still HOLD across fees / venues / asset types?" by sweeping a compiled
# strategy over a scenario grid {fee_bps incl. 0, venue, asset_type, optional slippage/impact} and re-running
# the EXISTING pure backtest per cell. inputs: a gate-ready spec + its fitted params, real bars, a scenario
# grid; outputs: a CostSurface of per-cell {net_return, gross_return, cost_ratio, breakeven_edge_bps, holds}.
# invariants: ZERO edits to the backtest — run_strategy_backtest is imported read-only and called per cell;
# the fee-free FRICTION-LESS run is the gross baseline (computed once, shared); "holds" is the GROUND TRUTH
# from the net backtest (a fee-free-profitable edge that stays net-positive under that cell's real cost), and
# breakeven_edge_bps is a documented per-trade model estimate, never a substitute for the net run; pure and
# deterministic for fixed inputs (no network, no clock, no LLM).

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from cosmu.data.backtest import run_strategy_backtest
from cosmu.data.market import Bar
from cosmu.strategy.compiler import compile_spec
from cosmu.strategy.spec import StrategySpec

# Asset types this surface labels. NOTE: run_strategy_backtest has no `asset_type` parameter — perp behaviour
# (short leg, funding accrual) is driven by the SPEC (spec.direction / spec.funding_feature) and the PIT
# `alt_by_symbol` funding join, not by a per-cell flag. So asset_type here is a LABEL dimension that records
# which market structure the cell describes; the caller supplies a perp spec + funding alt-data to actually
# price the funding leg.
# TODO(backtest): run_strategy_backtest takes no `asset_type`/`venue` argument — fees are the only per-venue
# lever we can vary per cell today. If a dedicated perp/spot execution flag is ever needed, add it to
# run_strategy_backtest (data/backtest.py) rather than faking it here. (Collision guard: do NOT edit it now.)
ASSET_TYPES = ("spot", "perp")


@dataclass(frozen=True)
class CostScenario:
    """One cell of the cost surface: the real cost assumptions to price the strategy under."""

    fee_bps: Decimal              # per-side taker fee (0 == the fee-free axis point)
    venue: str                    # venue id this cost schedule belongs to (label + provenance)
    asset_type: str               # "spot" | "perp" (label; see module note — not a backtest arg)
    slippage_bps: Decimal = Decimal("5")   # fixed half-spread fed to the backtest
    impact_bps: Decimal = Decimal("50")    # size-aware market-impact coefficient fed to the backtest

    def cost_key(self) -> tuple[str, str, str]:
        """The (fee, slippage, impact) triple that actually changes the backtest — used to memoize runs so two
        cells with identical costs (e.g. same fee at two label-only-different venues) share one backtest."""
        return (str(self.fee_bps), str(self.slippage_bps), str(self.impact_bps))


@dataclass(frozen=True)
class CostCell:
    """Per-cell verdict: did the edge survive THIS cell's real cost?"""

    scenario: CostScenario
    net_return: float          # validation return under the cell's fee + slippage + impact
    gross_return: float        # the shared friction-free baseline edge (fee=slip=impact=0)
    cost_ratio: float          # net_edge / gross_edge, clamped to [0, 1] for display
    breakeven_edge_bps: float  # round-trip fee (bps) the avg trade can absorb before net edge → 0 (model est.)
    num_trades: int
    holds: bool                # ground truth: gross edge existed AND it stays net-positive in this cell


@dataclass(frozen=True)
class CostSurface:
    """The full sweep for one compiled strategy."""

    strategy_name: str
    strategy_hash: str | None    # compile_spec hash for provenance; None if the spec did not compile
    gross_return: float          # the friction-free baseline edge, shared across every cell
    cells: list[CostCell] = field(default_factory=list)

    def holds_everywhere(self) -> bool:
        """True iff the edge survives EVERY cell — the strongest 'this strategy is venue/fee-robust' answer."""
        return bool(self.cells) and all(cell.holds for cell in self.cells)

    def surviving_venues(self) -> list[str]:
        """Venues where the edge holds in at least one cell (de-duplicated, first-seen order)."""
        seen: list[str] = []
        for cell in self.cells:
            if cell.holds and cell.scenario.venue not in seen:
                seen.append(cell.scenario.venue)
        return seen

    def by_venue(self) -> dict[str, list[CostCell]]:
        out: dict[str, list[CostCell]] = {}
        for cell in self.cells:
            out.setdefault(cell.scenario.venue, []).append(cell)
        return out


def compute_cost_surface(
    spec: StrategySpec,
    params: dict[str, float],
    market: dict[str, list[Bar]],
    scenarios: Sequence[CostScenario],
    *,
    alt_by_symbol: dict[str, dict[str, dict[str, float]]] | None = None,
) -> CostSurface:
    """Sweep a compiled strategy (a validated spec + its fitted `params`, as produced by compile_spec) over a
    cost-scenario grid and report, per cell, whether the edge still holds.

    For each cell the EXISTING pure backtest is re-run with that cell's fee/slippage/impact. The fee-free,
    friction-less run (fee=slippage=impact=0) is the GROSS baseline — the theoretical edge before any cost —
    computed once and shared. `cost_ratio = net_edge / gross_edge` is the fraction of that edge surviving the
    cell's real cost; `holds` is the ground-truth answer to "does this strategy still hold here?" — the gross
    edge existed (gross_return > 0) AND the net return stays positive under the cell's cost.

    `alt_by_symbol` is threaded straight through to run_strategy_backtest unchanged (the PIT funding/alt join),
    so a perp/carry spec is priced with its funding leg exactly as the gate would.
    """

    # Memoize by the cost triple that actually changes a run, so duplicate (fee, slip, impact) scenarios —
    # e.g. the same fee labelled under spot and perp — cost one backtest, not two.
    cache: dict[tuple[str, str, str], tuple[float, int]] = {}

    def _run(fee_bps: Decimal, slippage_bps: Decimal, impact_bps: Decimal) -> tuple[float, int]:
        key = (str(fee_bps), str(slippage_bps), str(impact_bps))
        if key not in cache:
            metrics = run_strategy_backtest(
                spec,
                params,
                market,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                impact_bps=impact_bps,
                alt_by_symbol=alt_by_symbol,
            )
            cache[key] = (float(metrics.oos_return), int(metrics.num_trades))
        return cache[key]

    # Gross = the fee-free, friction-less baseline edge. Same signals, zero transaction cost.
    gross_return, gross_trades = _run(Decimal("0"), Decimal("0"), Decimal("0"))
    breakeven = _breakeven_edge_bps(gross_return, gross_trades)

    cells: list[CostCell] = []
    for scenario in scenarios:
        net_return, num_trades = _run(scenario.fee_bps, scenario.slippage_bps, scenario.impact_bps)
        cells.append(
            CostCell(
                scenario=scenario,
                net_return=round(net_return, 8),
                gross_return=round(gross_return, 8),
                cost_ratio=_cost_ratio(net_return, gross_return),
                breakeven_edge_bps=round(breakeven, 4),
                num_trades=num_trades,
                holds=gross_return > 0.0 and net_return > 0.0,
            )
        )

    return CostSurface(
        strategy_name=spec.name,
        strategy_hash=_safe_hash(spec, params),
        gross_return=round(gross_return, 8),
        cells=cells,
    )


# --------------------------------------------------------------------------- scenario-grid builders


def scenario_grid(
    *,
    fee_bps: Sequence[Decimal],
    venues: Sequence[str],
    asset_types: Sequence[str] = ("spot",),
    slippage_bps: Decimal = Decimal("5"),
    impact_bps: Decimal = Decimal("50"),
) -> list[CostScenario]:
    """The full cartesian {fee_bps × venue × asset_type} grid at a fixed slippage/impact. Include 0 in
    `fee_bps` to pin the fee-free axis point. Slippage/impact are held constant here so each row isolates the
    fee/venue/asset effect; sweep them by calling this more than once or building CostScenarios directly."""
    for asset_type in asset_types:
        if asset_type not in ASSET_TYPES:
            raise ValueError(f"unknown asset_type {asset_type!r}; expected one of {ASSET_TYPES}")
    grid: list[CostScenario] = []
    for venue in venues:
        for asset_type in asset_types:
            for fee in fee_bps:
                grid.append(
                    CostScenario(
                        fee_bps=Decimal(str(fee)),
                        venue=venue,
                        asset_type=asset_type,
                        slippage_bps=Decimal(str(slippage_bps)),
                        impact_bps=Decimal(str(impact_bps)),
                    )
                )
    return grid


def venue_fee_scenarios(
    venues: Sequence[str],
    *,
    catalog=None,  # noqa: ANN001 — VenueCatalog; default-imported lazily to keep this module import-light
    volume_30d_usd: Decimal = Decimal("0"),
    asset_types: Sequence[str] = ("spot",),
    slippage_bps: Decimal = Decimal("5"),
    impact_bps: Decimal = Decimal("50"),
    include_fee_free: bool = True,
) -> list[CostScenario]:
    """One scenario per venue priced at that venue's REAL taker fee (the effective tier for `volume_30d_usd`),
    plus an optional fee-free baseline cell per venue. This is what makes cross-venue ordering honest — Binance
    (10 bps) vs Kraken (26 bps) vs Coinbase (60 bps) are the actual fee walls, not a paper assumption."""
    if catalog is None:
        from cosmu.spine.venue import default_catalog

        catalog = default_catalog()
    grid: list[CostScenario] = []
    for venue_id in venues:
        _, taker = catalog.venue(venue_id).effective_fee(volume_30d_usd)
        for asset_type in asset_types:
            fees = [Decimal("0"), taker] if include_fee_free else [taker]
            for fee in fees:
                grid.append(
                    CostScenario(
                        fee_bps=fee,
                        venue=venue_id,
                        asset_type=asset_type,
                        slippage_bps=Decimal(str(slippage_bps)),
                        impact_bps=Decimal(str(impact_bps)),
                    )
                )
    return grid


# --------------------------------------------------------------------------- internals


def _cost_ratio(net_return: float, gross_return: float) -> float:
    """net_edge / gross_edge in [0, 1] for display. 1.0 when costs cost nothing; 0.0 when the edge is fully
    eaten (or turned negative). Undefined gross (<= 0) → 0.0 (there was no edge to keep)."""
    if gross_return <= 0.0:
        return 0.0
    return round(max(0.0, min(1.0, net_return / gross_return)), 6)


def _breakeven_edge_bps(gross_return: float, num_trades: int) -> float:
    """The round-trip fee (in bps) the AVERAGE trade can absorb before the net edge reaches zero — a model
    estimate, not a backtest. Model: the friction-free edge compounds as exp(num_trades * g) - 1, so the
    per-trade log edge is g = ln(1 + gross_return) / num_trades; a round trip pays roughly that same fraction
    in fees at breakeven. Expressed in bps: g * 1e4. Zero when there is no edge or no trades. `holds` (from the
    net run) remains the ground truth; this is the headline 'cost budget' for reading the surface."""
    if num_trades <= 0 or gross_return <= 0.0:
        return 0.0
    per_trade_log_edge = math.log1p(gross_return) / num_trades
    return per_trade_log_edge * 1e4


def _safe_hash(spec: StrategySpec, params: dict[str, float]) -> str | None:
    """Best-effort compile hash for provenance. compile_spec validates the spec (no magic numbers, all params
    present) and would raise on an un-gate-ready spec; the surface is still useful without a hash, so a failed
    compile degrades to None rather than aborting the sweep."""
    try:
        return compile_spec(spec, params).code_hash
    except (ValueError, KeyError):
        return None
