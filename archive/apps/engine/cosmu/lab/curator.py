# intent: the CURATOR of the self-improvement flywheel — turn a gate-passing Version into a reusable,
# parameterized SKILL recipe (a spec TEMPLATE + the named features/composable modules it used), store it in the
# `skills` table, then GRADE every skill by the downstream OOS success of the Versions derived from it and PRUNE
# low-grade skills (set pruned_at). Live skills feed back into authoring as priors. inputs: a Store + a survivor
# Version row/Evaluated; outputs: persisted skills rows + grades. invariants: distilling is deterministic and
# KEYLESS/OFFLINE (no model, no network); a recipe carries STRUCTURE only — thresholds stay as param_space
# ranges (no magic numbers leak); grading reads REAL persisted backtests (the deterministic scorer's verdicts) —
# the Curator never scores or promotes anything itself, it only curates what the Gate already judged.

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from cosmu.knowledge.memory import GraveyardMemory, embed, structure_fingerprint, _encode_embedding
from cosmu.knowledge.store import Store, utcnow
from cosmu.strategy.spec import StrategySpec

# A skill whose graded edge-persistence falls below this (once it has enough derived evidence) is pruned. It is
# a quality FLOOR, not a magic threshold on any market quantity: a skill that no longer yields gate-passers is
# dead weight in the prior set. Configurable via grade_skills(min_grade=...).
DEFAULT_MIN_GRADE = 0.34
MIN_DERIVED_FOR_PRUNE = 2  # don't prune a skill until at least this many Versions have been derived from it


@dataclass(frozen=True)
class SkillRecord:
    id: str
    name: str
    grade: float
    success_count: int
    lineage: str
    recipe_summary: str
    created_at: str


def _recipe_from_spec(spec: StrategySpec, *, version_id: str) -> dict[str, Any]:
    """The reusable, parameterized recipe: the structural fingerprint + the spec TEMPLATE (param_space ranges
    kept, fitted values dropped) so a future Version can be authored from it without re-deriving structure and
    without inheriting any magic numbers."""
    fingerprint = structure_fingerprint(spec)
    # The template is the spec with its param_space (ranges, not fitted values) intact — the optimizer refits.
    template = spec.model_dump(mode="json")
    return {
        "structure": fingerprint,
        "template": template,
        "from_version": version_id,
        "features": fingerprint["entry_features"],
        "modules": fingerprint["setup_modules"],
        "asset_classes": fingerprint["asset_classes"],
        "bar_size": fingerprint["bar_size"],
    }


def _recipe_summary(recipe: dict[str, Any]) -> str:
    feats = ", ".join(recipe.get("features", [])) or "-"
    mods = ", ".join(recipe.get("modules", [])) or "-"
    classes = "/".join(recipe.get("asset_classes", [])) or "-"
    return f"{classes} {recipe.get('bar_size', '?')} · features [{feats}] · modules [{mods}]"


def _skill_name(spec: StrategySpec, recipe: dict[str, Any]) -> str:
    feats = "+".join(recipe.get("features", [])[:3]) or "structure"
    classes = "/".join(recipe.get("asset_classes", [])) or "any"
    return f"{classes}:{feats}"


def distill_skill(store: Store, spec: StrategySpec, evaluated: Any, *, lineage: str | None = None) -> str:  # noqa: ANN401
    """Turn ONE gate-passing Version into a reusable SKILL. Deterministic + keyless: the recipe is the spec
    template + its named features/modules. Idempotent per skill NAME (re-distilling the same structure bumps
    success_count instead of duplicating). Returns the skill id. Caller must only pass gate-passers — the
    Curator records what the Gate already judged, it never re-judges."""
    if not getattr(evaluated, "passed", False):
        raise ValueError("distill_skill expects a gate-passing survivor (LLM proposes, the Gate disposes)")
    recipe = _recipe_from_spec(spec, version_id=evaluated.version_id)
    name = _skill_name(spec, recipe)
    lineage = lineage or f"{evaluated.origin}:{evaluated.name}"
    embedding = _encode_embedding(embed(_recipe_summary(recipe)), store)

    existing = store.row("SELECT id, success_count FROM skills WHERE name = ?", (name,))
    if existing:
        store.rows(
            "UPDATE skills SET success_count = ?, recipe = ?, lineage = ?, embedding = ?, pruned_at = NULL WHERE id = ?",
            (int(existing["success_count"]) + 1, json.dumps(recipe, sort_keys=True), lineage, embedding, existing["id"]),
        )
        store.append_event(actor="master", kind="skill_reinforced", ref_type="skill", ref_id=str(existing["id"]), payload={"name": name})
        return str(existing["id"])

    skill_id = store.insert(
        "skills",
        {
            "name": name,
            "recipe": recipe,
            "grade": 0.0,  # provisional — grade_skills() fills it from downstream OOS evidence
            "lineage": lineage,
            "success_count": 1,
            "created_at": utcnow(),
            "pruned_at": None,
            "embedding": embedding,
        },
    )
    store.append_event(actor="master", kind="skill_distilled", ref_type="skill", ref_id=skill_id, payload={"name": name, "recipe_summary": _recipe_summary(recipe)})
    return skill_id


