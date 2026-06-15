# intent: recompute a stored strategy-version's NET performance under several COST BASES — the friction-free
# baseline ("No fees") and each candidate venue's REAL fee + market depth — so the operator can pick the basis
# in the UI ("perf under venue-1 vs venue-2"). Reuses the EXISTING pure backtest via cost_surface (no new sim).
# inputs: a Store + version_id (+ optional venue list / injected market provider); outputs: a CostBasisReport of
# per-basis cells. invariants: read-only, deterministic for fixed bars, the friction-free run is the gross
# baseline, and an unloadable market (offline / asset class not wired) yields an HONEST available=False + reason
# — never a fabricated number. NO LLM; never funds or fires.

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal

from cosmu.data.alt_join import build_alt_by_symbol, resolve_alt_store
from cosmu.data.market import BinanceSpotOHLCVProvider, MarketDataProvider
from cosmu.data.universe import CORE_PERP_UNIVERSE
from cosmu.research.cost_surface import CostScenario, compute_cost_surface, venue_fee_scenarios
from cosmu.spine.venue import default_catalog
from cosmu.strategy.spec import StrategySpec


@dataclass(frozen=True)
class CostBasisItem:
    """One cost basis's verdict — the no-fee baseline or a venue's real fee+depth."""

    basis: str               # "none" | a venue id
    label: str               # display label
    venue_id: str | None     # None for the no-fee baseline
    fee_bps: float
    slippage_bps: float
    impact_bps: float
    net_return_pct: float
    cost_ratio: float
    num_trades: int
    holds: bool


@dataclass(frozen=True)
class CostBasisReport:
    version_id: str
    name: str
    available: bool
    reason: str | None
    gross_return_pct: float | None
    items: list[CostBasisItem]


def _unavailable(version_id: str, name: str, reason: str) -> CostBasisReport:
    return CostBasisReport(
        version_id=version_id, name=name, available=False, reason=reason, gross_return_pct=None, items=[]
    )


def _coerce(value: object) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _numeric_params(raw: object) -> dict[str, float]:
    """Keep only numeric params (drop carriers like `config_tag`); the backtest needs dict[str, float]."""
    out: dict[str, float] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        if isinstance(v, bool):
            continue
        try:
            out[str(k)] = float(v)
        except (TypeError, ValueError):
            continue
    return out


def _default_params(spec: StrategySpec) -> dict[str, float]:
    """Deterministic midpoint of each param range — an honest default when a version stored no fitted params,
    so the basis comparison can still run. Never a fabricated edge (the gate's verdict is unaffected)."""
    out: dict[str, float] = {}
    for name, ps in (spec.param_space or {}).items():
        try:
            lo = float(ps.lo)
            hi = float(ps.hi)
        except (TypeError, ValueError, AttributeError):
            continue
        mid = (lo + hi) / 2.0
        if getattr(ps, "kind", "float") == "int":
            mid = float(round(mid))
        out[name] = mid
    return out


def _crypto_market(spec: StrategySpec, provider: MarketDataProvider) -> dict[str, list]:
    """The canonical core-slice market the Finder screens crypto/binance specs on — offline-degrading (a symbol
    with no cached bars is skipped, never fabricated)."""
    limit = 1500 if spec.horizon.bar_size == "1h" else 1000
    market: dict[str, list] = {}
    for sym in CORE_PERP_UNIVERSE:
        try:
            bars = provider.fetch_bars(sym, spec.horizon.bar_size, limit=limit)
        except Exception:  # noqa: BLE001 — offline/no-network for one symbol: skip, never crash the request
            continue
        if bars:
            market[sym] = bars
    return market


