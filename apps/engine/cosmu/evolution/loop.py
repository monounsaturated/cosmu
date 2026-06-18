# intent: the autonomous farming loop — generate a wide population (seeds + mutations + wildcards + pine imports), compile + static-check, cheap deterministic screen, score through the out-of-reach scorer, keep gate-passers as paper tracks and send the rest to the graveyard with reasons; inputs: seed/cohort config + optional pine scripts; outputs: persisted strategy_versions/backtests/tracks + CohortSummary; invariants: the scorer/gates stay deterministic and out of the agent's reach, every death records a kill_reason, runs are seeded/reproducible.

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.alt_join import build_alt_by_symbol
from cosmu.data.backtest import (
    DEFAULT_IMPACT_BPS,
    DEFAULT_SLIPPAGE_BPS,
    metrics_for_run,
    run_strategy_backtest_detailed,
)
from cosmu.data.market import BinanceSpotOHLCVProvider, MarketDataProvider
from cosmu.evolution import mutator
from cosmu.evolution.seeder import seed_population
from cosmu.knowledge.block_registry import blocks_available, find_duplicate, record_version_blocks
from cosmu.knowledge.store import Store, Writer, tracks_has_cell_columns, utcnow
from cosmu.master.cohort import Candidate as CohortCandidate
from cosmu.master.cohort import promote_brut
from cosmu.master.live_eligibility import cell_id
from cosmu.master.scorer import BacktestMetrics
from cosmu.master.screen_universe import build_cost_context
from cosmu.master.tracks import open_paper_track
from cosmu.master.trade_floor import MIN_TRADES_PER_SYMBOL
from cosmu.ml.regime import proven_regimes
from cosmu.ml.survival import features_from_metrics, load_survival_model
from cosmu.spine.universe import enabled_universe
from cosmu.spine.venue import default_catalog
from cosmu.strategy.blocks import combo_hash as strategy_combo_hash
from cosmu.strategy.compiler import CompiledStrategy, compile_spec
from cosmu.strategy.pine import translate_pine
from cosmu.strategy.spec import ParamSpace, StrategySpec


@dataclass
class Candidate:
    spec: StrategySpec
    origin: str
    lane: str
    operator: str | None = None
    rationale: str | None = None


@dataclass
class _Screened:
    """A candidate after the cheap real-data SCREEN but BEFORE scoring/persistence. Screening + global-trial
    registration happen for the WHOLE cohort first; only then is the trial ledger snapshotted and every candidate
    scored against the same full count. `parent` is the screened wave-0 candidate an exploit child was mutated
    from — resolved to a real version_id at persist time (children are persisted after their parents)."""

    cand: Candidate
    params: dict[str, float]
    compiled: CompiledStrategy
    metrics: BacktestMetrics  # POOLED display metrics; the BRUT verdict is per cell (see per_symbol_runs below)
    survival_score: float
    proven: list[str]
    # The validation per-bar return stream from the cheap screen (BacktestResult.val_returns). Kept for the
    # survival-feature row + display. The BRUT gate no longer clusters/CSCV-PBOs across mutants — each cell is
    # judged on its OWN streams (per_symbol_runs below).
    val_returns: list[float] = field(default_factory=list)
    # The per-symbol standalone validation breakdown (BacktestResult.per_symbol) the screen computes — carried so
    # _persist writes the first-class backtest_symbols rows (the queryable per-(strat,symbol,venue) unit of truth).
    per_symbol: dict[str, dict[str, float]] = field(default_factory=dict)
    # The full per-symbol RUNS (each cell's OWN bar_returns + fold_returns + trades) — the streams the BRUT gate
    # scores each cell on, via metrics_for_run. NEVER re-pool by reusing val.* per cell.
    per_symbol_runs: dict = field(default_factory=dict)
    # Each cell's OWN buy-and-hold over its validation window (the brut beat-B&H benchmark per cell).
    per_symbol_buy_and_hold: dict[str, float] = field(default_factory=dict)
    # The cost assumptions the screen was scored under (the venue it priced against + its taker fee + the SAME
    # venue's market depth the backtest charged), carried so _persist records the EXACT values on the backtest
    # row and the promotion freeze pins the gate-time cost model — never the global default (depth is per-venue).
    venue_id: str = ""
    fee_bps: float = 0.0
    slippage_bps: float = float(DEFAULT_SLIPPAGE_BPS)
    impact_bps: float = float(DEFAULT_IMPACT_BPS)
    parent: _Screened | None = None
    pre_kill: str | None = None  # kill reason injected before _persist (e.g. per-symbol floor)
    # The BRUT per-cell verdicts {symbol: _BrutCell}, filled in run_cohort before _persist. Each cell judged alone.
    cells: dict = field(default_factory=dict)


@dataclass
class Evaluated:
    version_id: str
    name: str
    origin: str
    lane: str
    deflated_sharpe: float
    oos_return_pct: float
    passed: bool
    reasons: list[str]
    # The survival model's edge-persistence score in [0,1] and whether a trained model produced it. This ONLY
    # orders which gate-survivors get full validation first (prioritize compute) — it NEVER changes `passed`.
    survival_score: float = 0.0
    survival_trained: bool = False
    proven_regimes: list[str] = field(default_factory=list)