def _derived_versions(store: Store, recipe: dict[str, Any]) -> list[dict[str, Any]]:
    """The Versions DERIVED from a skill: the seed Version it was distilled from PLUS any later Version whose
    structural fingerprint (asset class + entry features + modules) matches the recipe. Their REAL screen
    backtests (the deterministic scorer's verdicts) are the only grading evidence — the Curator never re-scores."""
    structure = recipe.get("structure", {})
    want_features = set(structure.get("entry_features", []))
    want_modules = set(structure.get("setup_modules", []))
    want_classes = set(structure.get("asset_classes", []))
    rows = store.rows(
        """
        SELECT sv.id AS version_id, sv.spec AS spec, b.passed_gates AS passed_gates,
               b.deflated_sharpe AS deflated_sharpe, b.oos_return AS oos_return
        FROM strategy_versions sv
        JOIN backtests b ON b.strategy_version_id = sv.id AND b.kind = 'screen'
        """
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        spec_json = r["spec"]
        if isinstance(spec_json, str):
            try:
                spec_json = json.loads(spec_json)
            except json.JSONDecodeError:
                continue
        try:
            spec = StrategySpec.model_validate(spec_json)
        except Exception:  # noqa: BLE001 — a malformed historical spec must not break grading
            continue
        fp = structure_fingerprint(spec)
        if set(fp["entry_features"]) != want_features:
            continue
        if set(fp["setup_modules"]) != want_modules:
            continue
        if want_classes and not (set(fp["asset_classes"]) & want_classes):
            continue
        out.append(r)
    return out


def grade_skills(store: Store, *, min_grade: float = DEFAULT_MIN_GRADE) -> list[SkillRecord]:
    """Grade each (un-pruned) skill by the downstream OOS success of the Versions derived from it: grade = share
    of derived Versions that PASSED the deterministic gate (a skill that keeps yielding gate-passers earns a high
    grade). PRUNE skills whose grade falls below `min_grade` once they have enough derived evidence — sets
    pruned_at so the prior set self-cleans. Deterministic; reads only real persisted verdicts."""
    skills = store.rows("SELECT id, name, recipe, lineage, created_at FROM skills WHERE pruned_at IS NULL")
    graded: list[SkillRecord] = []
    for s in skills:
        recipe = s["recipe"]
        if isinstance(recipe, str):
            try:
                recipe = json.loads(recipe)
            except json.JSONDecodeError:
                recipe = {}
        derived = _derived_versions(store, recipe or {})
        n = len(derived)
        passed = sum(1 for d in derived if int(d["passed_gates"] or 0) == 1)
        grade = round(passed / n, 6) if n else 0.0
        pruned = n >= MIN_DERIVED_FOR_PRUNE and grade < min_grade
        store.rows(
            "UPDATE skills SET grade = ?, success_count = ?, pruned_at = ? WHERE id = ?",
            (grade, passed, utcnow() if pruned else None, s["id"]),
        )
        if pruned:
            store.append_event(actor="master", kind="skill_pruned", ref_type="skill", ref_id=str(s["id"]), payload={"name": s["name"], "grade": grade, "derived": n})
            continue
        graded.append(
            SkillRecord(
                id=str(s["id"]),
                name=s["name"],
                grade=grade,
                success_count=passed,
                lineage=s["lineage"],
                recipe_summary=_recipe_summary(recipe or {}),
                created_at=s["created_at"],
            )
        )
    graded.sort(key=lambda r: (r.grade, r.success_count, r.name), reverse=True)
    return graded


def live_skills(store: Store, *, limit: int = 24) -> list[SkillRecord]:
    """The GET /skills feed AND the authoring prior set: un-pruned skills, best-graded first. Read straight off
    the table (no recompute) so it is cheap and offline."""
    rows = store.rows(
        "SELECT id, name, grade, success_count, lineage, recipe, created_at FROM skills WHERE pruned_at IS NULL ORDER BY CAST(grade AS REAL) DESC, success_count DESC LIMIT ?",
        (limit,),
    )
    out: list[SkillRecord] = []
    for r in rows:
        recipe = r["recipe"]
        if isinstance(recipe, str):
            try:
                recipe = json.loads(recipe)
            except json.JSONDecodeError:
                recipe = {}
        out.append(
            SkillRecord(
                id=str(r["id"]),
                name=r["name"],
                grade=float(r["grade"] or 0.0),
                success_count=int(r["success_count"] or 0),
                lineage=r["lineage"],
                recipe_summary=_recipe_summary(recipe or {}),
                created_at=r["created_at"],
            )
        )
    return out


def skill_feature_priors(store: Store) -> dict[str, float]:
    """The authoring prior the brain leans on: each named feature → its best skill grade across un-pruned skills.
    A higher prior means 'this feature is part of a structure that keeps passing the gate'. Empty when no skills
    exist yet (cold start — the author falls back to its deterministic template match). Never a veto."""
    priors: dict[str, float] = {}
    for r in store.rows("SELECT grade, recipe FROM skills WHERE pruned_at IS NULL"):
        recipe = r["recipe"]
        if isinstance(recipe, str):
            try:
                recipe = json.loads(recipe)
            except json.JSONDecodeError:
                continue
        grade = float(r["grade"] or 0.0)
        for feat in (recipe or {}).get("features", []):
            priors[feat] = max(priors.get(feat, 0.0), grade)
    return priors


def curate_cohort(store: Store, survivors: list[Any], specs_by_vid: dict[str, StrategySpec]) -> int:  # noqa: ANN401
    """Distill every gate-passing survivor of a cohort into a skill, then re-grade the whole skill set. Returns
    the number of skills distilled/reinforced. Also persists each death/win into long-term memory so the two
    halves of the flywheel (memory + skills) stay in lockstep. Offline + deterministic."""
    memory = GraveyardMemory(store)
    distilled = 0
    for ev in survivors:
        spec = specs_by_vid.get(ev.version_id)
        if spec is None:
            continue
        memory.remember(spec, ev)
        if getattr(ev, "passed", False):
            distill_skill(store, spec, ev)
            distilled += 1
    grade_skills(store)
    return distilled
