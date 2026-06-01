# intent: the autonomous farming loop — generate a wide population (seeds + mutations + wildcards + pine imports), compile + static-check, cheap deterministic screen, score through the out-of-reach scorer, keep gate-passers as paper sleeves and send the rest to the graveyard with reasons; inputs: seed/cohort config + optional pine scripts; outputs: persisted strategy_versions/backtests/sleeves + CohortSummary; invariants: the scorer/gates stay deterministic and out of the agent's reach, every death records a kill_reason, runs are seeded/reproducible.

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.evolution import mutator
from cosmu.evolution.seeder import seed_population
from cosmu.knowledge.store import Store, utcnow
from cosmu.master.scorer import BacktestMetrics, ScoreVerdict, score
from cosmu.strategy.compiler import compile_spec
from cosmu.strategy.pine import translate_pine
from cosmu.strategy.spec import ParamSpace, StrategySpec


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


@dataclass(frozen=True)
class FarmLoop:
    settings: Settings
    store: Store

    def run_cohort(
        self,
        *,
        seed: int | None = None,
        cohort_size: int | None = None,
        explore_pct: float | None = None,
        pine_scripts: list[str] | None = None,
    ) -> CohortSummary:
        cfg = self.settings.evolution
        seed = cfg.default_seed if seed is None else seed
        size = min(cfg.max_cohort_size, cohort_size or cfg.cohort_size)
        explore = float(cfg.explore_pct) if explore_pct is None else explore_pct
        rng = random.Random(seed)
        cohort_id = hashlib.sha256(f"cohort-{seed}-{size}-{utcnow()}".encode()).hexdigest()[:12]

        self.store.append_event(
            actor="master",
            kind="cohort_started",
            ref_type="cohort",
            ref_id=cohort_id,
            payload={"seed": seed, "cohort_size": size, "explore_pct": explore},
        )

        lanes = {"seed": 0, "exploit": 0, "explore": 0, "pine": 0}
        evaluated: list[Evaluated] = []
        invalid = 0
        parents: list[tuple[str, StrategySpec]] = []
        pine_notes: list[str] = []

        # Wave 0 — seeds + pine imports (these become the parent pool for the exploit lane).
        wave0: list[Candidate] = [
            Candidate(spec=spec, origin="seed", lane="seed", rationale="diverse seed template")
            for spec in seed_population()
        ]
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

        for cand in wave0:
            result, vid = self._evaluate(cand, rng, seed)
            if result is None:
                invalid += 1
                continue
            evaluated.append(result)
            lanes[cand.lane] += 1
            parents.append((vid, cand.spec))

        if not parents:  # pine-only with all-invalid → fall back to seeds
            for spec in seed_population():
                cand = Candidate(spec=spec, origin="seed", lane="seed")
                result, vid = self._evaluate(cand, rng, seed)
                if result:
                    evaluated.append(result)
                    lanes["seed"] += 1
                    parents.append((vid, spec))

        # Waves 1..N — fill the cohort with exploit children and explore wildcards.
        remaining = max(0, size - len(wave0))
        explore_n = round(remaining * explore)
        exploit_n = remaining - explore_n
        parent_specs = [p[1] for p in parents]

        for _ in range(exploit_n):
            pvid, pspec = rng.choice(parents)
            child = mutator.mutate_exploit(pspec, rng)
            cand = Candidate(spec=child.spec, origin="mutation", lane="exploit", operator=child.operator, rationale=child.rationale, parent_vid=pvid)
            result, _vid = self._evaluate(cand, rng, seed)
            if result is None:
                invalid += 1
                continue
            evaluated.append(result)
            lanes["exploit"] += 1

        for _ in range(explore_n):
            child = mutator.wildcard(parent_specs, rng)
            cand = Candidate(spec=child.spec, origin="wildcard", lane="explore", operator=child.operator, rationale=child.rationale)
            result, _vid = self._evaluate(cand, rng, seed)
            if result is None:
                invalid += 1
                continue
            evaluated.append(result)
            lanes["explore"] += 1

        survivors = sorted([e for e in evaluated if e.passed], key=lambda e: e.deflated_sharpe, reverse=True)
        graveyard = sorted([e for e in evaluated if not e.passed], key=lambda e: e.deflated_sharpe, reverse=True)
        generated = len(evaluated)
        killed = len(graveyard)

        self.store.append_event(
            actor="master",
            kind="cohort_completed",
            ref_type="cohort",
            ref_id=cohort_id,
            payload={
                "generated": generated,
                "passed": len(survivors),
                "killed": killed,
                "kill_rate": round(killed / generated, 3) if generated else 0.0,
                "lanes": lanes,
            },
        )

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

    # ------------------------------------------------------------------ internals

    def _evaluate(self, cand: Candidate, rng: random.Random, seed: int) -> tuple[Evaluated | None, str]:
        try:
            params = fit_params(cand.spec)
            compiled = compile_spec(cand.spec, params)
        except ValueError:
            return None, ""  # invalid spec — never persisted, counted as invalid

        metrics = self._screen(cand, compiled.code_hash, seed)
        verdict = score(metrics, self.settings.gates)
        passed = verdict.passed
        status = "paper" if passed else "killed"
        kill_reason = None if passed else ",".join(verdict.reasons) or "screened_out"

        strategy_id = self.store.insert(
            "strategies",
            {"name": cand.spec.name, "thesis": cand.spec.rationale, "origin": cand.origin, "created_at": utcnow()},
        )
        version_id = self.store.insert(
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
        self.store.insert(
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
                "created_at": utcnow(),
            },
        )
        if passed:
            equity = Decimal("100000") * (Decimal("1") + metrics.oos_return)
            self.store.insert(
                "sleeves",
                {
                    "strategy_version_id": version_id,
                    "starting_capital": "100000",
                    "equity": str(equity.quantize(Decimal("0.01"))),
                    "return_pct": str((metrics.oos_return * Decimal("100")).quantize(Decimal("0.01"))),
                    "updated_at": utcnow(),
                },
            )
            self.store.append_event(
                actor="master",
                kind="sleeve_opened",
                ref_type="strategy_version",
                ref_id=version_id,
                payload={"deflated_sharpe": str(verdict.ranking_scalar), "lane": cand.lane},
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
            ),
            version_id,
        )

    def _screen(self, cand: Candidate, code_hash: str, seed: int) -> BacktestMetrics:
        """Cheap deterministic surrogate backtest (stands in for the vectorbt screen).

        Per-candidate determinism comes from the code hash; the latent 'quality' draw
        is wider in the explore lane (high-variance wildcards) and slightly better-centered
        in the exploit lane (mutating known survivors). The real scorer/gates judge it.
        """
        local_seed = (int(code_hash[:12], 16) ^ (seed * 2654435761)) & 0xFFFFFFFF
        r = random.Random(local_seed)
        confluence = len(cand.spec.entry)

        if cand.lane == "explore":
            q = r.gauss(-0.35, 1.4)
        elif cand.lane == "exploit":
            q = r.gauss(-0.05, 0.7)
        elif cand.lane == "pine":
            q = r.gauss(-0.15, 1.0)
        else:  # seed
            q = r.gauss(0.1, 0.7)
        # confluence helps a little but over-fitting many filters hurts robustness
        q += 0.04 * min(confluence, 3) - 0.08 * max(0, confluence - 3)

        sharpe = round(0.7 + 0.7 * q, 4)
        oos_return = round(0.03 + 0.06 * q, 5)
        max_dd = min(0.6, max(0.02, round(0.1 + 0.06 * abs(q) - 0.03 * q, 4)))
        win_rate = min(0.8, max(0.3, round(0.5 + 0.05 * q, 4)))
        num_trades = int(max(6, 22 + r.randint(-12, 58)))
        pbo = min(0.95, max(0.02, round(0.46 - 0.13 * q + r.uniform(0.0, 0.2), 4)))
        folds_pct = min(0.95, max(0.2, round(0.5 + 0.12 * q, 4)))
        holdout = round(0.16 * q + r.gauss(-0.05, 0.2), 4)
        trials = len(cand.spec.param_space) + 10

        return BacktestMetrics(
            oos_return=Decimal(str(oos_return)),
            sharpe=Decimal(str(sharpe)),
            sortino=Decimal(str(round(sharpe * 1.25, 4))),
            max_drawdown=Decimal(str(max_dd)),
            win_rate=Decimal(str(win_rate)),
            num_trades=num_trades,
            pbo=Decimal(str(pbo)),
            trials_counted=trials,
            folds_positive_pct=Decimal(str(folds_pct)),
            holdout_deflated_sharpe=Decimal(str(holdout)),
        )
