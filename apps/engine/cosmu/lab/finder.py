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
from cosmu.data.backtest import run_strategy_backtest
from cosmu.data.market import Bar, BinanceSpotOHLCVProvider, MarketDataProvider
from cosmu.evolution.loop import fit_params
from cosmu.evolution.seeder import seed_orb_fvg_spec
from cosmu.knowledge.store import Store, Writer, utcnow
from cosmu.master.cohort import Candidate as CohortCandidate
from cosmu.master.cohort import promote_cohort
from cosmu.master.holdout import HoldoutLedger
from cosmu.master.scorer import BacktestMetrics, score
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
_REAL_SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")


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
    version_id: str | None = None
    promoted: bool = False
    holdout_passed: bool = False


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


def build_grid(spec: StrategySpec, *, max_variants: int = _MAX_VARIANTS) -> list[Variant]:
    """Cartesian product of each param's grid points → many fitted Versions. Deterministically truncated to
    `max_variants` (stride sampling, not a head slice, so the truncated grid still spans the space)."""
    keys = sorted(spec.param_space)
    axes = [_grid_values(spec.param_space[k]) for k in keys]
    combos = list(itertools.product(*axes))
    if len(combos) > max_variants:
        stride = len(combos) / max_variants
        combos = [combos[int(i * stride)] for i in range(max_variants)]
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

        combos = list(itertools.product(*axes))
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
        venues, classes = enabled_universe(self.store)
        if "crypto" not in spec.universe.asset_classes or "binance" not in spec.universe.venues:
            return []
        if "crypto" not in classes or "binance" not in venues:
            return []
        return list(_REAL_SYMBOLS)

    def _market(self, spec: StrategySpec) -> dict[str, list[Bar]]:
        provider = self.market_data or BinanceSpotOHLCVProvider()
        limit = 1500 if spec.horizon.bar_size == "1h" else 1000
        out: dict[str, list[Bar]] = {}
        for symbol in self._symbols(spec):
            try:
                out[symbol] = provider.fetch_bars(symbol, spec.horizon.bar_size, limit=limit)
            except Exception:  # noqa: BLE001 — offline/no-network: skip the symbol, degrade to whatever cached
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
        """Run the full Finder pass for one seed spec. Steps: build the grid → screen every variant on REAL bars
        → register each as a trial → rank by profit_factor within gate-passers → TWO-PASS REFINEMENT (finer grid
        around top survivors) → promote via the deterministic cohort gate (significance + BH-FDR) →
        WFO/holdout-validate the promoted leaders ONCE before they enter the config library. Deterministic and
        LLM-free."""
        spec = spec or seed_orb_fvg_spec()
        market = self._market(spec)
        grid = build_grid(spec, max_variants=max_variants)
        venue = default_catalog().venue("binance")

        results: list[VariantResult] = []
        cohort: list[CohortCandidate] = []
        for variant in grid:
            try:
                compiled = compile_spec(spec, variant.params)
            except ValueError:
                continue  # an invalid grid point (e.g. degenerate range) is skipped, never persisted
            metrics = run_strategy_backtest(spec, variant.params, market, fee_bps=venue.taker_fee_bps)
            verdict = score(metrics, self.settings.gates)
            net_profit = float(metrics.oos_return) - _round_trip_cost(metrics, venue)
            results.append(
                VariantResult(
                    config_tag=variant.config_tag,
                    code_hash=compiled.code_hash,
                    metrics=metrics,
                    deflated_sharpe=float(verdict.ranking_scalar),
                    profit_factor=float(metrics.profit_factor),
                    net_profit=net_profit,
                    gate_passed=verdict.passed,
                    reasons=verdict.reasons,
                )
            )
            cohort.append(
                CohortCandidate(
                    id=variant.config_tag,
                    metrics=metrics,
                    net_profit=net_profit,
                    source="finder",
                    label=f"{spec.name}:{variant.config_tag}",
                    return_variance=max(1e-6, float(metrics.max_drawdown) ** 2 + 1e-3),
                )
            )

        # TWO-PASS REFINEMENT: take the top coarse-pass gate-passers and run a finer grid around their
        # parameter neighborhoods. The gate still protects — refinement only finds better configurations
        # within the already-validated structural region, never overfits.
        if two_pass:
            coarse_passers = sorted(
                [r for r in results if r.gate_passed],
                key=lambda r: (r.profit_factor, r.deflated_sharpe),
                reverse=True,
            )[:_REFINE_TOP_N]
            if coarse_passers:
                survivor_variants = []
                for r in coarse_passers:
                    for v in grid:
                        if v.config_tag == r.config_tag:
                            survivor_variants.append(v)
                            break
                fine_grid = refine_around(spec, survivor_variants)
                existing_tags = {r.config_tag for r in results}
                for variant in fine_grid:
                    if variant.config_tag in existing_tags:
                        continue
                    try:
                        compiled = compile_spec(spec, variant.params)
                    except ValueError:
                        continue
                    metrics = run_strategy_backtest(spec, variant.params, market, fee_bps=venue.taker_fee_bps)
                    verdict = score(metrics, self.settings.gates)
                    net_profit = float(metrics.oos_return) - _round_trip_cost(metrics, venue)
                    results.append(
                        VariantResult(
                            config_tag=variant.config_tag,
                            code_hash=compiled.code_hash,
                            metrics=metrics,
                            deflated_sharpe=float(verdict.ranking_scalar),
                            profit_factor=float(metrics.profit_factor),
                            net_profit=net_profit,
                            gate_passed=verdict.passed,
                            reasons=verdict.reasons,
                        )
                    )
                    cohort.append(
                        CohortCandidate(
                            id=variant.config_tag,
                            metrics=metrics,
                            net_profit=net_profit,
                            source="finder_refine",
                            label=f"{spec.name}:refine:{variant.config_tag}",
                            return_variance=max(1e-6, float(metrics.max_drawdown) ** 2 + 1e-3),
                        )
                    )

        # The cohort gate registers EVERY variant as a trial (deflation validity) and promotes only those that
        # clear significance AND survive BH-FDR — never a raw top-of-leaderboard pick.
        promotions = {p.candidate_id: p for p in promote_cohort(self.store, cohort, self.settings.gates, fdr_q=fdr_q)}
        for r in results:
            p = promotions.get(r.config_tag)
            r.promoted = bool(p and p.promoted)

        # WFO / one-shot holdout BEFORE promotion: a promoted variant must ALSO clear the untouched holdout
        # (data/backtest reserves the last fifth; holdout_deflated_sharpe > the configured floor) so the finder
        # can never promote on in-sample PF alone — every winner survives out-of-sample too.
        floor = float(self.settings.gates.holdout_min_deflated_sharpe)
        for r in results:
            r.holdout_passed = float(r.metrics.holdout_deflated_sharpe) > floor
        if persist:
            self._persist(spec, results, market)

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

    # ------------------------------------------------------------------ persistence (config library)

    def _persist(self, spec: StrategySpec, results: list[VariantResult], market: dict[str, list[Bar]]) -> None:
        """Write the config library: one strategies row + one strategy_versions row per variant (origin='finder',
        config_tag carried in params), the screen backtest, and — for promoted+holdout-passing variants — a track
        + a survivor event. Idempotent: a variant whose code_hash already exists is not re-inserted."""
        with self.store.batch() as b:
            strategy_id = self._ensure_strategy(b, spec)
            for r in results:
                if self._version_exists(r.code_hash):
                    continue
                holdout_ok = r.holdout_passed
                promote = r.promoted and holdout_ok
                status = "forward_test" if promote else ("screened" if r.gate_passed else "killed")
                kill_reason = None if r.gate_passed else (",".join(r.reasons) or "screened_out")
                params = {**self._params_for(spec, r), "config_tag": r.config_tag}
                compiled = compile_spec(spec, self._params_for(spec, r))
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
                b.insert("backtests", _backtest_row(version_id, r.metrics, r.deflated_sharpe, r.gate_passed, holdout_ok))
                if promote:
                    equity = Decimal("100000") * (Decimal("1") + r.metrics.oos_return)
                    b.insert(
                        "tracks",
                        {
                            "strategy_version_id": version_id,
                            "starting_capital": "100000",
                            "equity": str(equity.quantize(Decimal("0.01"))),
                            "return_pct": str((r.metrics.oos_return * Decimal("100")).quantize(Decimal("0.01"))),
                            "updated_at": utcnow(),
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

        # After the version rows are committed, record each gate-passer's one-shot holdout verdict through the
        # ledger (separate transaction; idempotent on version_id) so the finder can never re-pick on the holdout.
        ledger = HoldoutLedger(self.store)
        for r in results:
            if r.version_id and r.gate_passed and not ledger.consumed(r.version_id):
                ledger.evaluate_once(
                    r.version_id,
                    lambda r=r: {"passed": r.holdout_passed, "deflated_sharpe": round(float(r.metrics.holdout_deflated_sharpe), 6)},
                )

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

    def _params_for(self, spec: StrategySpec, r: VariantResult) -> dict[str, float]:
        # Recover the variant's fitted params from the grid (deterministic for the config_tag); cheaper than
        # carrying them on VariantResult and keeps the result row lean.
        for variant in build_grid(spec):
            if variant.config_tag == r.config_tag:
                return variant.params
        return fit_params(spec)


def _round_trip_cost(metrics: BacktestMetrics, venue) -> float:  # noqa: ANN001
    """A net-of-cost haircut on the variant's return for RANKING the cohort by money: fee bps × number of
    round trips. The backtest already nets fees into each trade's PnL; this is the cohort-level money proxy."""
    fee = float(venue.taker_fee_bps) / 10000.0
    return fee * 2.0 * float(metrics.num_trades)


def _backtest_row(version_id: str, m: BacktestMetrics, deflated: float, passed: bool, holdout_ok: bool) -> dict:
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
