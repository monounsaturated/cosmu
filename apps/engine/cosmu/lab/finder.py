# intent: the Strategy Finder — grid-search a spec's fittable param space into many Versions, run each through
# the DETERMINISTIC screen (data/backtest over REAL Binance spot bars, cached + offline-safe), register EVERY
# variant as a trial (deflation validity), rank by profit_factor AND the Gate, walk-forward/holdout-validate the
# leaders BEFORE promotion, and persist winners to a CONFIG LIBRARY (strategy_versions tagged origin='finder',
# config_tag in params). inputs: a seed StrategySpec + its param_space + a market provider + the store; outputs:
# a FinderReport + persisted Strategy/Version/backtest/track/survivor rows. invariants: the LLM is nowhere in
# this path; the deterministic scorer/gate alone decide survival + money; no top-of-leaderboard picking (every
# variant counts toward trial deflation and promotion needs WFO/holdout, not just the best in-sample PF); params
# come from the fitted space (no magic numbers); fully offline (degrades to cached bars); idempotent re-runs.

from __future__ import annotations

import hashlib
import itertools
import tempfile
from dataclasses import dataclass, field
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.alt_join import build_alt_by_symbol, resolve_alt_store
from cosmu.data.backtest import metrics_for_run, run_strategy_backtest_detailed
from cosmu.data.market import (
    Bar,
    BinanceSpotOHLCVProvider,
    EquityOHLCVProvider,
    HyperliquidOHLCVProvider,
    MarketDataProvider,
)
from cosmu.data.universe import PERP_UNIVERSE
from cosmu.evolution.loop import fit_params
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.experiments import KIND_FINDER, ExperimentRecord, data_version, log_experiments
from cosmu.knowledge.store import Store, Writer, tracks_has_cell_columns, utcnow
from cosmu.master.cohort import Candidate as CohortCandidate
from cosmu.master.cohort import promote_brut
from cosmu.master.holdout import HoldoutLedger
from cosmu.master.live_eligibility import cell_id
from cosmu.master.promotion import freeze_promotion
from cosmu.master.scorer import BacktestMetrics
from cosmu.master.screen_universe import build_cost_context, equity_symbols, hyperliquid_symbols
from cosmu.master.tracks import WATCH_VERDICT, is_near_miss_cell, open_paper_track
from cosmu.master.trade_floor import MIN_TRADES_PER_SYMBOL
from cosmu.ml.regime import proven_regimes
from cosmu.spine.universe import enabled_universe
from cosmu.spine.venue import default_catalog
from cosmu.strategy.compiler import compile_spec
from cosmu.strategy.spec import ParamSpace, StrategySpec

# How many points to sample per numeric param when building the grid. Coarse on purpose: the grid is a
# DISCOVERY pass, not a fine optimizer, and a bounded grid keeps the variant count (and trial count) sane.
_GRID_POINTS = 3
# Hard cap on variants so a high-dimensional space can't explode the run. Deterministic truncation.
_MAX_VARIANTS = 256
# Second pass: finer grid around the top survivors from the coarse pass. More points per param, narrower
# range (±15% around each survivor's values). The gate still protects against overfitting.
_REFINE_POINTS = 5
_REFINE_TOP_N = 5
_REFINE_RADIUS = 0.15
# The finder's crypto live screen — the full PERP_UNIVERSE (30 Binance USDⓈ-M perps). All 30 have 1d bars
# cached under .cosmu/market_data/binanceperp/. The five-symbol CORE slice was the prior value; widened
# 2026-06-16 once the cache confirmed full coverage.
_REAL_SYMBOLS = PERP_UNIVERSE
# BRUT per-cell trade floor: a tradeable cell (this variant × symbol × venue) must book at least this many of its
# OWN trades on its validation window to be judgeable at all. The locked gate's larger min_trades=30 floor is ALSO
# enforced per cell (on the cell's OWN num_trades) inside promote_brut — this 5 is the cheap thinness pre-screen.
# Single source of truth in master/trade_floor.py (shared with the autonomous loop).
_MIN_TRADES_PER_SYMBOL = MIN_TRADES_PER_SYMBOL
# The BRUT per-cell min-trades floor on the single combo's OWN trades — a cell with fewer than this of its own
# trades is too thin to score honestly (set as gates.min_trades for the brut promote path).
_BRUT_MIN_TRADES = 30


@dataclass(frozen=True)
class Variant:
    """One point in the grid: the parent spec + a concrete fitted param dict + a stable config tag."""

    params: dict[str, float]
    config_tag: str


@dataclass
class CellResult:
    """ONE brut cell (this algorithm-variant × one symbol × one venue), judged on its OWN streams. `metrics` is
    built by metrics_for_run from THIS symbol's per_symbol_run (own bar_returns + fold_returns) with the per-combo
    param-grid count baked into trials_counted; `passed` is the locked stats gate on those streams AND the per-cell
    trade floor — never a pooled or sibling-compared verdict. `holdout_passed` is this cell's OWN one-shot holdout
    confirmation (champion-only)."""

    symbol: str
    venue_id: str
    metrics: BacktestMetrics
    deflated_sharpe: float
    trades: int
    passed: bool
    reasons: list[str] = field(default_factory=list)
    holdout_passed: bool = False
    target_vol: float | None = None


