# The agentic research loop, CLOSED: the propose-only tool bus gathers context → prior-art features are distilled
# → the author CONDITIONS on them (folded in, validated, memory-pruned) → the deterministic Gate still disposes.
# Everything here is offline + deterministic (tool fixtures, no key) and makes ZERO LLM calls.

from __future__ import annotations

from cosmu.lab.author import draft_from_brief
from cosmu.lab.research import _prior_art_from_context, author_candidates, gather_context
from cosmu.lab.tools.research_tools import research_tool_bus


def test_prior_art_is_distilled_from_the_read_only_bus_offline():
    """gather_context (offline fixtures) → _prior_art_from_context yields real prior-art features + citations."""
    ctx = gather_context(research_tool_bus())
    feats, cites = _prior_art_from_context(ctx)
    assert "rsi" in feats                       # the rag prior-art fixture surfaces the oversold-reversion feature
    assert cites and any("prior-art" in c for c in cites)


def test_author_conditions_on_prior_art_without_an_llm():
    """The author folds a valid prior-art feature into the spec and records the citation — deterministic, no key."""
    draft = draft_from_brief(
        "mean reversion on crypto",
        prior_art=["rsi"],
        research_citations=["prior-art: oversold mean reversion"],
    )
    assert "rsi" in draft.features                    # research INFORMED the structure
    assert "rsi" in draft.research_features           # audit trail records what research contributed
    assert any("oversold" in c for c in draft.research_citations)
    assert any("model router disabled" in n for n in draft.notes)   # proof: ZERO LLM calls (deterministic path)
    assert not draft.issues                            # still a valid, magic-number-free spec


def test_prior_art_invalid_for_asset_class_is_ignored_not_smuggled():
    """A prior-art feature that isn't valid for the spec's asset class is dropped — research can't override rules."""
    draft = draft_from_brief("equity momentum on SPY", prior_art=["funding_rate"])  # crypto-only feature
    assert "funding_rate" not in draft.features
    assert "funding_rate" not in draft.research_features


def test_author_candidates_threads_prior_art_into_at_least_one_candidate():
    """The gather→author wire reaches the cohort authoring path, not just the single-brief call."""
    cands = author_candidates(3, prior_art=["rsi"], research_citations=["c"])
    assert cands
    assert any("rsi" in draft.research_features for draft, _ in cands)