@dataclass
class CohortSummary:
    cohort_id: str
    seed: int
    generated: int
    invalid: int
    killed: int
    passed: int
    kill_rate: float
    lanes: dict[str, int]
    pine_imported: int
    survivors: list[Evaluated] = field(default_factory=list)
    graveyard: list[Evaluated] = field(default_factory=list)
    pine_notes: list[str] = field(default_factory=list)
    # Candidates skipped because their combo_hash matched an already-tested hypothesis (block registry).
    # A duplicate is NOT a new trial — skipping it protects the multiple-testing budget. 0 when the
    # registry tables are absent (pre-migration prod) — the loop then behaves exactly as before.
    duplicates: int = 0


def fit_params(spec: StrategySpec) -> dict[str, float]:
    """Deterministic stand-in for the IS optimizer: midpoint of each param range."""
    out: dict[str, float] = {}
    for key, ps in spec.param_space.items():
        out[key] = _midpoint(ps)
    return out


def _midpoint(ps: ParamSpace) -> float:
    if ps.kind == "choice" and ps.choices:
        return float(ps.choices[len(ps.choices) // 2])
    if ps.lo is not None and ps.hi is not None:
        mid = (ps.lo + ps.hi) / 2
        return float(round(mid)) if ps.kind == "int" else round(mid, 6)
    return 0.0


@dataclass
class _BrutCell:
    """ONE brut cell (this candidate × one symbol × its venue), judged on its OWN streams. `metrics` is built by
    metrics_for_run from this symbol's per_symbol_run (own bar_returns + fold_returns); `passed` is the locked
    stats gate on those streams AND the per-cell trade floor. `holdout_passed` is this cell's own one-shot holdout
    confirmation."""

    symbol: str
    venue_id: str
    metrics: BacktestMetrics
    deflated_sharpe: float
    trades: int
    passed: bool
    reasons: list[str] = field(default_factory=list)
    holdout_passed: bool = False


# Minimum trades on a SCREENED symbol — the cheap per-cell thinness pre-screen (the larger min_trades=30 floor is
# enforced per cell inside promote_brut, on the cell's OWN num_trades). A strategy that books 30 trades all on ONE
# of six symbols is no longer carried by a pooled count: under brut each cell stands alone. Single source of truth
# in master/trade_floor.py (shared with the finder sweep).
_MIN_TRADES_PER_SYMBOL = MIN_TRADES_PER_SYMBOL
# The BRUT per-cell min-trades floor on the single combo's OWN trades (set as gates.min_trades for promote_brut).
_BRUT_MIN_TRADES = 30


@dataclass(frozen=True)
class FarmLoop:
    settings: Settings
    store: Store
    market_data: MarketDataProvider | None = None
    _cache: dict = field(default_factory=dict, compare=False)

    def _enabled(self) -> tuple[set[str], set[str]]:
        """Global universe gate (which venues/asset classes are enabled), read once per loop."""
        if "venues" not in self._cache:
            venues, classes = enabled_universe(self.store)
            self._cache["venues"] = venues
            self._cache["classes"] = classes
        return self._cache["venues"], self._cache["classes"]

    def run_cohort(
        self,
        *,
        seed: int | None = None,
        cohort_size: int | None = None,
        explore_pct: float | None = None,
        pine_scripts: list[str] | None = None,
        extra_seeds: list[StrategySpec] | None = None,
    ) -> CohortSummary:
        cfg = self.settings.evolution
        seed = cfg.default_seed if seed is None else seed
        size = min(cfg.max_cohort_size, cohort_size or cfg.cohort_size)
        explore = float(cfg.explore_pct) if explore_pct is None else explore_pct
        rng = random.Random(seed)
        cohort_id = hashlib.sha256(f"cohort-{seed}-{size}-{utcnow()}".encode()).hexdigest()[:12]
        self._enabled()  # warm the universe gate once, before the write transaction opens
        # Load the survival model on the outcomes that exist BEFORE this cohort writes any rows (point-in-time:
        # the ranker never sees its own cohort's labels). Cold-start => trained=False + heuristic ordering.
        survival = load_survival_model(self.store)

        lanes = {"seed": 0, "chat": 0, "exploit": 0, "explore": 0, "pine": 0}
        # version_id → its spec, so the self-improvement flywheel (graveyard memory + Curator skills) can record
        # each death/win and distill survivors AFTER the cohort transaction commits (no nested writers).
        specs_by_vid: dict[str, StrategySpec] = {}
        invalid = 0
        pine_notes: list[str] = []

        # Block registry: probe availability ONCE, outside any write transaction (an absent table inside a
        # Postgres tx would abort the whole cohort batch). When the 2026-06-11 migration hasn't run yet this
        # is False and everything below no-ops — the cohort behaves exactly as before.
        registry_on = blocks_available(self.store)
        self._cache["blocks_on"] = registry_on
        duplicates = 0
        seen_combos: set[str] = set()

        def _is_duplicate(spec: StrategySpec, lane: str) -> bool:
            """Structural dedup on the spec's combo_hash. NEVER skips the seed lane (seeds are the cohort's
            baseline parent pool by design — they anchor the in-cohort set instead, so a child identical to a
            seed IS deduped). A hypothesis already in the registry — even a KILLED one — was already tested:
            re-screening it re-spends the multiple-testing budget without adding information."""
            nonlocal duplicates
            if not registry_on:
                return False
            combo = strategy_combo_hash(spec)
            if lane == "seed":
                seen_combos.add(combo)
                return False
            if combo in seen_combos or find_duplicate(self.store, combo) is not None:
                duplicates += 1
                return True
            seen_combos.add(combo)
            return False

        # Wave 0 — seeds + chat-authored briefs + pine imports (the parent pool for the exploit lane).
        wave0: list[Candidate] = [
            Candidate(spec=spec, origin="seed", lane="seed", rationale="diverse seed template")
            for spec in seed_population()
        ]
        for spec in extra_seeds or []:
            wave0.append(Candidate(spec=spec, origin="chat", lane="chat", operator="chat_author", rationale="human-authored brief"))
        for src in pine_scripts or []:
            tr = translate_pine(src)
            pine_notes.extend(tr.notes)
            wave0.append(
                Candidate(
                    spec=tr.spec,
                    origin="pine",
                    lane="pine",
                    operator="pine_import",
                    rationale="; ".join(tr.notes)[:240] or "translated from pine",
                )
            )

        # PHASE 1 — generate + cheap-screen the WHOLE cohort and register EVERY candidate in the global trial
        # ledger (source="farmloop") BEFORE anyone is scored. Mirrors lab/finder.py: the Deflated Sharpe must
        # deflate against the true running hypothesis count (this cohort + all history), not just ~len(param_space)
        # of one candidate's params. No DB writes here except the trial ledger, so persistence stays one batch.
        screened: list[_Screened] = []
        parents: list[_Screened] = []   # the screened wave-0 candidates = the exploit lane's parent pool

        for cand in wave0:
            if _is_duplicate(cand.spec, cand.lane):
                continue
            sc = self._screen_and_register(cand, seed, survival)
            if sc is None:
                invalid += 1
                continue
            screened.append(sc)
            lanes[cand.lane] += 1
            parents.append(sc)

        # Waves 1..N — fill the cohort with exploit children and explore wildcards.
        remaining = max(0, size - len(wave0))
        explore_n = round(remaining * explore)
        exploit_n = remaining - explore_n
        parent_specs = [sc.cand.spec for sc in parents]
        live_specs = [sc.cand.spec for sc in parents] if parents else []

        for _ in range(exploit_n):
            parent = rng.choice(parents)
            child = mutator.mutate_exploit(parent.cand.spec, rng)
            cand = Candidate(spec=child.spec, origin="mutation", lane="exploit", operator=child.operator, rationale=child.rationale)
            if not self._novelty_ok(cand.spec, live_specs):
                invalid += 1
                continue
            if _is_duplicate(cand.spec, cand.lane):
                continue
            sc = self._screen_and_register(cand, seed, survival)
            if sc is None:
                invalid += 1
                continue
            sc.parent = parent
            screened.append(sc)
            lanes["exploit"] += 1

        for _ in range(explore_n):
            child = mutator.wildcard(parent_specs, rng)
            cand = Candidate(spec=child.spec, origin="wildcard", lane="explore", operator=child.operator, rationale=child.rationale)
            if not self._novelty_ok(cand.spec, live_specs):
                invalid += 1
                continue
            if _is_duplicate(cand.spec, cand.lane):
                continue
            sc = self._screen_and_register(cand, seed, survival)
            if sc is None:
                invalid += 1
                continue
            screened.append(sc)
            lanes["explore"] += 1

        # ---- BRUT per-cell scoring: judge each (candidate × symbol) cell ON ITS OWN data ----
        # No clustering, no cohort CSCV-PBO inject, no cross-mutant FDR. Each candidate's cells are scored alone via
        # promote_brut (the locked DSR/PBO math untouched; only the INPUT — one cell — and trials_counted change).
        # The FarmLoop screens each mutant ONCE at its midpoint params (no per-candidate param grid), so the
        # per-combo param-search count is 1 → trials=1 in metrics_for_run. A candidate with NO passing cell is
        # killed (the brut equivalent of the old gate-fail), still recording its per-cell rows for visibility.
        for sc in screened:
            sc.cells = self._score_cells(sc)

        # CHAMPION-ONLY one-shot holdout, PER CELL (pure compute, before the persist batch). The screen ran
        # include_holdout=False; for each candidate with ≥1 passing cell, re-run WITH the embargoed holdout once and
        # confirm EACH passing cell on ITS OWN holdout run — a pure CONFIRMATION, never a retry. A cell that fails
        # its own holdout is dropped from funding (its track is not opened).
        holdout_floor = float(self.settings.gates.holdout_min_deflated_sharpe)
        for sc in screened:
            if not any(c.passed for c in sc.cells.values()):
                continue
            holdout_runs, holdout_bh = self._champion_holdout_runs(sc.cand.spec, sc.params)
            for sym, cell in sc.cells.items():
                if not cell.passed:
                    continue
                h_run = holdout_runs.get(sym)
                cell_h_dsr = (
                    float(metrics_for_run(h_run, trials=1, buy_and_hold=holdout_bh.get(sym, 0.0), holdout_run=h_run).holdout_deflated_sharpe)
                    if h_run is not None else 0.0
                )
                cell.holdout_passed = cell_h_dsr > holdout_floor
                cell.metrics = cell.metrics.model_copy(update={"holdout_deflated_sharpe": Decimal(str(round(cell_h_dsr, 6)))})

        evaluated: list[Evaluated] = []
        vid_by_screened: dict[int, str] = {}   # id(_Screened) → persisted version_id, to resolve child parent_id

        # PHASE 2 — persist every screened candidate with its per-cell brut verdicts. One connection + one
        # transaction for the whole cohort. Parents are persisted before their children (wave-0 first), so an
        # exploit child's parent_id always references an already-inserted row (the FK holds).
        with self.store.batch() as b:
            b.append_event(
                actor="master",
                kind="cohort_started",
                ref_type="cohort",
                ref_id=cohort_id,
                payload={"seed": seed, "cohort_size": size, "explore_pct": explore},
            )

            for sc in screened:
                parent_vid = vid_by_screened.get(id(sc.parent)) if sc.parent is not None else None
                result, vid = self._persist(sc, survival, parent_vid, b)
                evaluated.append(result)
                specs_by_vid[vid] = sc.cand.spec
                vid_by_screened[id(sc)] = vid

            # ORDER the gate-survivors by the survival model's edge-persistence score (descending) — this is the
            # validation queue: which gate-passers get scarce full-validation compute FIRST. It is a re-sort of
            # the SAME survivors (the gate already decided who passed); the model never adds or removes anyone.
            # Deterministic tie-break on deflated_sharpe so equal scores (e.g. cold-start) stay reproducible.
            survivors = sorted(
                [e for e in evaluated if e.passed],
                key=lambda e: (e.survival_score, e.deflated_sharpe),
                reverse=True,
            )
            graveyard = sorted([e for e in evaluated if not e.passed], key=lambda e: e.deflated_sharpe, reverse=True)
            generated = len(evaluated)
            killed = len(graveyard)

            b.append_event(
                actor="master",
                kind="cohort_completed",
                ref_type="cohort",
                ref_id=cohort_id,
                payload={
                    "generated": generated,
                    "passed": len(survivors),
                    "killed": killed,
                    "duplicates": duplicates,
                    "kill_rate": round(killed / generated, 3) if generated else 0.0,
                    "lanes": lanes,
                    "survival_model": {"trained": survival.trained, "backend": survival.backend, "n_labels": survival.n_labels, "auroc": survival.auroc},
                    "survival_ranking": [{"version_id": e.version_id, "name": e.name, "score": e.survival_score, "trained": e.survival_trained} for e in survivors[:24]],
                },
            )

        # SELF-IMPROVEMENT FLYWHEEL (runs AFTER the cohort transaction commits — no nested writer): record every
        # death + win into the graveyard/research RAG, distill gate-passing survivors into reusable skills, and
        # re-grade the skill set. Best-effort: a memory/curation hiccup must never fail a cohort the Gate already
        # judged (the scorer/Gate remain the sole authority over what survives).
        self._record_flywheel(evaluated, specs_by_vid)

        return CohortSummary(
            cohort_id=cohort_id,
            seed=seed,
            generated=generated,
            invalid=invalid,
            killed=killed,
            passed=len(survivors),
            kill_rate=round(killed / generated, 4) if generated else 0.0,
            lanes=lanes,
            pine_imported=lanes["pine"],
            survivors=survivors[:24],
            graveyard=graveyard[:16],
            pine_notes=pine_notes[:12],
            duplicates=duplicates,
        )

    def _record_flywheel(self, evaluated: list[Evaluated], specs_by_vid: dict[str, StrategySpec]) -> None:
        """Persist deaths + wins into long-term memory and distill survivors into skills, then re-grade. Imported
        lazily so the loop stays importable even if the flywheel modules change. Never raises into the cohort."""
        try:
            from cosmu.knowledge.memory import GraveyardMemory
            from cosmu.lab.curator import distill_skill, grade_skills

            memory = GraveyardMemory(self.store)
            distilled = False
            for ev in evaluated:
                spec = specs_by_vid.get(ev.version_id)
                if spec is None:
                    continue
                memory.remember(spec, ev)
                if ev.passed:
                    distill_skill(self.store, spec, ev)
                    distilled = True
            if distilled:
                grade_skills(self.store)
        except Exception:  # noqa: BLE001 — the flywheel is additive; it never blocks a gated cohort
            pass

        # FREEZE each gate-passing survivor into its strategy_promotions record — the single source of truth live
        # reads to replicate the verdict (frozen params + hash, fee model, registry version, regimes). Post-commit
        # (the version + track_opened rows are durable now) and best-effort: a freeze hiccup never unwinds a
        # promotion the deterministic Gate already disposed.
        try:
            from cosmu.master.promotion import freeze_promotion

            for ev in evaluated:
                if ev.passed and ev.version_id:
                    freeze_promotion(self.store, ev.version_id)
        except Exception:  # noqa: BLE001 — freeze is durable bookkeeping, never blocks a gated cohort
            pass

    # ------------------------------------------------------------------ internals

    def _novelty_ok(self, spec: StrategySpec, live_specs: list[StrategySpec]) -> bool:
        """Quick novelty gate: reject specs too similar to recent dead-ends or the live population."""
        try:
            from cosmu.knowledge.memory import novelty_gate

            ok, _reason = novelty_gate(spec, self.store, live_specs=live_specs)
            return ok
        except Exception:  # noqa: BLE001 — novelty is advisory; never blocks what the Gate should judge
            return True

    def _screen_and_register(self, cand: Candidate, seed: int, survival) -> _Screened | None:  # noqa: ANN001
        """Compile + cheap-screen one candidate and register it in the GLOBAL trial ledger (source="farmloop").
        Returns the screened bundle, or None for an invalid spec (counted as invalid, never persisted). No row is
        written except the trial — scoring + persistence happen later, once the whole cohort is registered, so every
        candidate deflates against the same full count."""
        try:
            params = fit_params(cand.spec)
            compiled = compile_spec(cand.spec, params)
        except ValueError:
            return None  # invalid spec — never persisted, counted as invalid

        metrics, venue, min_symbol_trades, val_returns, per_symbol, per_symbol_runs, per_symbol_bh = self._screen(cand, compiled.code_hash, seed)
        # BRUT: a per-combo cell is NOT part of any cross-combo family, so the autonomous loop NO LONGER registers
        # a global trial here (the old register_trial fed the pooled FDR/DSR deflation this lane has dropped, and
        # would otherwise also contaminate the POOLED research lanes' global ledger with autonomous mutants). Each
        # cell deflates on its OWN per-combo evidence (trials=1 — the loop screens a mutant once, no param grid).
        # Survival model: edge-persistence score (ordering only) + the regimes this screen proved positive in
        # (the strategy's live-eligibility passport). Computed from the SCREEN metrics — never a veto.
        survival_score = round(survival.score_features(features_from_metrics(metrics)), 6)
        proven = sorted(proven_regimes(metrics.regime_returns))
        # Per-cell trade floor pre-screen: require >= _MIN_TRADES_PER_SYMBOL trades on the THINNEST screened symbol
        # (the cheap thinness gate; the larger min_trades=30 floor is enforced per cell in promote_brut). A mutant
        # with no symbol clearing the floor is killed pre-paper. min_symbol_trades is 0 when no symbol traded.
        pre_kill = "min_trades_per_symbol" if min_symbol_trades < _MIN_TRADES_PER_SYMBOL else None
        return _Screened(
            cand=cand, params=params, compiled=compiled, metrics=metrics,
            survival_score=survival_score, proven=proven,
            val_returns=val_returns, per_symbol=per_symbol,
            per_symbol_runs=per_symbol_runs, per_symbol_buy_and_hold=per_symbol_bh,
            venue_id=venue.id, fee_bps=float(venue.taker_fee_bps),
            slippage_bps=float(venue.slippage_bps), impact_bps=float(venue.impact_bps),
            pre_kill=pre_kill,
        )

    def _score_cells(self, sc: _Screened) -> dict[str, _BrutCell]:
        """Build ONE _BrutCell per (symbol, venue) from this candidate's per-symbol RUNS, judged on its OWN data.

        NO RE-POOLING: each cell's metrics come from sc.per_symbol_runs[sym] (own bar_returns AND own
        fold_returns) + the per-symbol B&H + trials=1 (the loop screens a mutant once — no per-candidate param
        grid). promote_brut scores each cell alone (TrialStats(count=1), the min-trades floor on the cell's OWN
        trades). A cell passes iff promoted AND it cleared the per-cell trade floor AND the candidate wasn't
        pre-killed for thinness."""
        cell_metrics: dict[str, BacktestMetrics] = {}
        for sym, run in (sc.per_symbol_runs or {}).items():
            cell_metrics[sym] = metrics_for_run(run, trials=1, buy_and_hold=sc.per_symbol_buy_and_hold.get(sym, 0.0))
        candidates = [CohortCandidate(id=sym, metrics=m, net_profit=0.0, source="farmloop") for sym, m in cell_metrics.items()]
        promotions = {p.candidate_id: p for p in promote_brut(candidates, self.settings.gates, min_trades=_BRUT_MIN_TRADES)}
        out: dict[str, _BrutCell] = {}
        for sym, m in cell_metrics.items():
            p = promotions[sym]
            trades = m.num_trades
            reasons = list(p.reasons)
            floor_ok = trades >= _MIN_TRADES_PER_SYMBOL and not sc.pre_kill
            if trades < _MIN_TRADES_PER_SYMBOL:
                reasons.append("min_trades_per_symbol")
            out[sym] = _BrutCell(
                symbol=sym, venue_id=sc.venue_id, metrics=m,
                deflated_sharpe=p.deflated_sharpe_prob, trades=trades,
                passed=p.promoted and floor_ok, reasons=reasons,
            )
        return out

    def _persist(self, sc: _Screened, survival, parent_vid: str | None, b: Writer) -> tuple[Evaluated, str]:  # noqa: ANN001
        """Persist a screened candidate with its BRUT per-cell verdicts: strategy / version / screen-backtest, one
        backtest_symbols row PER CELL (carrying the cell's OWN pass/fail in `verdict`), and — for each cell that
        passed the gate AND confirmed on its OWN holdout — a per-CELL paper track + a cell-keyed track_opened.
        Returns the Evaluated row + version_id."""
        cand = sc.cand
        metrics = sc.metrics  # POOLED display metrics; the brut verdict is per cell (sc.cells)
        compiled = sc.compiled
        params = sc.params
        # BRUT: the candidate is SCREENED (kept on /lab) iff ANY of its cells passed; KILLED otherwise. No pooled
        # score(), no breadth/generalize gate, no FDR — each cell judged ALONE on its own data (sc.cells).
        passing = [c for c in sc.cells.values() if c.passed]
        passed = bool(passing)
        status = "screened" if passed else "killed"
        kill_reason = None if passed else (sc.pre_kill or "no_passing_cell")
        survival_score = sc.survival_score
        proven = sc.proven
        # The best cell's deflated Sharpe is the display ranking number for this version (the brut verdict is per
        # cell). On a fully-killed candidate this is the max over cells (or 0 when no cell traded).
        best_dsr = max((c.deflated_sharpe for c in sc.cells.values()), default=0.0)

        strategy_id = b.insert(
            "strategies",
            {"name": cand.spec.name, "thesis": cand.spec.rationale, "origin": cand.origin, "created_at": utcnow()},
        )
        version_id = b.insert(
            "strategy_versions",
            {
                "strategy_id": strategy_id,
                "parent_id": parent_vid,
                "spec": cand.spec.model_dump(mode="json"),
                "generated_code": compiled.code,
                "code_hash": compiled.code_hash,
                "params": params,
                "mutation_operator": cand.operator,
                "mutation_rationale": cand.rationale,
                "origin": cand.origin,
                "status": status,
                "created_at": utcnow(),
                "killed_at": utcnow() if not passed else None,
                "kill_reason": kill_reason,
            },
        )
        # Block lineage: content-address the spec's building blocks inside the SAME transaction as the
        # version row (registry probed once per cohort; absent tables → flag off → no statement runs here).
        if self._cache.get("blocks_on"):
            record_version_blocks(b, version_id, cand.spec)
        bt_id = b.insert(
            "backtests",
            {
                "strategy_version_id": version_id,
                "kind": "screen",
                "oos_return": str(metrics.oos_return),
                "sharpe": str(metrics.sharpe),
                "sortino": str(metrics.sortino),
                "deflated_sharpe": str(round(best_dsr, 6)),
                "max_dd": str(metrics.max_drawdown),
                "win_rate": str(metrics.win_rate),
                "num_trades": metrics.num_trades,
                "pbo": str(metrics.pbo),
                "trials_counted": metrics.trials_counted,
                "regime_label": "mixed",
                "folds_positive": int(metrics.folds_positive_pct * 6),
                "passed_gates": int(passed),
                # BRUT: holdout_passed iff ANY cell confirmed on its OWN holdout (the per-cell exam).
                "holdout_passed": int(any(c.passed and c.holdout_passed for c in sc.cells.values())),
                # Survival-model feature row persisted alongside the verdict so the ranker trains on the SAME
                # vector it scores with (no more zero-filling skew/kurtosis/n_obs/regime breadth at train time).
                "sharpe_per_obs": str(metrics.sharpe_per_obs),
                "skew": str(metrics.skew),
                "kurtosis": str(metrics.kurtosis),
                "n_obs": metrics.n_obs,
                "regime_spread": sum(1 for pnl in metrics.regime_returns.values() if pnl > 0),
                # Cost assumptions this screen was scored under (venue + taker fee + the SAME venue's market
                # depth the backtest charged) — frozen into the promotion so live can detect a venue repricing
                # the edge was never proven through. Record the values charged, never the global default.
                "venue_id": sc.venue_id,
                "fee_bps": str(sc.fee_bps),
                "slippage_bps": str(sc.slippage_bps),
                "impact_bps": str(sc.impact_bps),
                "created_at": utcnow(),
            },
        )
        # First-class per-CELL rows — the autonomous loop populates the queryable per-(strat,symbol,venue) unit of
        # truth identically to the finder sweep. venue_id = the fee axis; `verdict` carries the BRUT per-cell
        # pass/fail ('pass' iff this cell cleared the gate on its OWN data, else its own kill reason — the funder
        # fans out a paper track per 'pass' cell). NEVER a pooled or sibling-compared label — each cell judged ALONE.
        # NOTE: a single sc.venue_id is correct only because this loop is crypto-only today (every symbol is Binance
        # spot). The finder, which screens equity+HL legs, stamps the per-symbol venue map. When this loop's universe
        # widens, carry venue_id_by_symbol onto the cells or it will mislabel the fee axis.
        for _sym, _pm in (sc.per_symbol or {}).items():
            cell = sc.cells.get(_sym)
            cell_verdict = "pass" if (cell and cell.passed) else ((",".join(cell.reasons) or "fail") if cell else None)
            b.insert("backtest_symbols", {
                "backtest_id": bt_id, "strategy_version_id": version_id, "symbol": _sym, "venue_id": sc.venue_id,
                "return_pct": str(_pm.get("return", 0.0)), "sharpe": str(_pm.get("sharpe", 0.0)),
                "max_drawdown": str(_pm.get("max_drawdown", 0.0)), "trades": int(_pm.get("trades", 0)),
                "verdict": cell_verdict, "created_at": utcnow(),
            })
        # PER-CELL TRACKS: one standalone paper track per cell that passed the gate AND confirmed on its OWN
        # holdout. Born HONEST (equity=starting_capital, return_pct=0); the paper clock advances forward columns
        # from real marks. track_opened is keyed to the CELL (cell_id) so master/live_eligibility reads this cell's
        # OWN clock origin + proven-regime passport — never a sibling cell's. Each cell stands alone.
        track_capital = self.settings.sim_track_capital
        # Pre-migration tracks still has UNIQUE(strategy_version_id) — a version with >1 passing cell would collide
        # on the 2nd insert. Until the held migration lands, degrade to ONE version-wide track per version; after it,
        # every cell funds its own (UNIQUE(version,symbol,venue)). Schema-adaptive, crash-proof on both schemas.
        _cell_cols = tracks_has_cell_columns(self.store)
        _opened_version_wide = False
        for _sym, cell in sc.cells.items():
            if not (cell.passed and cell.holdout_passed):
                continue
            if not _cell_cols and _opened_version_wide:
                continue
            open_paper_track(b, version_id=version_id, starting_capital=track_capital,
                             symbol=cell.symbol, venue_id=cell.venue_id, store=self.store)
            if not _cell_cols:
                _opened_version_wide = True
            cell_proven = sorted(proven_regimes(cell.metrics.regime_returns))
            cid = cell_id(version_id, cell.symbol, cell.venue_id)
            b.append_event(
                actor="master", kind="track_opened", ref_type="strategy_version", ref_id=cid,
                payload={
                    "deflated_sharpe": round(cell.deflated_sharpe, 6), "lane": cand.lane,
                    "symbol": cell.symbol, "venue_id": cell.venue_id,
                    "survival_score": survival_score, "survival_trained": survival.trained,
                    "proven_regimes": cell_proven,
                },
            )
            # ADDITIVE lifecycle-trace audit marks: the cell's screen passed and the paper clock now begins.
            b.append_event(actor="master", kind="screened_passed", ref_type="strategy_version", ref_id=cid, payload={"lane": cand.lane, "symbol": cell.symbol, "proven_regimes": cell_proven})
            b.append_event(actor="master", kind="paper_started", ref_type="strategy_version", ref_id=cid, payload={"lane": cand.lane, "symbol": cell.symbol, "proven_regimes": cell_proven})

        return (
            Evaluated(
                version_id=version_id,
                name=cand.spec.name,
                origin=cand.origin,
                lane=cand.lane,
                deflated_sharpe=float(best_dsr),
                oos_return_pct=float(metrics.oos_return) * 100,
                passed=passed,
                reasons=([kill_reason] if kill_reason else []),
                survival_score=survival_score,
                survival_trained=survival.trained,
                proven_regimes=proven,
            ),
            version_id,
        )

    def _screen(self, cand: Candidate, code_hash: str, seed: int):  # noqa: ANN201 — (BacktestMetrics, venue, min_symbol_trades, val_returns, per_symbol)
        """Cheap real-data screen over Binance spot bars. Returns the metrics, the venue it priced against (so
        the persist path records the gate-time cost assumptions), the per-symbol trade MINIMUM (the smallest
        validation trade count across the screened symbols — the true per-symbol breadth, see _screen_and_register),
        AND the validation per-bar return STREAM (BacktestResult.val_returns). The cohort uses that stream to
        cluster correlated mutants into DISTINCT representatives and to compute the REAL cohort CSCV-PBO — the
        same evidence the finder sweep dedupes + certifies on (lab/finder.py).

        The screen is deterministic for a fixed bar cache and fitted params. It is still the
        cheap tier, but its return/drawdown/trade-count fields now come from actual venue OHLCV
        and fee-net fills instead of a candidate-shape surrogate.
        """
        del code_hash, seed
        provider = self.market_data or BinanceSpotOHLCVProvider()
        enabled_venues, enabled_classes = self._enabled()
        symbols = _binance_symbols(cand.spec, enabled_venues, enabled_classes)
        market = {
            symbol: provider.fetch_bars(symbol, cand.spec.horizon.bar_size, limit=_bar_limit(cand.spec))
            for symbol in symbols
        }
        catalog = default_catalog()
        venue = catalog.venue_for(cand.spec.universe.venues)   # price against the spec's OWN venue (one source of fee truth)
        # Per-symbol cost + calendar context from the SHARED source the finder also uses (master/screen_universe),
        # so the FarmLoop and the Strategy Finder can never diverge on cost. This loop is CRYPTO-ONLY today —
        # _binance_symbols feeds only Binance crypto symbols, so build_cost_context finds no equity/HL leg and
        # returns (None, None, None, None); the backtest then uses the scalar venue fee/depth below and this call
        # is byte-identical to the prior crypto path. The day the loop's universe widens, the per-venue fee +
        # depth + calendar flow automatically — no second implementation to keep in sync (audit landmine closed).
        fee_schedule, depth_schedule, asset_class_by_symbol, _venue_id_by_symbol = build_cost_context(cand.spec, market, catalog)
        # Detailed backtest: `.metrics` is BYTE-IDENTICAL to run_strategy_backtest (which is a thin .metrics
        # wrapper over this), so no verdict drifts — but it also exposes per-symbol trade counts so the
        # per-symbol floor can test the true MINIMUM-per-symbol (finder.py semantic), not a pooled total.
        result = run_strategy_backtest_detailed(
            cand.spec,
            fit_params(cand.spec),
            market,
            fee_bps=venue.taker_fee_bps,
            fee_schedule=fee_schedule,
            # Charge the SPEC's own venue depth (half-spread + size-aware impact), not the global 5/50 — a
            # thin-book venue (Polymarket 30/150, Coinbase 8/60, Hyperliquid 6/60) pays the real cost it would
            # live, so a strategy can't pass the screen on costs it'd never survive on its actual venue. The
            # depth_schedule (per-symbol) overrides this scalar only when a cross-asset leg is present (None here).
            slippage_bps=venue.slippage_bps,
            impact_bps=venue.impact_bps,
            depth_schedule=depth_schedule,
            alt_by_symbol=self._alt_by_symbol(cand.spec, market),
            # SELECTION sees VALIDATION evidence only — the untouched, purged+embargoed holdout is evaluated
            # exactly once per gate+FDR survivor in run_cohort's champion-only holdout step (mirrors lab/finder).
            # Screening every candidate WITH the holdout (the old default) made the always-on loop SELECT on the
            # exam — the structural holdout-reuse channel the gate-integrity review flagged.
            include_holdout=False,
            asset_class_by_symbol=asset_class_by_symbol,
        )
        return (
            result.metrics, venue, result.min_symbol_trades, list(result.val_returns),
            result.per_symbol, result.per_symbol_runs, result.per_symbol_buy_and_hold,
        )

    def _champion_holdout_runs(self, spec: StrategySpec, params: dict[str, float]) -> tuple[dict, dict[str, float]]:
        """The one-shot UNTOUCHED holdout for a SELECTED champion, PER CELL: re-run the full backtest WITH the
        embargoed holdout (the screen ran include_holdout=False) and return (per_symbol_holdout_runs,
        per_symbol_buy_and_hold) — same market / venue / cost model the screen priced against, so the exam is
        charged identically. The brut gate confirms EACH passing cell on ITS OWN holdout run. Pure compute, no DB
        write. Called once per candidate with a passing cell (a fresh version per cohort → structurally one-shot)."""
        provider = self.market_data or BinanceSpotOHLCVProvider()
        enabled_venues, enabled_classes = self._enabled()
        symbols = _binance_symbols(spec, enabled_venues, enabled_classes)
        market = {s: provider.fetch_bars(s, spec.horizon.bar_size, limit=_bar_limit(spec)) for s in symbols}
        catalog = default_catalog()
        venue = catalog.venue_for(spec.universe.venues)
        fee_schedule, depth_schedule, asset_class_by_symbol, _venue_id_by_symbol = build_cost_context(spec, market, catalog)
        result = run_strategy_backtest_detailed(
            spec, params, market, fee_bps=venue.taker_fee_bps,
            fee_schedule=fee_schedule,
            slippage_bps=venue.slippage_bps, impact_bps=venue.impact_bps,
            depth_schedule=depth_schedule,
            alt_by_symbol=self._alt_by_symbol(spec, market),
            include_holdout=True,
            asset_class_by_symbol=asset_class_by_symbol,
        )
        return result.per_symbol_holdout_runs, result.per_symbol_buy_and_hold

    def _alt_store(self):  # noqa: ANN202 — AltDataStore | PgAltDataStore
        """The point-in-time alt-data store, chosen the SAME way ingest/api do: postgres URL → PgAltDataStore
        over the knowledge Store, else the JSONL AltDataStore. Cached per loop."""
        if "alt_store" not in self._cache:
            url = self.settings.database_url
            if url.startswith("postgres://") or url.startswith("postgresql://"):
                from cosmu.data.altdata import PgAltDataStore

                self._cache["alt_store"] = PgAltDataStore(self.store)
            else:
                from cosmu.data.altdata import AltDataStore

                self._cache["alt_store"] = AltDataStore()
        return self._cache["alt_store"]

    def _alt_by_symbol(self, spec: StrategySpec, market: dict[str, list]) -> dict | None:
        """Build the per-symbol point-in-time alt-data join for every leading-signal feature this spec uses —
        entry/exit conditions, the perp-funding carry leg, AND the secondary meta-label model's features.
        Delegates to the shared `build_alt_by_symbol` (one join, also used by the Finder sweep), so the cohort
        screen and the sweep evaluate a funding/meta spec identically. Offline / no alt store → None (price-only,
        unchanged). Never raises."""
        return build_alt_by_symbol(self._alt_store(), spec, market)


# THE crypto screen universe — the symbols every Binance gate-lane candidate is screened against. The funder
# reads this too (orchestrator/loop.py): a survivor paper-trades ONLY on a symbol its gate evidence covered.
CRYPTO_SCREEN_UNIVERSE: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT")


def _binance_symbols(spec: StrategySpec, enabled_venues: set[str], enabled_classes: set[str]) -> list[str]:
    # The strategy must target crypto on Binance AND the operator must have that venue/class enabled
    # in the global universe gate. A disabled venue/class yields no symbols → no trades → killed.
    if "crypto" not in spec.universe.asset_classes or "binance" not in spec.universe.venues:
        return []
    if "crypto" not in enabled_classes or "binance" not in enabled_venues:
        return []
    return list(CRYPTO_SCREEN_UNIVERSE)


def _bar_limit(spec: StrategySpec) -> int:
    if spec.horizon.bar_size == "1d":
        return 1000
    if spec.horizon.bar_size == "4h":
        return 1000
    return 1500
