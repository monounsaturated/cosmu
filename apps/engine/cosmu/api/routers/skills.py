# intent: distilled SKILL recipes (priors the brain reuses); inputs: none; outputs: SkillsResponse; invariants: the Curator curates what the Gate judged, it never judges.

from __future__ import annotations

from fastapi import APIRouter

from cosmu.api._shared import store
from cosmu.api.models import Skill, SkillsResponse

router = APIRouter()


@router.get("/skills", response_model=SkillsResponse)
def skills() -> SkillsResponse:
    """The Curator's distilled SKILL recipes — reusable, parameterized templates the brain reuses as priors.
    Best-graded first; pruned skills are excluded. `grade` is the downstream OOS pass-rate of derived Versions
    (the deterministic Gate's verdicts) — the Curator curates what the Gate judged, it never judges."""
    from cosmu.lab.curator import live_skills

    return SkillsResponse(
        skills=[
            Skill(
                name=s.name,
                grade=round(s.grade, 6),
                success_count=s.success_count,
                lineage=s.lineage,
                recipe_summary=s.recipe_summary,
                created_at=s.created_at,
            )
            for s in live_skills(store)
        ]
    )
