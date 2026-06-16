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
import math
import statistics
import tempfile
from dataclasses import dataclass, field, replace
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.alt_join import build_alt_by_symbol, resolve_alt_store
from cosmu.data.backtest import run_strategy_backtest_detailed
from cosmu.data.market import Bar, BinanceSpotOHLCVProvider, EquityOHLCVProvider, HyperliquidOHLCVProvider, MarketDataProvider
from cosmu.data.universe import PERP_UNIVERSE
from cosmu.evolution.loop import fit_params
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.experiments import KIND_FINDER, ExperimentRecord, data_version, log_experiments
from cosmu.knowledge.store import Store, Writer, utcnow
from cosmu.master.cohort import Candidate as CohortCandidate
from cosmu.master.cohort import promote_cohort
from cosmu.master.holdout import HoldoutLedger
from cosmu.master.verdict_log import CohortPersist
from cosmu.master.promotion import freeze_promotion
from cosmu.master.scorer import BacktestMetrics, TrialStats, cscv_pbo, score
from cosmu.master.tracks import open_paper_track
from cosmu.master.trials import register_trial
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
# Cap equity symbols per finder run. More symbols → more trials → stricter gate (correct), but also slower
# local runs. 50 gives breadth without dominating the trial budget on a correlated sector basket.
_EQUITY_SCREEN_LIMIT = 50
# Cap Hyperliquid perp symbols per run. HL perps are highly correlated with Binance perps (same underlying),
# so 30 liquid perps is already generous — matching the Binance PERP_UNIVERSE width.
_HL_SCREEN_LIMIT = 30
# Two validation return streams with Pearson correlation >= this are treated as the SAME hypothesis: one is the
# cluster representative, the rest are near-duplicates. Dedupe to representatives BEFORE BH-FDR so a dense
# correlated grid can't game the false-discovery cutoff (cohort.py's "distinct candidates" contract).
_CLUSTER_CORRELATION = 0.95
# Per-symbol validation trade floor. The pooled gate (min_trades=30) can be met with ~6 trades on each of 5
# correlated symbols; require independent evidence on EACH traded symbol instead of accepting a pooled count.
_MIN_TRADES_PER_SYMBOL = 5


@dataclass(frozen=True)
class Variant:
    """One point in the grid: the parent spec + a concrete fitted param dict + a stable config tag."""

    params: dict[str, float]
    config_tag: str


