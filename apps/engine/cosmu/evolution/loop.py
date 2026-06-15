# intent: the autonomous farming loop — generate a wide population (seeds + mutations + wildcards + pine imports), compile + static-check, cheap deterministic screen, score through the out-of-reach scorer, keep gate-passers as paper tracks and send the rest to the graveyard with reasons; inputs: seed/cohort config + optional pine scripts; outputs: persisted strategy_versions/backtests/tracks + CohortSummary; invariants: the scorer/gates stay deterministic and out of the agent's reach, every death records a kill_reason, runs are seeded/reproducible.

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.alt_join import build_alt_by_symbol
from cosmu.data.backtest import DEFAULT_IMPACT_BPS, DEFAULT_SLIPPAGE_BPS, run_strategy_backtest
from cosmu.data.market import BinanceSpotOHLCVProvider, MarketDataProvider
from cosmu.evolution import mutator
from cosmu.evolution.seeder import seed_population
from cosmu.knowledge.block_registry import blocks_available, find_duplicate, record_version_blocks
from cosmu.knowledge.store import Store, Writer, utcnow
from cosmu.master.fdr import benjamini_hochberg, dsr_pvalue
from cosmu.master.scorer import BacktestMetrics, TrialStats, score
from cosmu.master.trials import register_trial, trial_stats
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
    metrics: BacktestMetrics
    survival_score: float
    proven: list[str]
    # The cost assumptions the screen was scored under (the venue it priced against + its taker fee), carried so
    # _persist can record them on the backtest row and the promotion freeze can pin the gate-time fee model.
    venue_id: str = ""
    fee_bps: float = 0.0
    parent: _Screened | None = None


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