@dataclass
class VariantResult:
    config_tag: str
    code_hash: str
    metrics: BacktestMetrics  # POOLED display metrics (the granular truth lives in `cells`); never the brut verdict
    deflated_sharpe: float
    profit_factor: float
    net_profit: float
    gate_passed: bool         # brut: True iff ANY cell of this variant passed (a variant is a config, cells are judged)
    reasons: list[str]
    fitted_params: dict[str, float] = field(default_factory=dict)
    version_id: str | None = None
    promoted: bool = False     # brut: True iff any cell promoted (== gate_passed; no FDR/cluster gating)
    holdout_passed: bool = False  # brut: True iff any promoted cell's own holdout confirmed
    target_vol: float | None = None  # T1 sizing anchor: set from champion.target_vol at champion holdout
    # Per-symbol breakdown {symbol: {return, sharpe, max_drawdown, trades}} from the detailed backtest — the
    # GRANULAR display truth. The BRUT verdict lives per-cell in `cells` (each judged on its OWN data); this stays
    # for the display rows + best_symbol.
    per_symbol: dict = field(default_factory=dict)
    # The BRUT per-cell verdicts: {symbol: CellResult}. Each cell is judged independently on its own streams — the
    # unit the funder fans out to a paper track. venue_id carried per cell (the fee axis of the S×A×V triple).
    cells: dict[str, CellResult] = field(default_factory=dict)


@dataclass
class FinderReport:
    strategy_name: str
    grid_size: int
    screened: int
    gate_passed: int
    promoted: int
    # Ranked by profit_factor (displayed secondary) within the gate-passers; promotion still uses the
    # deterministic Gate + FDR + WFO/holdout, never raw PF leaderboard order.
    leaderboard: list[VariantResult] = field(default_factory=list)
    survivors: list[VariantResult] = field(default_factory=list)


# --------------------------------------------------------------------------- grid construction


def _grid_values(ps: ParamSpace) -> list[float]:
    """The discrete sample points for one param. Choices enumerate verbatim; numeric ranges sample _GRID_POINTS
    evenly (ints rounded + de-duplicated). Endpoints included so the grid spans the whole fitted space."""
    if ps.kind == "choice" and ps.choices:
        return [float(c) for c in ps.choices]
    if ps.lo is None or ps.hi is None:
        return [0.0]
    lo, hi = float(ps.lo), float(ps.hi)
    if hi <= lo:
        return [lo]
    pts = [lo + (hi - lo) * i / (_GRID_POINTS - 1) for i in range(_GRID_POINTS)]
    if ps.kind == "int":
        pts = sorted({float(int(round(p))) for p in pts})
    else:
        pts = [round(p, 8) for p in pts]
    return pts


def _product_size(axes: list[list[float]]) -> int:
    n = 1
    for a in axes:
        n *= len(a)
    return n


def _combo_at(axes: list[list[float]], idx: int) -> tuple[float, ...]:
    """Index into the cartesian product without materializing it."""
    combo: list[float] = []
    for a in reversed(axes):
        idx, r = divmod(idx, len(a))
        combo.append(a[r])
    return tuple(reversed(combo))


def _sample_combos(axes: list[list[float]], max_variants: int) -> list[tuple[float, ...]]:
    total = _product_size(axes)
    if total <= max_variants:
        return list(itertools.product(*axes))
    stride = total / max_variants
    return [_combo_at(axes, int(i * stride)) for i in range(max_variants)]


def build_grid(spec: StrategySpec, *, max_variants: int = _MAX_VARIANTS) -> list[Variant]:
    """Cartesian product of each param's grid points → many fitted Versions. Deterministically truncated to
    `max_variants` (stride sampling, not a head slice, so the truncated grid still spans the space)."""
    keys = sorted(spec.param_space)
    axes = [_grid_values(spec.param_space[k]) for k in keys]
    combos = _sample_combos(axes, max_variants)
    variants: list[Variant] = []
    for combo in combos:
        params = {k: v for k, v in zip(keys, combo, strict=True)}
        tag = hashlib.sha256(
            (spec.name + "|" + ",".join(f"{k}={params[k]}" for k in keys)).encode()
        ).hexdigest()[:16]
        variants.append(Variant(params=params, config_tag=tag))
    return variants


def refine_around(
    spec: StrategySpec,
    survivors: list[Variant],
    *,
    top_n: int = _REFINE_TOP_N,
    points: int = _REFINE_POINTS,
    radius: float = _REFINE_RADIUS,
    max_variants: int = _MAX_VARIANTS,
) -> list[Variant]:
    """Second-pass grid: a finer search around the top survivors from the coarse pass. For each
    survivor, build a local grid with `points` per param centered on the survivor's values, within
    ±radius of the original range. Deterministic, bounded, and the gate still protects."""
    keys = sorted(spec.param_space)
    all_variants: list[Variant] = []
    seen_tags: set[str] = set()

    for survivor in survivors[:top_n]:
        axes: list[list[float]] = []
        for k in keys:
            ps = spec.param_space[k]
            center = survivor.params.get(k, 0.0)
            if ps.kind == "choice" and ps.choices:
                axes.append([float(c) for c in ps.choices])
                continue
            lo_orig = float(ps.lo) if ps.lo is not None else center
            hi_orig = float(ps.hi) if ps.hi is not None else center
            span = hi_orig - lo_orig
            lo_fine = max(lo_orig, center - span * radius)
            hi_fine = min(hi_orig, center + span * radius)
            if hi_fine <= lo_fine:
                axes.append([center])
                continue
            pts = [lo_fine + (hi_fine - lo_fine) * i / (points - 1) for i in range(points)]
            if ps.kind == "int":
                pts = sorted({float(int(round(p))) for p in pts})
            else:
                pts = [round(p, 8) for p in pts]
            axes.append(pts)

        combos = _sample_combos(axes, max_variants)
        for combo in combos:
            params = {k: v for k, v in zip(keys, combo, strict=True)}
            tag = hashlib.sha256(
                (spec.name + "|refine|" + ",".join(f"{k}={params[k]}" for k in keys)).encode()
            ).hexdigest()[:16]
            if tag not in seen_tags:
                seen_tags.add(tag)
                all_variants.append(Variant(params=params, config_tag=tag))

    if len(all_variants) > max_variants:
        stride = len(all_variants) / max_variants
        all_variants = [all_variants[int(i * stride)] for i in range(max_variants)]
    return all_variants