@dataclass
class VariantResult:
    config_tag: str
    code_hash: str
    metrics: BacktestMetrics
    deflated_sharpe: float
    profit_factor: float
    net_profit: float
    gate_passed: bool
    reasons: list[str]
    fitted_params: dict[str, float] = field(default_factory=dict)
    version_id: str | None = None
    promoted: bool = False
    holdout_passed: bool = False
    target_vol: float | None = None  # T1 sizing anchor: set from champion.target_vol at champion holdout


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
        """Equity symbols when the spec's universe includes 'equity'. Reads the local cache to avoid a network
        dependency at discovery time; the cache is maintained by equity backfill scripts."""
        if "equity" not in spec.universe.asset_classes:
            return []
        _, classes = enabled_universe(self.store)
        if "equity" not in classes:
            return []
        return EquityOHLCVProvider().available_symbols()[:_EQUITY_SCREEN_LIMIT]

    def _hyperliquid_symbols(self, spec: StrategySpec) -> list[str]:
        """Hyperliquid perp symbols when the spec's universe includes 'hyperliquid'. Cache-only: returns
        whatever `ingest_hyperliquid_bars.py` has already downloaded; empty if the cache hasn't been run."""
        if "hyperliquid" not in spec.universe.venues:
            return []
        return HyperliquidOHLCVProvider().available_symbols()[:_HL_SCREEN_LIMIT]

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
        fdr_q: float = 0.10,
        persist: bool = True,
        two_pass: bool = True,
    ) -> FinderReport:
        """Run the full Finder pass for one seed spec — now as statistically honest as research/gate.py.

        Steps: build the grid → screen every variant on REAL bars → register EVERY variant as a trial so the
        global ledger reflects the TRUE count (not len(param_space)) → score every variant against that true,
        correlation-haircut trial count AND the cohort's REAL CSCV-PBO (not the per-variant proxy) → pick refine
        seeds from those HONEST gate-passers → TWO-PASS REFINEMENT → cluster the correlated grid into DISTINCT
        representatives and run BH-FDR over THOSE (cohort.py's "distinct candidates" contract) → one-shot
        holdout-validate before the config library. Deterministic, LLM-free, and a dense correlated grid can no
        longer manufacture significance."""
        spec = spec or seed_orb_fvg_spec()
        market = self._market(spec)
        grid = build_grid(spec, max_variants=max_variants)
        catalog = default_catalog()
        venue = catalog.venue_for(spec.universe.venues)   # price against the spec's OWN venue (one source of fee truth)
        # Per-symbol fee schedule: equity symbols pay IBKR (0.5 bps); HL perp symbols pay HL (1.5 bps); crypto
        # symbols pay the spec's primary venue fee. None when all symbols share the same venue fee (common
        # crypto-only path) — avoids a dict-lookup on every bar for the typical case.
        equity_syms = set(self._equity_symbols(spec)) & market.keys()
        hl_syms = set(self._hyperliquid_symbols(spec)) & market.keys()
        fee_schedule = None
        if equity_syms or hl_syms:
            fee_schedule = {s: venue.taker_fee_bps for s in market}
            if equity_syms:
                ibkr_fee = catalog.venue("ibkr").taker_fee_bps
                fee_schedule.update({s: ibkr_fee for s in equity_syms})
            if hl_syms:
                hl_fee = catalog.venue("hyperliquid").taker_fee_bps
                fee_schedule.update({s: hl_fee for s in hl_syms})
        # Per-symbol annualization calendar: equity symbols trade ≈252 sessions/yr, so their Sharpe must NOT be
        # annualized at crypto's 365 (a pooled cross-asset spec would otherwise over-state the equity leg ≈1.2×).
        # Crypto + HL perps are 24/7 → the 365-session default (None) is already correct, so we only mark equity.
        # None when there are no equity symbols (the common crypto-only path stays byte-identical).
        asset_class_by_symbol = {s: "equity" for s in equity_syms} or None
        # Point-in-time alt-data join (funding_rate, fear_greed, …), built ONCE per spec since it depends only on
        # the spec's features + the market, not the swept params. Without this the sweep would screen every
        # funding/meta-label spec price-only (funding reads None) — the same join the cohort screen uses.
        alt = build_alt_by_symbol(resolve_alt_store(self.settings, self.store), spec, market)

        results: list[VariantResult] = []
        cohort: list[CohortCandidate] = []
        returns_by_tag: dict[str, list[float]] = {}
        trades_by_tag: dict[str, int] = {}

        def _screen_into(variant: Variant, source: str, label: str) -> None:
            screened = self._screen(spec, variant, market, venue, alt, source=source, label=label, fee_schedule=fee_schedule, asset_class_by_symbol=asset_class_by_symbol)
            if screened is None:
                return  # an invalid grid point (e.g. degenerate range) is skipped, never persisted
            r, cand, val_returns, min_symbol_trades = screened
            results.append(r)
            cohort.append(cand)
            returns_by_tag[r.config_tag] = val_returns
            trades_by_tag[r.config_tag] = min_symbol_trades
            # Problem 1 — register EVERY screened variant as a trial so the global ledger (and thus every
            # deflation in this run) reflects the TRUE running count, not the ~len(param_space) proxy.
            register_trial(self.store, float(cand.metrics.sharpe_per_obs), source=cand.source, label=cand.label or cand.id)

        # ---- coarse pass ----
        for variant in grid:
            _screen_into(variant, "finder", f"{spec.name}:{variant.config_tag}")
        # Honest coarse scoring drives the refine-seed selection below: the TRUE running trial count with the
        # SAME dedupe-based effective-N as the final pass (so a correlated-but-real edge survives to refinement
        # instead of being over-deflated against the raw coarse count).
        coarse_reps = _cluster_representatives(results, returns_by_tag, threshold=_CLUSTER_CORRELATION)
        self._rescore(results, returns_by_tag, trades_by_tag,
                      self._finder_trial_stats(coarse_reps, {r.config_tag: r for r in results}))

        # TWO-PASS REFINEMENT around the HONEST coarse gate-passers (not the leaky ones).
        if two_pass:
            coarse_passers = sorted(
                [r for r in results if r.gate_passed],
                key=lambda r: (r.profit_factor, r.deflated_sharpe),
                reverse=True,
            )[:_REFINE_TOP_N]
            if coarse_passers:
                by_tag = {v.config_tag: v for v in grid}
                survivor_variants = [by_tag[r.config_tag] for r in coarse_passers if r.config_tag in by_tag]
                existing_tags = {r.config_tag for r in results}
                for variant in refine_around(spec, survivor_variants):
                    if variant.config_tag in existing_tags:
                        continue
                    _screen_into(variant, "finder_refine", f"{spec.name}:refine:{variant.config_tag}")

        # ---- dedupe the correlated grid → DISTINCT representatives; compute the run-wide honest context ----
        reps = _cluster_representatives(results, returns_by_tag, threshold=_CLUSTER_CORRELATION)
        results_by_tag = {r.config_tag: r for r in results}
        finder_stats = self._finder_trial_stats(reps, results_by_tag)         # true count, effective-N = clusters (Problems 1, 2)
        cohort_pbo = _cohort_pbo(reps, returns_by_tag)                         # REAL CSCV-PBO across the grid (Problem 3)

        # FINAL scoring of every variant against the honest context — drives the displayed leaderboard.
        self._rescore(results, returns_by_tag, trades_by_tag, finder_stats, cohort_pbo=cohort_pbo)

        # BH-FDR over the DISTINCT representatives only (Problem 6); the ledger already holds every variant so
        # deflation still sees the true count (register=False), and the haircut context is injected (trials=).
        rep_set = set(reps)
        rep_cohort = [
            _with_pbo(c, cohort_pbo)
            for c in cohort
            if c.id in rep_set and trades_by_tag.get(c.id, 0) >= _MIN_TRADES_PER_SYMBOL
        ]
        # OBSERVE-ONLY rejects watch-list: opt the REAL autonomous cohort path into measuring the gate's Type-II
        # rate. `watch_rejects=True` makes persist_cohort_verdict additionally band the gate-rejected-but-CLOSE
        # representatives (promoted=False AND DSR in [0.90,0.95) AND survived FDR AND no risk-floor reason) into
        # rejects_watch. This NEVER touches the gate's pass/fail — it reads the same promotions the gate produced.
        # The verdict store is a SEPARATE durable handle from this run's trial ledger, so persisting the watch-list
        # never perturbs the deflation math (best-effort: a watch-list write failure can't abort the run).
        rejects_run_id = f"finder:{spec.name}:{utcnow()}"
        rejects_persist = CohortPersist(
            store=self.store,
            run_id=rejects_run_id,
            hypothesis=spec.rationale[:200] if spec.rationale else spec.name,
            source=f"finder:{spec.name}",
            watch_rejects=True,
        )
        promotions = {
            p.candidate_id: p
            for p in promote_cohort(
                self.store, rep_cohort, self.settings.gates, fdr_q=fdr_q, register=False, trials=finder_stats,
                check_holdout=False,  # selection is validation-only; the holdout confirms champions below
                persist=rejects_persist,
            )
        }
        for r in results:
            p = promotions.get(r.config_tag)
            r.promoted = bool(p and p.promoted)  # only a cluster representative can be promoted

        # CHAMPION-ONLY one-shot holdout. The grid screened with include_holdout=False (no variant ever
        # simulated the exam), selection + FDR ran on validation evidence alone — so the untouched, PURGED +
        # EMBARGOED holdout is now evaluated exactly once per PROMOTED cluster representative, as a pure
        # CONFIRMATION. A champion that fails is an honest dead end for this run: the finder never retries the
        # exam with the next-best variant (search-until-pass would silently turn the holdout back into a
        # selection set). Every look is audited as a `holdout_look` event.
        floor = float(self.settings.gates.holdout_min_deflated_sharpe)
        for r in results:
            r.holdout_passed = False
        for r in (r for r in results if r.promoted):
            champion = run_strategy_backtest_detailed(
                spec, dict(r.fitted_params), market, fee_bps=venue.taker_fee_bps,
                fee_schedule=fee_schedule,
                slippage_bps=venue.slippage_bps, impact_bps=venue.impact_bps, alt_by_symbol=alt,
                asset_class_by_symbol=asset_class_by_symbol,
            )  # include_holdout defaults True — this is the single exam look for this champion; charge the
            #    venue's OWN depth (half-spread + impact), not the global 5/50 — same cost model as the screen
            r.metrics = r.metrics.model_copy(
                update={"holdout_deflated_sharpe": champion.metrics.holdout_deflated_sharpe}
            )
            r.holdout_passed = float(r.metrics.holdout_deflated_sharpe) > floor
            r.target_vol = champion.target_vol  # T1: freeze vol anchor from the full backtest (incl. holdout bars)
            try:
                self.store.append_event(
                    actor="master", kind="holdout_look", ref_type="strategy",
                    ref_id=f"{spec.name}:{r.config_tag}",
                    payload={
                        "passed": r.holdout_passed,
                        "holdout_deflated_sharpe": float(r.metrics.holdout_deflated_sharpe),
                    },
                )
            except Exception:  # noqa: BLE001 — audit trail is best-effort; the verdict itself is already set
                pass
        if persist:
            self._persist(spec, results, market, venue)
            # ACTIVATE the rejects watch-list: every screened variant now has a persisted strategy_version
            # (r.version_id), so link each watched reject to its version and open a ZERO-CAPITAL paper track —
            # the SAME SIM machinery survivors use — stamping strategy_version_id back so the Type-II report can
            # join the reject's realized paper P&L to the verdict that rejected it. Observe-only + best-effort:
            # a failure here can never undo a valid promotion (the gate already disposed). Zero capital = no money.
            version_by_tag = {r.config_tag: r.version_id for r in results if r.version_id}
            if version_by_tag:
                from cosmu.master.rejects_lane import link_and_open_rejects_tracks

                link_and_open_rejects_tracks(self.store, rejects_run_id, version_by_tag)

        # Experiment-tracking hook (thin, best-effort): log EVERY screened variant to the registry with its
        # exact fitted config + run seed + data_version + metrics — so the run is comparable to past runs and
        # exactly regenerable — and carry `net_profit` as the continuous forward-P&L SOFT-LABEL that gives the
        # ML ranker a gradient before any variant passes the gate. Never blocks discovery (log_experiments
        # swallows its own failures). data_version is computed from the bars the run actually consumed.
        self._log_experiments(spec, results, market)

        gate_passers = [r for r in results if r.gate_passed]
        leaderboard = sorted(gate_passers, key=lambda r: (r.profit_factor, r.deflated_sharpe), reverse=True)
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
        source: str,
        label: str,
        fee_schedule: dict[str, Decimal] | None = None,
        asset_class_by_symbol: dict[str, str] | None = None,
    ) -> tuple[VariantResult, CohortCandidate, list[float], int] | None:
        """Compile + backtest one variant on REAL bars (with the point-in-time alt-data join so funding/meta-label
        specs are evaluated honestly). Returns (result, cohort-candidate, validation return stream, min per-symbol
        trade count) — or None for an invalid grid point. Gate flags are filled later by `_rescore`, once the
        run-wide honest trial context is known."""
        try:
            compiled = compile_spec(spec, variant.params)
        except ValueError:
            return None
        # include_holdout=False: the SCREEN sees validation evidence only — the untouched holdout is evaluated
        # exactly once, for the promoted champion(s), in find()'s champion-only holdout step. A 256-variant grid
        # simulating the exam per variant was the structural holdout-reuse channel the deep review flagged.
        detailed = run_strategy_backtest_detailed(
            spec, variant.params, market, fee_bps=venue.taker_fee_bps,
            fee_schedule=fee_schedule,
            slippage_bps=venue.slippage_bps, impact_bps=venue.impact_bps,
            alt_by_symbol=alt_by_symbol,
            include_holdout=False,
            asset_class_by_symbol=asset_class_by_symbol,
        )  # price at the SPEC's venue depth — a thin-book venue (Polymarket 30/150, Coinbase 8/60) pays the
        #   wide spread + heavy impact it really would, instead of falling back to the global 5/50
        metrics = detailed.metrics
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
        )
        candidate = CohortCandidate(
            id=variant.config_tag,
            metrics=metrics,
            net_profit=net_profit,
            source=source,
            label=label,
            return_variance=max(1e-6, float(metrics.max_drawdown) ** 2 + 1e-3),
        )
        return result, candidate, list(detailed.val_returns), detailed.min_symbol_trades

    def _rescore(
        self,
        results: list[VariantResult],
        returns_by_tag: dict[str, list[float]],
        trades_by_tag: dict[str, int],
        finder_stats: TrialStats,
        *,
        cohort_pbo: float | None = None,
    ) -> None:
        """Score every variant against the honest trial context `finder_stats` and, when provided, the REAL
        cohort CSCV-PBO + a PER-SYMBOL trade floor. Mutates each result's gate flag, deflated Sharpe, and reasons
        in place."""
        for r in results:
            metrics = r.metrics
            if cohort_pbo is not None:
                metrics = metrics.model_copy(update={"pbo": Decimal(str(round(cohort_pbo, 6)))})
                r.metrics = metrics  # persist the real CSCV-PBO into the recorded backtest
            verdict = score(metrics, self.settings.gates, trials=finder_stats, check_holdout=False)
            reasons = list(verdict.reasons)
            per_symbol_ok = trades_by_tag.get(r.config_tag, 0) >= _MIN_TRADES_PER_SYMBOL
            if not per_symbol_ok:
                reasons.append("min_trades_per_symbol")
            r.deflated_sharpe = float(verdict.ranking_scalar)
            r.reasons = reasons
            r.gate_passed = verdict.passed and per_symbol_ok

    def _finder_trial_stats(self, reps: list[str], results_by_tag: dict[str, VariantResult]) -> TrialStats:
        """The honest multiple-testing context for this run.

        The EFFECTIVE number of independent trials is the number of DISTINCT correlation clusters K — Problem 6's
        dedupe *is* the effective-N. This is the faithful realization of "thread the true trial count, haircut for
        correlation": K is the real count of decorrelated hypotheses tested (>> len(param_space)~7), and a dense
        CORRELATED grid collapses to few clusters so densifying it cannot keep inflating the count (closing the
        'easier as the grid densifies' leak). It is computed per-run from the data alone, so re-running the finder
        on the same bars is deterministic (it does NOT ratchet up with the accumulating global ledger).

        The closed-form average-correlation haircut `N/(1+(N-1)*rho_bar)` (`scorer.effective_trials`) is the wrong
        model for a CLUSTERED grid — most pairs ~0, a few ~1 → a low mean that over-discounts toward 1 — so K, the
        decorrelated-cluster count, is used directly as the effective count. The cross-sectional Sharpe variance
        is taken over the DISTINCT representatives, which (unlike the variance over the whole grid) does NOT
        collapse as near-duplicates pile up."""
        k = max(1, len(reps))
        rep_sharpes = [float(results_by_tag[t].metrics.sharpe_per_obs) for t in reps if t in results_by_tag]
        sr_variance = statistics.pvariance(rep_sharpes) if len(rep_sharpes) > 1 else None
        return TrialStats(count=k, sr_variance=sr_variance, sr_correlation=None)

    # ------------------------------------------------------------------ persistence (config library)

    def _persist(self, spec: StrategySpec, results: list[VariantResult], market: dict[str, list[Bar]], venue) -> None:  # noqa: ANN001 — venue catalog row
        """Write the config library: one strategies row + one strategy_versions row per variant (origin='finder',
        config_tag carried in params), the screen backtest, and — for promoted+holdout-passing variants — a track,
        a `track_opened` event (the paper clock origin + proven-regime passport that master/live_eligibility
        reads, mirroring the evolution loop), and a finder-survivor event. Idempotent: a variant whose code_hash
        already exists is not re-inserted."""
        with self.store.batch() as b:
            strategy_id = self._ensure_strategy(b, spec)
            for r in results:
                if self._version_exists(r.code_hash):
                    continue
                holdout_ok = r.holdout_passed
                promote = r.promoted and holdout_ok
                # Forward-test entrants are born "screened" (badge: Backtest) — they carry only backtest
                # evidence at birth. The paper clock (mark_tracks) promotes them to "paper" once they accrue
                # >= 1 real forward day. status is badge-only; the live gate reads track_opened, not status.
                status = "screened" if r.gate_passed else "killed"
                kill_reason = None if r.gate_passed else (",".join(r.reasons) or "screened_out")
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
                        "killed_at": utcnow() if not r.gate_passed else None,
                        "kill_reason": kill_reason,
                    },
                )
                r.version_id = version_id
                b.insert("backtests", _backtest_row(version_id, r.metrics, r.deflated_sharpe, r.gate_passed, holdout_ok, venue))
                if promote:
                    # Born HONEST: equity = starting_capital, return_pct = 0 (master/tracks.open_paper_track).
                    # The OOS stays in backtests.oos_return; the paper clock advances the forward columns from
                    # real marks, so a promoted-but-unmarked survivor never shows its backtest as forward P&L.
                    _capital = self.settings.sim_track_capital
                    open_paper_track(b, version_id=version_id, starting_capital=_capital, target_vol=r.target_vol)
                    # The paper clock origin. master/live_eligibility reads the FIRST `track_opened` event for
                    # a version as BOTH its maturity-clock origin (paper_clock_origin) and its proven-regime
                    # passport (proven_regimes_for) — exactly as the evolution loop writes it. Without this a promoted
                    # finder survivor would have origin=None → paper_age_days 0 forever → never forward_ready →
                    # never live-armable (paper is HARD-enforced in api/routers/live.py). So a finder survivor
                    # gets the SAME track_opened mark, carrying the regimes its screen proved positive net edge in.
                    proven = sorted(proven_regimes(r.metrics.regime_returns))
                    b.append_event(
                        actor="master",
                        kind="track_opened",
                        ref_type="strategy_version",
                        ref_id=version_id,
                        payload={
                            "deflated_sharpe": round(r.deflated_sharpe, 6),
                            "config_tag": r.config_tag,
                            "origin": "finder",
                            "proven_regimes": proven,
                        },
                    )
                    b.append_event(
                        actor="master",
                        kind="finder_survivor",
                        ref_type="strategy_version",
                        ref_id=version_id,
                        payload={
                            "config_tag": r.config_tag,
                            "profit_factor": round(r.profit_factor, 4),
                            "deflated_sharpe": round(r.deflated_sharpe, 6),
                            "net_profit": round(r.net_profit, 6),
                            "holdout_passed": holdout_ok,
                        },
                    )

        # After the version rows are committed, record each CHAMPION's one-shot holdout verdict through the
        # ledger (separate transaction; idempotent on version_id) so the finder can never re-pick on the holdout.
        # Only promoted representatives ever took the exam (champion-only holdout) — recording a non-promoted
        # gate-passer here would mark its holdout "spent, failed" for an exam it never sat.
        ledger = HoldoutLedger(self.store)
        for r in results:
            if r.version_id and r.promoted and not ledger.consumed(r.version_id):
                ledger.evaluate_once(
                    r.version_id,
                    lambda r=r: {"passed": r.holdout_passed, "deflated_sharpe": round(float(r.metrics.holdout_deflated_sharpe), 6)},
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



# --------------------------------------------------------------------------- correlation / clustering / CSCV


def _corr(a: list[float], b: list[float]) -> float | None:
    """Pearson correlation of two return streams aligned on their common tail. None when undefined."""
    n = min(len(a), len(b))
    if n < 2:
        return None
    aa, bb = a[-n:], b[-n:]
    ma, mb = statistics.fmean(aa), statistics.fmean(bb)
    va = sum((x - ma) ** 2 for x in aa)
    vb = sum((y - mb) ** 2 for y in bb)
    if va <= 0 or vb <= 0:
        return None
    cov = sum((aa[k] - ma) * (bb[k] - mb) for k in range(n))
    return cov / math.sqrt(va * vb)


def _cluster_representatives(
    results: list[VariantResult], returns_by_tag: dict[str, list[float]], *, threshold: float
) -> list[str]:
    """Greedy correlation clustering: walk variants best-first (profit_factor, then per-obs Sharpe) and fold each
    into the first existing representative it correlates with at >= `threshold`; otherwise it starts a new
    cluster as its own representative. Returns the representative config_tags — one DISTINCT hypothesis per
    cluster — so BH-FDR is never fed a grid of near-duplicates. Variants with no usable return stream are
    excluded (they cannot clear the trade gate anyway)."""
    ordered = sorted(
        (r for r in results if len(returns_by_tag.get(r.config_tag, [])) >= 2),
        key=lambda r: (r.profit_factor, float(r.metrics.sharpe_per_obs)),
        reverse=True,
    )
    reps: list[str] = []
    for r in ordered:
        stream = returns_by_tag[r.config_tag]
        if any((_corr(stream, returns_by_tag[rep]) or 0.0) >= threshold for rep in reps):
            continue
        reps.append(r.config_tag)
    return reps


def _cohort_pbo(reps: list[str], returns_by_tag: dict[str, list[float]]) -> float:
    """Real CSCV-PBO across the DISTINCT representatives' return streams (a legitimate, diverse config
    population). < 2 representatives → 1.0 (maximally overfit: CSCV cannot certify a single config), matching
    the gate's convention."""
    streams = [returns_by_tag[t] for t in reps if len(returns_by_tag.get(t, [])) >= 2]
    return cscv_pbo(streams) if len(streams) >= 2 else 1.0


def _with_pbo(candidate: CohortCandidate, pbo: float) -> CohortCandidate:
    """A copy of the candidate whose metrics carry the cohort's real CSCV-PBO, so promote_cohort's pbo gate uses
    the real overfit estimate, not the per-variant proxy."""
    return replace(candidate, metrics=candidate.metrics.model_copy(update={"pbo": Decimal(str(round(pbo, 6)))}))


def _round_trip_cost(metrics: BacktestMetrics, venue) -> float:  # noqa: ANN001
    """A net-of-cost haircut on the variant's return for RANKING the cohort by money: fee bps × number of
    round trips. The backtest already nets fees into each trade's PnL; this is the cohort-level money proxy."""
    fee = float(venue.taker_fee_bps) / 10000.0
    return fee * 2.0 * float(metrics.num_trades)


def _backtest_row(version_id: str, m: BacktestMetrics, deflated: float, passed: bool, holdout_ok: bool, venue) -> dict:  # noqa: ANN001 — venue catalog row
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