def compute_version_cost_basis(
    store: object,
    version_id: str,
    *,
    settings: object | None = None,
    venues: list[str] | None = None,
    market_data: MarketDataProvider | None = None,
) -> CostBasisReport:
    """Recompute one stored version's net performance under each cost basis (No fees + each candidate venue's
    real fee+depth). Reuses the pure backtest via cost_surface; returns an honest available=False when the
    market can't be loaded (offline, or an asset class whose recompute isn't wired yet)."""
    row = store.row(
        "SELECT sv.id, sv.spec, sv.params, s.name FROM strategy_versions sv "
        "JOIN strategies s ON s.id = sv.strategy_id WHERE sv.id = ?",
        (version_id,),
    )
    if row is None:
        return _unavailable(version_id, "Unknown", "unknown strategy version")
    name = row["name"] or "Unknown"

    spec_raw = _coerce(row["spec"])
    if not isinstance(spec_raw, dict):
        return _unavailable(version_id, name, "spec is not available")
    try:
        spec = StrategySpec.model_validate(spec_raw)
    except Exception:  # noqa: BLE001 — a spec that no longer validates is honest-unavailable, not a crash
        return _unavailable(version_id, name, "spec did not validate")

    # Stored fitted params win; defaults backfill any gap so the backtest always has a complete param set.
    params = {**_default_params(spec), **_numeric_params(_coerce(row["params"]))}
    if not params:
        return _unavailable(version_id, name, "no parameters to recompute with")

    # Faithful market: crypto/binance specs re-screen on the canonical core slice (the Finder's path); other
    # asset classes aren't wired for on-demand recompute yet (honest, never faked).
    if "crypto" not in (spec.universe.asset_classes or []) or "binance" not in (spec.universe.venues or []):
        return _unavailable(version_id, name, "cost-basis recompute currently supports crypto/binance specs")
    provider = market_data or BinanceSpotOHLCVProvider()
    market = _crypto_market(spec, provider)
    if not market:
        return _unavailable(version_id, name, "no cached bars for this spec's universe (offline)")

    # PIT alt-data join so a leading-signal spec (funding/sentiment/…) is priced exactly as the gate would.
    try:
        alt = build_alt_by_symbol(resolve_alt_store(settings or _settings(), store), spec, market)
    except Exception:  # noqa: BLE001 — no alt store reachable → price/TA only, never a crashed request
        alt = None

    catalog = default_catalog()
    candidate = venues or list(spec.universe.venues) or ["binance"]
    known: list[str] = []
    for vid in candidate:
        try:
            catalog.venue(vid)
        except KeyError:
            continue
        if vid not in known:
            known.append(vid)
    if not known:
        known = ["binance"]

    # The no-fee baseline + one real fee+depth cell per candidate venue. compute_cost_surface memoizes by the
    # cost triple, so identical-cost venues share one backtest run.
    no_fee = CostScenario(
        fee_bps=Decimal("0"), venue="none", asset_type="spot", slippage_bps=Decimal("0"), impact_bps=Decimal("0")
    )
    scenarios = [no_fee, *venue_fee_scenarios(known, catalog=catalog, include_fee_free=False)]
    surface = compute_cost_surface(spec, params, market, scenarios, alt_by_symbol=alt)

    items: list[CostBasisItem] = []
    for cell in surface.cells:
        sc = cell.scenario
        is_none = sc.venue == "none"
        items.append(
            CostBasisItem(
                basis="none" if is_none else sc.venue,
                label="No fees" if is_none else catalog.venue(sc.venue).name,
                venue_id=None if is_none else sc.venue,
                fee_bps=float(sc.fee_bps),
                slippage_bps=float(sc.slippage_bps),
                impact_bps=float(sc.impact_bps),
                net_return_pct=round(cell.net_return * 100, 2),
                cost_ratio=cell.cost_ratio,
                num_trades=cell.num_trades,
                holds=cell.holds,
            )
        )

    return CostBasisReport(
        version_id=version_id,
        name=name,
        available=True,
        reason=None,
        gross_return_pct=round(surface.gross_return * 100, 2),
        items=items,
    )


def _settings() -> object:
    from cosmu.config.settings import get_settings

    return get_settings()
