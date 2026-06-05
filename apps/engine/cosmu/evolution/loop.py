# intent: the autonomous farming loop — generate a wide population (seeds + mutations + wildcards + pine imports), compile + static-check, cheap deterministic screen, score through the out-of-reach scorer, keep gate-passers as forward-test tracks and send the rest to the graveyard with reasons; inputs: seed/cohort config + optional pine scripts; outputs: persisted strategy_versions/backtests/tracks + CohortSummary; invariants: the scorer/gates stay deterministic and out of the agent's reach, every death records a kill_reason, runs are seeded/reproducible.

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from decimal import Decimal

from cosmu.config.feature_registry import feature_names
from cosmu.config.settings import Settings
from cosmu.data.altdata import StoreBackedAltProvider
from cosmu.data.backtest import PRICE_FEATURES, align_asof, run_strategy_backtest
from cosmu.data.market import BinanceSpotOHLCVProvider, MarketDataProvider
from cosmu.evolution import mutator
from cosmu.evolution.seeder import seed_population
from cosmu.knowledge.store import Store, Writer, utcnow
from cosmu.master.fdr import benjamini_hochberg, dsr_pvalue
from cosmu.master.scorer import BacktestMetrics, score
from cosmu.ml.regime import proven_regimes
from cosmu.ml.survival import features_from_metrics, load_survival_model
from cosmu.spine.universe import enabled_universe
from cosmu.spine.venue import default_catalog
from cosmu.strategy.compiler import compile_spec
from cosmu.strategy.pine import translate_pine
from cosmu.strategy.spec import ParamSpace, StrategySpec


# How many trailing alt-data points to pull per (symbol, feature) before the point-in-time as-of join.
# Generous: covers >1yr at any ingest frequency, so the per-bar align_asof always has the full window it
# needs (align_asof, not this slice, does the no-look-ahead selection). Bounded so a runaway series can't
# blow up memory.
_ALT_HISTORY_LIMIT = 100_000