# --------------------------------------------------------------------------- the Finder


@dataclass(frozen=True)
class StrategyFinder:
    settings: Settings
    store: Store
    market_data: MarketDataProvider | None = None

    def _symbols(self, spec: StrategySpec) -> list[str]:
        """Crypto symbols for this spec — the full PERP_UNIVERSE when binance+crypto are enabled."""
        venues, classes = enabled_universe(self.store)
        if "crypto" not in spec.universe.asset_classes or "binance" not in spec.universe.venues:
            return []
        if "crypto" not in classes or "binance" not in venues:
            return []
        return list(_REAL_SYMBOLS)

    def _equity_symbols(self, spec: StrategySpec) -> list[str]:
        """Equity symbols when the spec's universe includes 'equity' AND equity is enabled in the global universe
        gate. The cache-backed symbol detection itself is the SINGLE source in master/screen_universe (shared with
        build_cost_context + the autonomous loop), so the finder and the cost context can never disagree on the
        set; this method only adds the finder's store-level enabled-universe gate on top."""
        if "equity" not in spec.universe.asset_classes:
            return []
        _, classes = enabled_universe(self.store)
        return equity_symbols(spec) if "equity" in classes else []

    def _hyperliquid_symbols(self, spec: StrategySpec) -> list[str]:
        """Hyperliquid perp symbols when the spec's universe includes 'hyperliquid'. Cache-only detection via the
        SINGLE source in master/screen_universe (returns whatever `ingest_hyperliquid_bars.py` has downloaded)."""
        return hyperliquid_symbols(spec)

    def _market(self, spec: StrategySpec) -> dict[str, list[Bar]]:
        limit = 1500 if spec.horizon.bar_size == "1h" else 1000
        out: dict[str, list[Bar]] = {}
        # Crypto panel — Binance perp bars (live fetch with cache fallback)
        provider = self.market_data or BinanceSpotOHLCVProvider()
        for symbol in self._symbols(spec):
            try:
                out[symbol] = provider.fetch_bars(symbol, spec.horizon.bar_size, limit=limit)
            except Exception:  # noqa: BLE001 — offline/no-network: skip the symbol, degrade to whatever cached
                continue
        # Equity panel — read from local cache only (no live fetch in the finder)
        if self._equity_symbols(spec):
            equity_provider = EquityOHLCVProvider()
            for symbol in self._equity_symbols(spec):
                try:
                    bars = equity_provider.fetch_bars(symbol, spec.horizon.bar_size, limit=limit)
                    if bars:
                        out[symbol] = bars
                except Exception:  # noqa: BLE001
                    continue
        # Hyperliquid perp panel — read from local cache (populated by ingest_hyperliquid_bars.py)
        if self._hyperliquid_symbols(spec):
            hl_provider = HyperliquidOHLCVProvider()
            for symbol in self._hyperliquid_symbols(spec):
                try:
                    bars = hl_provider.fetch_bars(symbol, spec.horizon.bar_size, limit=limit)
                    if bars:
                        out[symbol] = bars
                except Exception:  # noqa: BLE001
                    continue
        return out

    def find(
        self,
        spec: StrategySpec | None = None,
        *,
        max_variants: int = _MAX_VARIANTS,
        fdr_q: float = 0.10,  # noqa: ARG002 — kept for API compat; the BRUT path has no cross-cell FDR family
        persist: bool = True,
        two_pass: bool = True,
    ) -> FinderReport:
        """Run the full Finder pass for one seed spec, BRUT per-combo.

        A combo is one tradeable cell (this param-variant × one symbol × one venue), judged ON ITS OWN DATA:
        never pooled across symbols, never deflated by sibling cells, never compared to siblings. Steps: build the
        grid → screen every variant on REAL bars → for each (variant × symbol) build ONE BacktestMetrics from THAT
        symbol's per_symbol_run (own bar_returns + fold_returns) with trials = the per-combo param-grid count (the
        legitimate own-overfit deflation; the cross-combo family is dropped) → score each cell independently via
        promote_brut (TrialStats(count=1), the locked DSR/PBO math untouched) → refine around variants with ≥1
        passing cell → confirm each promoted cell on ITS OWN one-shot holdout → persist. Deterministic + LLM-free.

        Deliberately DROPPED vs the pooled finder: register_trial (a brut cell isn't part of a family), the cohort
        CSCV-PBO inject, the cluster-representative dedupe + rep gating, and BH-FDR. The fluke safeguard is the
        forward/paper test (live stays human-only)."""
        spec = spec or seed_orb_fvg_spec()
        market = self._market(spec)
        grid = build_grid(spec, max_variants=max_variants)
        # trials = the per-combo param-grid count — the number of param variants of THIS algorithm tried (the
        # legitimate own-overfit deflation). NOT the global ledger, NOT len(param_space) inherited blindly: it is
        # the realized grid size, so the brut cell's deflated Sharpe is INVARIANT to how many OTHER cells exist.
        grid_size = max(1, len(grid))
        catalog = default_catalog()
        venue = catalog.venue_for(spec.universe.venues)   # price against the spec's OWN venue (one source of fee truth)
        # Per-symbol cost + calendar context — taker fee, MARKET DEPTH (slippage/impact), the asset-class
        # annualization calendar, and the venue each cell was actually priced at — ALL from the single source the
        # autonomous loop also reads (master/screen_universe.build_cost_context). Each is None on the common
        # crypto-only path → the backtest's SCALAR venue fee/depth is used, byte-identical to before.
        fee_schedule, depth_schedule, asset_class_by_symbol, venue_id_by_symbol = build_cost_context(spec, market, catalog)
        # Point-in-time alt-data join (funding_rate, fear_greed, …), built ONCE per spec since it depends only on
        # the spec's features + the market, not the swept params.
        alt = build_alt_by_symbol(resolve_alt_store(self.settings, self.store), spec, market)

        results: list[VariantResult] = []

        def _screen_into(variant: Variant) -> None:
            r = self._screen(spec, variant, market, venue, alt, grid_size=grid_size,
                             fee_schedule=fee_schedule, depth_schedule=depth_schedule,
                             asset_class_by_symbol=asset_class_by_symbol, venue_id_by_symbol=venue_id_by_symbol)
            if r is None:
                return  # an invalid grid point (e.g. degenerate range) is skipped, never persisted
            results.append(r)

        # ---- coarse pass: screen + score each cell of each variant on its OWN data ----
        for variant in grid:
            _screen_into(variant)

        # TWO-PASS REFINEMENT around variants that have ≥1 PASSING cell (a real per-cell edge to localize). No
        # leaderboard ranking across cells — a variant qualifies as a refine seed iff some cell of it passed.
        if two_pass:
            coarse_passers = sorted(
                [r for r in results if r.gate_passed],
                key=lambda r: r.deflated_sharpe,
                reverse=True,
            )[:_REFINE_TOP_N]
            if coarse_passers:
                by_tag = {v.config_tag: v for v in grid}
                survivor_variants = [by_tag[r.config_tag] for r in coarse_passers if r.config_tag in by_tag]
                existing_tags = {r.config_tag for r in results}
                for variant in refine_around(spec, survivor_variants):
                    if variant.config_tag in existing_tags:
                        continue
                    _screen_into(variant)

        # CHAMPION-ONLY one-shot holdout, PER CELL. The screen ran include_holdout=False (no cell simulated the
        # exam). For each variant with ≥1 passing cell, re-run WITH the embargoed holdout once and confirm EACH
        # passing cell on ITS OWN holdout run (per_symbol_holdout_runs[sym]) — a pure CONFIRMATION, never a retry.
        floor = float(self.settings.gates.holdout_min_deflated_sharpe)
        for r in results:
            r.holdout_passed = False
        for r in (r for r in results if r.gate_passed):
            champion = run_strategy_backtest_detailed(
                spec, dict(r.fitted_params), market, fee_bps=venue.taker_fee_bps,
                fee_schedule=fee_schedule,
                slippage_bps=venue.slippage_bps, impact_bps=venue.impact_bps,
                depth_schedule=depth_schedule, alt_by_symbol=alt,
                asset_class_by_symbol=asset_class_by_symbol,
            )  # include_holdout defaults True — the single exam look for this champion variant
            r.target_vol = champion.target_vol  # T1: freeze vol anchor from the full backtest (incl. holdout bars)
            any_cell_holdout = False
            for sym, cell in r.cells.items():
                if not cell.passed:
                    continue
                # Score this cell's holdout on ITS OWN holdout stream: metrics_for_run with holdout_run = this
                # symbol's untouched holdout SymbolRun gives the cell's holdout deflated Sharpe (recentred PSR).
                h_run = champion.per_symbol_holdout_runs.get(sym)
                cell_h_dsr = (
                    float(
                        metrics_for_run(
                            champion.per_symbol_runs.get(sym, h_run),
                            trials=grid_size,
                            buy_and_hold=champion.per_symbol_buy_and_hold.get(sym, 0.0),
                            holdout_run=h_run,
                        ).holdout_deflated_sharpe
                    )
                    if h_run is not None else 0.0
                )
                cell.holdout_passed = cell_h_dsr > floor
                cell.metrics = cell.metrics.model_copy(update={"holdout_deflated_sharpe": Decimal(str(round(cell_h_dsr, 6)))})
                cell.target_vol = champion.target_vol
                any_cell_holdout = any_cell_holdout or cell.holdout_passed
            r.holdout_passed = any_cell_holdout
            try:
                self.store.append_event(
                    actor="master", kind="holdout_look", ref_type="strategy",
                    ref_id=f"{spec.name}:{r.config_tag}",
                    payload={
                        "passed": r.holdout_passed,
                        "cells": {s: c.holdout_passed for s, c in r.cells.items() if c.passed},
                    },
                )
            except Exception:  # noqa: BLE001 — audit trail is best-effort; the verdict itself is already set
                pass
        for r in results:
            r.promoted = r.gate_passed  # brut: a variant "promotes" iff ≥1 of its cells passed (no FDR/cluster gate)

        if persist:
            self._persist(spec, results, market, venue, venue_id_by_symbol)

        # Experiment-tracking hook (thin, best-effort): log EVERY screened variant to the registry.
        self._log_experiments(spec, results, market)

        gate_passers = [r for r in results if r.gate_passed]
        leaderboard = sorted(gate_passers, key=lambda r: (r.profit_factor, r.deflated_sharpe), reverse=True)
        # A SURVIVOR is a variant with at least one cell that passed the gate AND confirmed on its own holdout.
        survivors = [r for r in results if r.promoted and r.holdout_passed]
        return FinderReport(
            strategy_name=spec.name,
            grid_size=len(grid),
            screened=len(results),
            gate_passed=len(gate_passers),
            promoted=len(survivors),
            leaderboard=leaderboard[:24],
            survivors=survivors,
        )

    # ------------------------------------------------------------------ screening + honest scoring

    def _screen(
        self,
        spec: StrategySpec,
        variant: Variant,
        market: dict[str, list[Bar]],
        venue,  # noqa: ANN001 — venue catalog row
        alt_by_symbol: dict[str, dict[str, dict[str, float]]] | None,
        *,
        grid_size: int,
        fee_schedule: dict[str, Decimal] | None = None,
        depth_schedule: dict[str, tuple[Decimal, Decimal]] | None = None,
        asset_class_by_symbol: dict[str, str] | None = None,
        venue_id_by_symbol: dict[str, str] | None = None,
    ) -> VariantResult | None:
        """Compile + backtest one variant on REAL bars, then BUILD AND SCORE ONE CELL PER (symbol, venue) on its
        OWN streams. Returns a VariantResult carrying per-cell verdicts — or None for an invalid grid point.

        Each cell's BacktestMetrics comes from metrics_for_run(per_symbol_runs[sym], trials=grid_size, ...) — the
        cell's OWN bar_returns AND own fold_returns (NEVER the pooled val.* streams), and the per-combo param-grid
        count as the own-overfit deflation. Each cell is scored by promote_brut (TrialStats(count=1), the min-trades
        floor on the cell's OWN trades). A cell passes iff promote_brut promoted it AND it cleared the per-cell
        trade floor. The variant's pooled `metrics`/`profit_factor` are kept for DISPLAY only; the brut verdict is
        per cell."""
        try:
            compiled = compile_spec(spec, variant.params)
        except ValueError:
            return None
        # include_holdout=False: the SCREEN sees validation evidence only — the untouched holdout is confirmed once
        # per passing cell in find()'s champion-only holdout step. Each leg is priced at ITS OWN venue depth.
        detailed = run_strategy_backtest_detailed(
            spec, variant.params, market, fee_bps=venue.taker_fee_bps,
            fee_schedule=fee_schedule,
            slippage_bps=venue.slippage_bps, impact_bps=venue.impact_bps,
            depth_schedule=depth_schedule,
            alt_by_symbol=alt_by_symbol,
            include_holdout=False,
            asset_class_by_symbol=asset_class_by_symbol,
        )
        metrics = detailed.metrics  # POOLED — display only (best_symbol, the leaderboard); never the brut verdict
        net_profit = float(metrics.oos_return) - _round_trip_cost(metrics, venue)
        result = VariantResult(
            config_tag=variant.config_tag,
            code_hash=compiled.code_hash,
            metrics=metrics,
            deflated_sharpe=0.0,
            profit_factor=float(metrics.profit_factor),
            net_profit=net_profit,
            gate_passed=False,
            reasons=[],
            fitted_params=variant.params,
            per_symbol=detailed.per_symbol,
        )
        result.cells = self._score_cells(detailed, venue, grid_size, venue_id_by_symbol)
        # The variant's display deflated_sharpe = the BEST cell's deflated Sharpe (a display ranking number; the
        # brut verdict is per cell). gate_passed iff ANY cell passed — a config with one real cell edge qualifies.
        passing = [c for c in result.cells.values() if c.passed]
        result.gate_passed = bool(passing)
        result.deflated_sharpe = max((c.deflated_sharpe for c in result.cells.values()), default=0.0)
        result.reasons = [] if passing else ["no_passing_cell"]
        return result

    def _score_cells(
        self,
        detailed,  # noqa: ANN001 — BacktestResult
        venue,  # noqa: ANN001 — venue catalog row
        grid_size: int,
        venue_id_by_symbol: dict[str, str] | None,
    ) -> dict[str, CellResult]:
        """Build ONE CellResult per (symbol, venue) from the variant's per-symbol RUNS, judged on its OWN data.

        NO RE-POOLING: each cell's metrics come from detailed.per_symbol_runs[sym] (own bar_returns AND own
        fold_returns), the per-symbol B&H, and trials=grid_size (the per-combo param-search count) — never the
        pooled val.bar_returns/val.fold_returns. promote_brut scores each cell alone (TrialStats(count=1), so the
        cell's deflated Sharpe is invariant to how many OTHER cells the sweep produced) with the min-trades floor on
        the cell's OWN trades. A cell passes iff promoted AND it cleared the per-cell trade floor."""
        vmap = venue_id_by_symbol or {}
        cell_metrics: dict[str, BacktestMetrics] = {}
        for sym, run in detailed.per_symbol_runs.items():
            cell_metrics[sym] = metrics_for_run(
                run,
                trials=grid_size,
                buy_and_hold=detailed.per_symbol_buy_and_hold.get(sym, 0.0),
            )
        candidates = [CohortCandidate(id=sym, metrics=m, net_profit=0.0, source="finder") for sym, m in cell_metrics.items()]
        promotions = {p.candidate_id: p for p in promote_brut(candidates, self.settings.gates, min_trades=_BRUT_MIN_TRADES)}
        out: dict[str, CellResult] = {}
        for sym, m in cell_metrics.items():
            p = promotions[sym]
            trades = m.num_trades
            reasons = list(p.reasons)
            floor_ok = trades >= _MIN_TRADES_PER_SYMBOL
            if not floor_ok:
                reasons.append("min_trades_per_symbol")
            out[sym] = CellResult(
                symbol=sym,
                venue_id=vmap.get(sym, venue.id),
                metrics=m,
                deflated_sharpe=p.deflated_sharpe_prob,
                trades=trades,
                passed=p.promoted and floor_ok,
                reasons=reasons,
            )
        return out

    # ------------------------------------------------------------------ persistence (config library)

    def _persist(self, spec: StrategySpec, results: list[VariantResult], market: dict[str, list[Bar]], venue, venue_id_by_symbol: dict[str, str] | None = None) -> None:  # noqa: ANN001 — venue catalog row
        """Write the config library, BRUT per-cell: one strategies row + one strategy_versions row per variant
        (origin='finder', config_tag in params), the screen backtest, one backtest_symbols row PER CELL (carrying
        the cell's OWN pass/fail in `verdict`), and — for each cell that passed the gate AND confirmed on its OWN
        holdout — a per-CELL paper track + a cell-keyed `track_opened` event (the paper clock origin + this cell's
        own proven-regime passport that master/live_eligibility reads) + a finder_survivor event. Idempotent: a
        variant whose code_hash already exists is not re-inserted."""
        with self.store.batch() as b:
            strategy_id = self._ensure_strategy(b, spec)
            for r in results:
                if self._version_exists(r.code_hash):
                    continue
                # GENEROUS-PAPER near-miss set (computed once, used for the status, the per-cell verdict, AND the
                # track fan-out): the gate-FAILED cells promising enough to forward-test (sharpe>1 / trades>=30 /
                # return>0, net of fees — off the same per-cell display metrics persisted on backtest_symbols).
                _watch_syms: set[str] = {
                    _sym
                    for _sym, _pm in (r.per_symbol or {}).items()
                    if (_c := r.cells.get(_sym)) is not None and not _c.passed
                    and is_near_miss_cell(
                        sharpe=float(_pm.get("sharpe", 0.0)),
                        trades=int(_pm.get("trades", 0)),
                        return_pct=float(_pm.get("return", 0.0)),
                    )
                }
                # A variant is SCREENED (kept on /lab) iff ANY of its cells passed the brut gate. A variant with NO
                # gate pass but a WATCH near-miss goes to PAPER (it forward-tests on the generous lane, so it must be
                # ALIVE for the funder + executor to step it — KILLED versions are skipped by both). Only a variant
                # with neither a pass nor a watch cell is truly KILLED. The brut gate VERDICT is unchanged: the
                # backtest's passed_gates flag still reflects the gate, and a watch version is never live-armable
                # (live-eligibility reads the per-cell pass passport, which a watch cell lacks).
                if r.gate_passed:
                    status = "screened"
                elif _watch_syms:
                    status = "paper"
                else:
                    status = "killed"
                _is_killed = status == "killed"
                kill_reason = None if not _is_killed else (",".join(r.reasons) or "no_passing_cell")
                fitted = r.fitted_params or fit_params(spec)
                params = {**fitted, "config_tag": r.config_tag}
                compiled = compile_spec(spec, fitted)
                version_id = b.insert(
                    "strategy_versions",
                    {
                        "strategy_id": strategy_id,
                        "parent_id": None,
                        "spec": spec.model_dump(mode="json"),
                        "generated_code": compiled.code,
                        "code_hash": r.code_hash,
                        "params": params,
                        "mutation_operator": "finder_grid",
                        "mutation_rationale": f"grid variant {r.config_tag}",
                        "origin": "finder",
                        "status": status,
                        "created_at": utcnow(),
                        "killed_at": utcnow() if _is_killed else None,
                        "kill_reason": kill_reason,
                    },
                )
                r.version_id = version_id
                bt_id = b.insert("backtests", _backtest_row(version_id, r.metrics, r.deflated_sharpe, r.gate_passed, r.holdout_passed, venue, r.per_symbol))
                # PER-CELL rows = the queryable unit of truth (1 strat × 1 symbol × 1 venue × 1 result). venue_id =
                # the venue THIS symbol was actually priced at (the real fee axis of the S×A×V triple). `verdict`
                # carries the BRUT per-cell pass/fail: 'pass' iff this cell cleared the gate on its OWN data (the
                # funder fans out a paper track per 'pass' cell), else the cell's own kill reason. NEVER a pooled or
                # sibling-compared label — each cell is judged alone.
                _vmap = venue_id_by_symbol or {}
                # GENEROUS-PAPER routing: a gate-FAILED near-miss cell (in _watch_syms, computed above) is tagged
                # 'watch' (not its kill reason) and ALSO funds a paper track below. The gate verdict ('pass') and the
                # true-negative kill reasons are untouched.
                for _sym, _pm in (r.per_symbol or {}).items():
                    cell = r.cells.get(_sym)
                    cell_venue = cell.venue_id if cell else _vmap.get(_sym, venue.id)
                    if cell and cell.passed:
                        cell_verdict = "pass"
                    elif _sym in _watch_syms:
                        cell_verdict = WATCH_VERDICT
                    else:
                        cell_verdict = (",".join(cell.reasons) or "fail") if cell else None
                    b.insert("backtest_symbols", {
                        "backtest_id": bt_id, "strategy_version_id": version_id, "symbol": _sym, "venue_id": cell_venue,
                        "return_pct": str(_pm.get("return", 0.0)), "sharpe": str(_pm.get("sharpe", 0.0)),
                        "max_drawdown": str(_pm.get("max_drawdown", 0.0)), "trades": int(_pm.get("trades", 0)),
                        "verdict": cell_verdict, "created_at": utcnow(),
                    })
                # PER-CELL TRACKS, TWO generous-paper lanes:
                #   • GATE lane (lane='finder'): a cell that passed the gate AND confirmed on its OWN holdout.
                #   • WATCH lane (lane='watch'): a gate-FAILED near-miss cell (verdict='watch' above) — routed to the
                #     SAME zero-real-capital, born-honest paper test INSTEAD of being killed, so the forward record
                #     separates real from lucky. A watch track is NOT a gate pass (live-eligibility never reads it as
                #     proof) and it defunds on drift like any paper cell.
                # Born HONEST (equity=starting_capital, return_pct=0); the paper clock advances the forward columns
                # from real marks. The track_opened event is keyed to the CELL (cell_id) so master/live_eligibility
                # reads this cell's OWN clock origin — never a sibling cell's. Each cell stands alone.
                _capital = self.settings.sim_track_capital
                # Pre-migration the tracks table still has UNIQUE(strategy_version_id) (the per-cell UNIQUE arrives
                # with the held migration), so a version with >1 fundable cell (either lane) would collide on the 2nd
                # insert. Until migrated, degrade to ONE version-wide track per version (fund the first fundable cell,
                # skip the rest); post-migration every cell funds its own track. Schema-adaptive — crash-proof on both.
                _cell_cols = tracks_has_cell_columns(self.store)
                _opened_version_wide = False
                for _sym, cell in r.cells.items():
                    _is_pass = cell.passed and cell.holdout_passed
                    _is_watch = (not cell.passed) and (_sym in _watch_syms)
                    if not (_is_pass or _is_watch):
                        continue
                    if not _cell_cols and _opened_version_wide:
                        continue
                    open_paper_track(b, version_id=version_id, starting_capital=_capital, target_vol=cell.target_vol,
                                     symbol=cell.symbol, venue_id=cell.venue_id, store=self.store)
                    if not _cell_cols:
                        _opened_version_wide = True
                    proven = sorted(proven_regimes(cell.metrics.regime_returns))
                    b.append_event(
                        actor="master", kind="track_opened", ref_type="strategy_version",
                        ref_id=cell_id(version_id, cell.symbol, cell.venue_id),
                        payload={
                            "deflated_sharpe": round(cell.deflated_sharpe, 6),
                            "config_tag": r.config_tag, "origin": "finder",
                            "lane": "watch" if _is_watch else "finder",
                            "symbol": cell.symbol, "venue_id": cell.venue_id,
                            "proven_regimes": proven,
                        },
                    )
                    # Only a GATE-lane cell is a finder_survivor (the live-arming passport). A watch cell is observed
                    # forward, never recorded as a survivor — it never enters the gate-pass funding join.
                    if _is_pass:
                        b.append_event(
                            actor="master", kind="finder_survivor", ref_type="strategy_version",
                            ref_id=cell_id(version_id, cell.symbol, cell.venue_id),
                            payload={
                                "config_tag": r.config_tag, "symbol": cell.symbol, "venue_id": cell.venue_id,
                                "deflated_sharpe": round(cell.deflated_sharpe, 6),
                                "holdout_passed": cell.holdout_passed,
                            },
                        )

        # After the version rows are committed, record each surviving CHAMPION's one-shot holdout verdict through
        # the ledger (separate transaction; idempotent on version_id) so the finder can never re-pick on the
        # holdout. Only variants with a passing cell ever took the exam (champion-only holdout).
        ledger = HoldoutLedger(self.store)
        for r in results:
            if r.version_id and r.gate_passed and not ledger.consumed(r.version_id):
                ledger.evaluate_once(
                    r.version_id,
                    lambda r=r: {"passed": r.holdout_passed, "deflated_sharpe": round(r.deflated_sharpe, 6)},
                )

        # FREEZE each promoted survivor into its strategy_promotions record — the single source of truth live
        # reads to replicate the Gate's verdict (frozen params + hash, fee model, registry version, regimes).
        # Runs AFTER the batch commits so it sees the committed version + track_opened rows. Best-effort: a freeze
        # hiccup must never unwind a valid promotion (the gate already disposed; the freeze is durable bookkeeping).
        for r in results:
            if r.version_id and r.promoted and r.holdout_passed:
                try:
                    freeze_promotion(self.store, r.version_id)
                except Exception:  # noqa: BLE001 — freeze is durable bookkeeping, never blocks a real promotion
                    pass

    def _ensure_strategy(self, b: Writer, spec: StrategySpec) -> str:
        existing = self.store.row("SELECT id FROM strategies WHERE name = ? AND origin = 'finder'", (spec.name,))
        if existing:
            return str(existing["id"])
        return b.insert(
            "strategies",
            {"name": spec.name, "thesis": spec.rationale, "origin": "finder", "created_at": utcnow()},
        )

    def _version_exists(self, code_hash: str) -> bool:
        return self.store.row("SELECT id FROM strategy_versions WHERE code_hash = ?", (code_hash,)) is not None

    def _log_experiments(self, spec: StrategySpec, results: list[VariantResult], market: dict[str, list[Bar]]) -> None:
        """The experiment-tracking hook: one registry row per screened variant. config = the fitted params
        (the regeneration knobs), metrics = the full scoreable BacktestMetrics, soft_label = net forward-P&L
        (the continuous gradient for the ranker). Deterministic run seed from settings so a re-run reproduces."""
        dv = data_version(market)
        seed = int(self.settings.evolution.default_seed)
        records = [
            ExperimentRecord(
                kind=KIND_FINDER,
                source="finder",
                label=r.config_tag,
                config={**r.fitted_params, "config_tag": r.config_tag},
                metrics=r.metrics.model_dump(mode="json"),
                seed=seed,
                data_version=dv,
                code_hash=r.code_hash,
                soft_label=r.net_profit,
                gate_passed=r.gate_passed,
            )
            for r in results
        ]
        log_experiments(self.store, records)



