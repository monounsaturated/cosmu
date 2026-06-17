# intent: the Mind — the trading agent's standardized self-knowledge surface. It answers three questions in
# one vocabulary: what it KNOWS (the point-in-time data sources it reads), how it THINKS (a multi-perspective
# analyst panel that debates a market read), and what it has LEARNED (graveyard memory, the ML survival model,
# regime coverage, gate efficiency). inputs: the Store (everything lives in the audit ledger + alt_data +
# research_notes) + an optional reference close series; outputs: a typed snapshot dict. invariants: read-only,
# offline/LLM-optional, NEVER fabricates a read (a perspective with no ingested data ABSTAINS), and — the hard
# railguard — the Mind only REASONS; it never funds or fires an order. The deterministic gate alone disposes.

from __future__ import annotations

from cosmu.mind.analysts import (
    ALL_ANALYSTS,
    PER_SYMBOL_METRICS,
    MindContext,
    Stance,
    context_for_symbol,
    gather_context,
    run_panel,
)
from cosmu.mind.debate import RAILGUARD, MindSnapshot, debate
from cosmu.mind.judge import JudgeFn, build_judge, judge_from_settings, judge_pillar
from cosmu.mind.rubric import RUBRICS, Rubric, Verdict
from cosmu.mind.snapshot import build_mind, reflect

__all__ = [
    "ALL_ANALYSTS",
    "PER_SYMBOL_METRICS",
    "MindContext",
    "Stance",
    "context_for_symbol",
    "gather_context",
    "run_panel",
    "RAILGUARD",
    "MindSnapshot",
    "debate",
    "build_mind",
    "reflect",
    "JudgeFn",
    "build_judge",
    "judge_pillar",
    "judge_from_settings",
    "RUBRICS",
    "Rubric",
    "Verdict",
]