@dataclass
class Candidate:
    spec: StrategySpec
    origin: str
    lane: str
    operator: str | None = None
    rationale: str | None = None
    parent_vid: str | None = None


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
        evaluated: list[Evaluated] = []
        # version_id → its spec, so the self-improvement flywheel (graveyard memory + Curator skills) can record
        # each death/win and distill survivors AFTER the cohort transaction commits (no nested writers).
        specs_by_vid: dict[str, StrategySpec] = {}
        invalid = 0
        parents: list[tuple[str, StrategySpec]] = []
        pine_notes: list[str] = []

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

        # One connection + one transaction for the whole cohort.
        with self.store.batch() as b:
            b.append_event(
                actor="master",
                kind="cohort_started",
                ref_type="cohort",
                ref_id=cohort_id,
                payload={"seed": seed, "cohort_size": size, "explore_pct": explore},
            )

            for cand in wave0:
                result, vid = self._evaluate(cand, b, rng, seed, survival)
                if result is None:
                    invalid += 1
                    continue
                evaluated.append(result)
                specs_by_vid[vid] = cand.spec
                lanes[cand.lane] += 1
                parents.append((vid, cand.spec))

            # Waves 1..N — fill the cohort with exploit children and explore wildcards.
            remaining = max(0, size - len(wave0))
            explore_n = round(remaining * explore)
            exploit_n = remaining - explore_n
            parent_specs = [p[1] for p in parents]

            live_specs = [p[1] for p in parents] if parents else []

            for _ in range(exploit_n):
                pvid, pspec = rng.choice(parents)
                child = mutator.mutate_exploit(pspec, rng)
                cand = Candidate(spec=child.spec, origin="mutation", lane="exploit", operator=child.operator, rationale=child.rationale, parent_vid=pvid)
                if not self._novelty_ok(cand.spec, live_specs):
                    invalid += 1
                    continue
                result, vid = self._evaluate(cand, b, rng, seed, survival)
                if result is None:
                    invalid += 1
                    continue
                evaluated.append(result)
                specs_by_vid[vid] = cand.spec
                lanes["exploit"] += 1

            for _ in range(explore_n):
                child = mutator.wildcard(parent_specs, rng)
                cand = Candidate(spec=child.spec, origin="wildcard", lane="explore", operator=child.operator, rationale=child.rationale)
                if not self._novelty_ok(cand.spec, live_specs):
                    invalid += 1
                    continue
                result, vid = self._evaluate(cand, b, rng, seed, survival)
                if result is None:
                    invalid += 1
                    continue
                evaluated.append(result)
                specs_by_vid[vid] = cand.spec
                lanes["explore"] += 1

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

    # ------------------------------------------------------------------ internals

    def _novelty_ok(self, spec: StrategySpec, live_specs: list[StrategySpec]) -> bool:
        """Quick novelty gate: reject specs too similar to recent dead-ends or the live population."""
        try:
            from cosmu.knowledge.memory import novelty_gate

            ok, _reason = novelty_gate(spec, self.store, live_specs=live_specs)
            return ok
        except Exception:  # noqa: BLE001 — novelty is advisory; never blocks what the Gate should judge
            return True

    def _evaluate(self, cand: Candidate, b: Writer, rng: random.Random, seed: int, survival) -> tuple[Evaluated | None, str]:  # noqa: ANN001
        try:
            params = fit_params(cand.spec)
            compiled = compile_spec(cand.spec, params)
        except ValueError:
            return None, ""  # invalid spec — never persisted, counted as invalid

        metrics = self._screen(cand, compiled.code_hash, seed)
        verdict = score(metrics, self.settings.gates)
        passed = verdict.passed
        status = "forward_test" if passed else "killed"
        kill_reason = None if passed else ",".join(verdict.reasons) or "screened_out"

        # Survival model: edge-persistence score (ordering only) + the regimes this screen proved positive in
        # (the strategy's live-eligibility passport). Computed from the SCREEN metrics — never a veto.
        survival_score = round(survival.score_features(features_from_metrics(metrics)), 6)
        proven = sorted(proven_regimes(metrics.regime_returns))

        strategy_id = b.insert(
            "strategies",
            {"name": cand.spec.name, "thesis": cand.spec.rationale, "origin": cand.origin, "created_at": utcnow()},
        )
        version_id = b.insert(
            "strategy_versions",
            {
                "strategy_id": strategy_id,
                "parent_id": cand.parent_vid,
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
                "created_at": utcnow(),
            },
        )
        if passed:
            equity = Decimal("100000") * (Decimal("1") + metrics.oos_return)
            b.insert(
                "tracks",
                {
                    "strategy_version_id": version_id,
                    "starting_capital": "100000",
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

    def _screen(self, cand: Candidate, code_hash: str, seed: int) -> BacktestMetrics:
        """Cheap real-data screen over Binance spot bars.

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
        return run_strategy_backtest(
            cand.spec,
            fit_params(cand.spec),
            market,
            fee_bps=venue.taker_fee_bps,
            alt_by_symbol=self._alt_by_symbol(cand.spec, market),
        )

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

    def _alt_feature_universe(self) -> set[str]:
        """The leading-signal (alt-data) feature names the screen joins point-in-time: every ENABLED
        feature_registry name MINUS the ones the backtest computes itself from bars (PRICE_FEATURES). Read
        from the registry AT RUNTIME (cached per loop), so a feature the data agent registers + ingests is
        wired here automatically — this loop never hard-codes the key list, and the price/alt split has a
        single source of truth (cosmu.data.backtest.PRICE_FEATURES)."""
        if "alt_universe" not in self._cache:
            self._cache["alt_universe"] = feature_names() - PRICE_FEATURES
        return self._cache["alt_universe"]

    def _alt_by_symbol(self, spec: StrategySpec, market: dict[str, list]) -> dict | None:
        """Build the per-symbol point-in-time alt-data join for EVERY registered leading-signal feature this
        spec uses (funding_rate, fear_greed, macro, sentiment, …) — not just funding. The feature universe
        comes from the feature_registry at runtime (`_alt_feature_universe`); StoreBackedAltProvider routes
        each name to its stored series (provider + market-wide keying) and `align_asof` joins it bar-by-bar
        as-of (each bar gets the latest value with available_at <= bar.ts — NO look-ahead). A feature with no
        provider route or no stored data is simply omitted: the backtest reads None and its condition can't
        fire (honest — never a fabricated value, never a skipped/crashed bar). The perp-funding carry leg
        (`spec.funding_feature`) reads the same join. Offline / no alt store → None (price-only, unchanged).
        Never raises."""
        used = {c.feature.name for c in [*spec.entry, *spec.exit.signal_exits]}
        funding = getattr(spec, "funding_feature", None)
        if funding:
            used.add(funding)
        names = used & self._alt_feature_universe()
        if not names:
            return None
        try:
            provider = StoreBackedAltProvider(self._alt_store())
        except Exception:  # noqa: BLE001 — no alt store available → price-only screen, never abort
            return None
        out: dict[str, dict[str, dict[str, float]]] = {}
        for symbol, bars in market.items():
            feats: dict[str, dict[str, float]] = {}
            for name in names:
                try:
                    points = provider.fetch_series(symbol, name, limit=_ALT_HISTORY_LIMIT)
                except Exception:  # noqa: BLE001 — a missing/erroring series is just no data for that feature
                    points = []
                aligned = align_asof(points, bars)
                if aligned:
                    feats[name] = aligned
            if feats:
                out[symbol] = feats
        return out or None


def _binance_symbols(spec: StrategySpec, enabled_venues: set[str], enabled_classes: set[str]) -> list[str]:
    # The strategy must target crypto on Binance AND the operator must have that venue/class enabled
    # in the global universe gate. A disabled venue/class yields no symbols → no trades → killed.
    if "crypto" not in spec.universe.asset_classes or "binance" not in spec.universe.venues:
        return []
    if "crypto" not in enabled_classes or "binance" not in enabled_venues:
        return []
    return ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]


def _bar_limit(spec: StrategySpec) -> int:
    if spec.horizon.bar_size == "1d":
        return 1000
    if spec.horizon.bar_size == "4h":
        return 1000
    return 1500