# --------------------------------------------------------------------------- cost / display helpers


def _round_trip_cost(metrics: BacktestMetrics, venue) -> float:  # noqa: ANN001
    """A net-of-cost haircut on the variant's return for RANKING the cohort by money: fee bps × number of
    round trips. The backtest already nets fees into each trade's PnL; this is the cohort-level money proxy."""
    fee = float(venue.taker_fee_bps) / 10000.0
    return fee * 2.0 * float(metrics.num_trades)


def _backtest_row(version_id: str, m: BacktestMetrics, deflated: float, passed: bool, holdout_ok: bool, venue, per_symbol: dict | None = None) -> dict:  # noqa: ANN001 — venue catalog row
    # best_symbol / best_pnl_pct = the single highest OOS return across the symbols tested. DISPLAY-ONLY (the
    # pooled deflated gate still decides pass/fail — funding the best-of-N would be a multiple-testing hole).
    best_symbol = max(per_symbol, key=lambda s: per_symbol[s].get("return", float("-inf"))) if per_symbol else None
    best_pnl_pct = str(round(per_symbol[best_symbol].get("return", 0.0), 6)) if best_symbol else None
    return {
        "strategy_version_id": version_id,
        "kind": "screen",
        "oos_return": str(m.oos_return),
        "sharpe": str(m.sharpe),
        "sortino": str(m.sortino),
        "deflated_sharpe": str(round(deflated, 6)),
        "max_dd": str(m.max_drawdown),
        "win_rate": str(m.win_rate),
        "num_trades": m.num_trades,
        "pbo": str(m.pbo),
        "trials_counted": m.trials_counted,
        "regime_label": "mixed",
        "folds_positive": int(m.folds_positive_pct * 6),
        "passed_gates": int(passed),
        "holdout_passed": int(holdout_ok),
        # Survival-model feature row (see ml/survival.py) — persisted so the ranker trains on the same vector
        # it scores with. Matches the evolution-loop screen insert; nullable in the schema for older rows.
        "sharpe_per_obs": str(m.sharpe_per_obs),
        "skew": str(m.skew),
        "kurtosis": str(m.kurtosis),
        "n_obs": m.n_obs,
        "regime_spread": sum(1 for pnl in m.regime_returns.values() if pnl > 0),
        # The cost assumptions this screen was scored under — the venue it priced against (taker fee) + the
        # SAME venue's market depth the backtest actually charged. Frozen into the promotion so live can detect
        # a venue repricing (record the values charged, never the global default — they can now differ per venue).
        "venue_id": venue.id,
        "fee_bps": str(venue.taker_fee_bps),
        "slippage_bps": str(venue.slippage_bps),
        "impact_bps": str(venue.impact_bps),
        "best_symbol": best_symbol,
        "best_pnl_pct": best_pnl_pct,
        "per_symbol": per_symbol or None,  # granular {symbol:{return,sharpe,max_drawdown,trades}} → JSON in DB
        "created_at": utcnow(),
    }