def fdr_culled_vids(evaluated: list[Evaluated], q: float) -> set[str]:
    """Across the WHOLE cohort, apply Benjamini-Hochberg FDR to every candidate's deflated-Sharpe p-value and
    return the version_ids of candidates that CLEARED score()'s per-candidate gate but FAIL FDR control — i.e.
    the ones that must be demoted so they never become fundable. The family is ALL evaluated candidates (FDR
    validity requires every test to count, not just the survivors), but only gate-passers can be culled — a
    candidate the gate already killed has nothing left to demote. Pure + deterministic; the agent can't touch it."""
    if not evaluated:
        return set()
    pvalues = [dsr_pvalue(e.deflated_sharpe) for e in evaluated]
    survives = benjamini_hochberg(pvalues, q=q)
    return {e.version_id for e, ok in zip(evaluated, survives, strict=True) if e.passed and not ok}


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

        # Snapshot the global ledger ONCE, now that every candidate is registered, so all candidates in this cohort
        # are judged against the identical, full trial count (and every prior cohort's trials — two sequential
        # cohorts deflate the second against the first). This is the contract finder.py honors via trial_stats().
        combined = trial_stats(self.store)
        evaluated: list[Evaluated] = []
        vid_by_screened: dict[int, str] = {}   # id(_Screened) → persisted version_id, to resolve child parent_id

        # PHASE 2 — score every screened candidate against the snapshot and persist. One connection + one
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
                result, vid = self._persist(sc, combined, survival, parent_vid, b)
                evaluated.append(result)
                specs_by_vid[vid] = sc.cand.spec
                vid_by_screened[id(sc)] = vid

            # FDR GATE — the multiple-testing correction the funding path depends on. score() judged each
            # candidate in isolation; this judges the COHORT together. A gate-passer that doesn't survive
            # Benjamini-Hochberg across the whole family is demoted HERE — passed_gates→0 (so orchestrator's
            # funding query never funds it), status→killed (reason "fdr"), and its Track removed — so the honest
            # loop can't be gamed by authoring more candidates per tick. Same transaction as the cohort.
            culled = fdr_culled_vids(evaluated, float(self.settings.gates.fdr_q))
            for e in evaluated:
                if e.version_id not in culled:
                    continue
                b.execute("UPDATE backtests SET passed_gates = 0 WHERE strategy_version_id = ? AND kind = 'screen'", (e.version_id,))
                b.execute("UPDATE strategy_versions SET status = 'killed', kill_reason = 'fdr', killed_at = ? WHERE id = ?", (utcnow(), e.version_id))
                b.execute("DELETE FROM tracks WHERE strategy_version_id = ?", (e.version_id,))
                e.passed = False
                if "fdr" not in e.reasons:
                    e.reasons.append("fdr")

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
                    "fdr_culled": len(culled),
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

        metrics, venue = self._screen(cand, compiled.code_hash, seed)
        # THE choke point: every farmed candidate is one more hypothesis the Deflated Sharpe / FDR must deflate
        # against — otherwise authoring more candidates per tick manufactures significance by sheer count.
        register_trial(self.store, float(metrics.sharpe_per_obs), source="farmloop", label=cand.spec.name)
        # Survival model: edge-persistence score (ordering only) + the regimes this screen proved positive in
        # (the strategy's live-eligibility passport). Computed from the SCREEN metrics — never a veto.
        survival_score = round(survival.score_features(features_from_metrics(metrics)), 6)
        proven = sorted(proven_regimes(metrics.regime_returns))
        return _Screened(
            cand=cand, params=params, compiled=compiled, metrics=metrics,
            survival_score=survival_score, proven=proven,
            venue_id=venue.id, fee_bps=float(venue.taker_fee_bps),
        )

    def _persist(self, sc: _Screened, trials: TrialStats, survival, parent_vid: str | None, b: Writer) -> tuple[Evaluated, str]:  # noqa: ANN001
        """Score a screened candidate against the cohort-wide trial snapshot and persist its strategy / version /
        screen-backtest (and, for a gate-passer, its paper track). Returns the Evaluated row + version_id."""
        cand = sc.cand
        metrics = sc.metrics
        compiled = sc.compiled
        params = sc.params
        # Deflate against the FULL global trial count (this cohort + all history), not ~len(param_space).
        verdict = score(metrics, self.settings.gates, trials=trials)
        passed = verdict.passed
        # Born "screened" (badge: Backtest) — backtest evidence only at birth. The paper clock promotes to
        # "paper" once >= 1 real forward day accrues. status is badge-only; the live gate reads track_opened.
        status = "screened" if passed else "killed"
        kill_reason = None if passed else ",".join(verdict.reasons) or "screened_out"
        survival_score = sc.survival_score
        proven = sc.proven

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
        b.insert(
            "backtests",
            {
                "strategy_version_id": version_id,
                "kind": "screen",
                "oos_return": str(metrics.oos_return),
                "sharpe": str(metrics.sharpe),
                "sortino": str(metrics.sortino),
                "deflated_sharpe": str(verdict.ranking_scalar),
                "max_dd": str(metrics.max_drawdown),
                "win_rate": str(metrics.win_rate),
                "num_trades": metrics.num_trades,
                "pbo": str(metrics.pbo),
                "trials_counted": metrics.trials_counted,
                "regime_label": "mixed",
                "folds_positive": int(metrics.folds_positive_pct * 6),
                "passed_gates": int(passed),
                "holdout_passed": int(metrics.holdout_deflated_sharpe > self.settings.gates.holdout_min_deflated_sharpe),
                # Survival-model feature row persisted alongside the verdict so the ranker trains on the SAME
                # vector it scores with (no more zero-filling skew/kurtosis/n_obs/regime breadth at train time).
                "sharpe_per_obs": str(metrics.sharpe_per_obs),
                "skew": str(metrics.skew),
                "kurtosis": str(metrics.kurtosis),
                "n_obs": metrics.n_obs,
                "regime_spread": sum(1 for pnl in metrics.regime_returns.values() if pnl > 0),
                # Cost assumptions this screen was scored under (venue + taker fee + default slippage/impact) —
                # frozen into the promotion so live can detect a venue repricing the edge was never proven through.
                "venue_id": sc.venue_id,
                "fee_bps": str(sc.fee_bps),
                "slippage_bps": str(DEFAULT_SLIPPAGE_BPS),
                "impact_bps": str(DEFAULT_IMPACT_BPS),
                "created_at": utcnow(),
            },
        )
        if passed:
            # Seed at the STANDARDIZED standalone track size (sim_track_capital — what the funder deploys),
            # never the $100k pool: the forward clock recomputes return_pct as marked_value / starting_capital,
            # so a $100k denominator under a $1k funded position reads ~-99% forever. Same as finder/arms.
            track_capital = self.settings.sim_track_capital
            equity = track_capital * (Decimal("1") + metrics.oos_return)
            b.insert(
                "tracks",
                {
                    "strategy_version_id": version_id,
                    "starting_capital": str(track_capital),
                    "equity": str(equity.quantize(Decimal("0.01"))),
                    "return_pct": str((metrics.oos_return * Decimal("100")).quantize(Decimal("0.01"))),
                    "updated_at": utcnow(),
                },
            )
            b.append_event(
                actor="master",
                kind="track_opened",
                ref_type="strategy_version",
                ref_id=version_id,
                payload={
                    "deflated_sharpe": str(verdict.ranking_scalar),
                    "lane": cand.lane,
                    "survival_score": survival_score,
                    "survival_trained": survival.trained,
                    "proven_regimes": proven,
                },
            )
            # ADDITIVE lifecycle-trace audit marks (see master/lifecycle.py): the screen passed and the paper
            # clock now begins. Write-only journaling on the same transaction — never gates/promotes/arms.
            b.append_event(actor="master", kind="screened_passed", ref_type="strategy_version", ref_id=version_id, payload={"lane": cand.lane, "proven_regimes": proven})
            b.append_event(actor="master", kind="paper_started", ref_type="strategy_version", ref_id=version_id, payload={"lane": cand.lane, "proven_regimes": proven})

        return (
            Evaluated(
                version_id=version_id,
                name=cand.spec.name,
                origin=cand.origin,
                lane=cand.lane,
                deflated_sharpe=float(verdict.ranking_scalar),
                oos_return_pct=float(metrics.oos_return) * 100,
                passed=passed,
                reasons=verdict.reasons,
                survival_score=survival_score,
                survival_trained=survival.trained,
                proven_regimes=proven,
            ),
            version_id,
        )

    def _screen(self, cand: Candidate, code_hash: str, seed: int):  # noqa: ANN201 — (BacktestMetrics, venue catalog row)
        """Cheap real-data screen over Binance spot bars. Returns the metrics AND the venue it priced against (so
        the persist path records the gate-time cost assumptions).

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
        venue = default_catalog().venue_for(cand.spec.universe.venues)   # price against the spec's OWN venue (one source of fee truth)
        metrics = run_strategy_backtest(
            cand.spec,
            fit_params(cand.spec),
            market,
            fee_bps=venue.taker_fee_bps,
            alt_by_symbol=self._alt_by_symbol(cand.spec, market),
        )
        return metrics, venue

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
