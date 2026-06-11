# intent: typed contract for the SOURCE SCOREBOARD (realtime-data-lane epic P2) — the voice_scoreboard
# table served flat over GET /mind/credibility; inputs: voice_scoreboard rows written by the hourly
# voices pass; outputs: CredibilityResponse for the generated TS contract; invariants: nullable metrics
# stay null (untested ≠ unskilled — a NULL skill is "no resolved claims yet", NEVER rendered as 0);
# read-only, no LLM on this path, the Gate/money path is deterministic and separate.

from __future__ import annotations

from pydantic import BaseModel


class CredibilityRow(BaseModel):
    """One pre-registered voice's flat scoreboard row (written by cosmu/ingest/voices_pass.py).

    `n_posts`/`n_claims` are volume, NOT skill. `n_resolved` is how many claims were old enough to be
    scored against the tape. Every REAL metric is nullable: a voice with zero resolved claims carries
    NULL skill (honest — untested, not unskilled). `hit_rate` vs `base_hit_rate` separates being right
    from the market simply going up; `brier_skill_score` > 0 beats the base rate; `calibration_error`
    is |stated conviction − realized| (0 = perfectly calibrated); `skill` is the headline [0,1]
    sample-shrunk scalar; `authority` is skill-anchored citation PageRank (influence ≠ authority);
    `primacy_rate` is how often this voice is FIRST on a claim (breaker vs echo)."""

    handle: str
    platform: str
    n_posts: int
    n_claims: int
    n_resolved: int
    hit_rate: float | None = None
    base_hit_rate: float | None = None
    excess_hit_rate: float | None = None
    brier_skill_score: float | None = None
    calibration_error: float | None = None
    skill: float | None = None
    authority: float | None = None
    primacy_rate: float | None = None
    updated_at: str


class CredibilityResponse(BaseModel):
    """The source scoreboard: one row per followed voice, ordered skill DESC with NULLs (untested) last.
    `panel_size` is the row count; `as_of` is the latest scoreboard update (null when the panel is empty
    — voices are pre-registered in cosmu/config/voices.py and the hourly pass fills this in)."""

    as_of: str | None = None
    panel_size: int
    rows: list[CredibilityRow]