# --------------------------------------------------------------------------- bootstrap / CLI


def _offline_store() -> Store:
    tmp = tempfile.mkdtemp(prefix="cosmu-finder-")
    return Store(Settings(database_url=f"sqlite:///{tmp}/finder.sqlite3", openrouter_api_key=None))


def seed_real(store: Store | None = None, *, max_variants: int = 64) -> FinderReport:
    """Bootstrap the app with GENUINE backtested strategies: run the Finder on the ORB+FVG seed over REAL Binance
    spot bars (cached; degrades to cache offline) and PERSIST real Strategy/Version/Track/backtest/survivor rows.
    Idempotent (a variant whose code_hash exists is skipped) and safe offline."""
    store = store or Store(Settings())
    finder = StrategyFinder(settings=store.settings, store=store)
    return finder.find(seed_orb_fvg_spec(), max_variants=max_variants, persist=True)


def _print(report: FinderReport) -> None:
    print(f"STRATEGY FINDER — {report.strategy_name}")
    print(f"  grid={report.grid_size} screened={report.screened} gate_passed={report.gate_passed} promoted={report.promoted}")
    print("  LEADERBOARD (ranked by profit_factor; promotion uses the Gate + FDR + holdout, not PF order):")
    for r in report.leaderboard[:12]:
        tag = "PROMOTED" if (r.promoted and r.holdout_passed) else ("gate-pass" if r.gate_passed else "screened")
        print(f"    [{tag}] {r.config_tag} · PF={r.profit_factor:.3f} · deflated_sharpe={r.deflated_sharpe:.4f} · net={r.net_profit:+.4f} · trades={r.metrics.num_trades}")
    if not report.survivors:
        print("  (no variant cleared the Gate + FDR + one-shot holdout — nothing promoted; honest empty result)")


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Strategy Finder: grid-search a spec → screen on real bars → rank by profit_factor + Gate → WFO/holdout → config library.")
    parser.add_argument("--max-variants", type=int, default=64, help="cap on grid variants (default 64)")
    parser.add_argument("--seed-real", action="store_true", help="persist real backtested strategies to the configured store (bootstrap)")
    args = parser.parse_args(argv)

    if args.seed_real:
        report = seed_real(max_variants=args.max_variants)
    else:
        # Default demo: run fully offline against the edge-bearing fixture so the leaderboard is visible with
        # no keys/network. The deterministic screen/gate judge honestly.
        from cosmu.research.fixtures import edge_bearing_screen_market

        class _FixtureBars:
            def __init__(self) -> None:
                self._by = edge_bearing_screen_market()
                self._default = next(iter(self._by.values()))

            def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
                return self._by.get(symbol, self._default)[-limit:]

        finder = StrategyFinder(settings=Settings(openrouter_api_key=None), store=_offline_store(), market_data=_FixtureBars())
        report = finder.find(seed_orb_fvg_spec(), max_variants=args.max_variants, persist=True)

    _print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
