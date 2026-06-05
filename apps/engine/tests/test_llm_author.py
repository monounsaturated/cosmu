"""The REAL LLM author seam, fully offline (the HTTP transport is mocked so CI needs no keys/network):
- a MOCK model returns a valid, magic-number-free StrategySpec (LLM PROPOSES structure; thresholds stay in
  param_space; static_check passes),
- with no key the author falls back to the deterministic template path unchanged,
- an invalid / hardcoded-number model reply is REJECTED (retry, then fall back) — a magic number can never reach
  the spec,
- the tier router maps a tier to a model id and calls the injected seam,
- the scorer/Gate are never reached from the LLM path (the proposal is structure-only).
"""

from __future__ import annotations

import json
from decimal import Decimal

from cosmu.config.settings import Settings, SpendSettings
from cosmu.knowledge.store import Store
from cosmu.lab.author import draft_from_brief
from cosmu.lab.llm import LlmProposal, propose_structure
from cosmu.lab.router import TIER_MODELS, route_and_propose
from cosmu.strategy.spec import ParamRef
from cosmu.strategy.static_check import validate_spec


def _store(tmp_path, *, key: str | None) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/llm.sqlite3", openrouter_api_key=key))


def _valid_chat(_model_id: str, _prompt: str) -> str:
    # A well-behaved model: returns ONLY structure (template + named features), wrapped in prose to prove the
    # JSON extractor copes. No thresholds, no numbers — the spec builder fills param_space deterministically.
    return (
        "Sure! Here is the proposal:\n```json\n"
        + json.dumps({"base_template": "momentum", "features": ["ret_Nd", "adx"], "bar_size": "1d", "rationale": "trend persists"})
        + "\n```"
    )


def _hardcoded_chat(_model_id: str, _prompt: str) -> str:
    # A misbehaving model trying to smuggle a magic number + an extra field; the typed schema must reject it.
    return json.dumps({"base_template": "momentum", "features": ["ret_Nd"], "threshold": 30, "entry_rsi": 0.7})


def _unknown_template_chat(_model_id: str, _prompt: str) -> str:
    return json.dumps({"base_template": "martingale_grid", "features": ["ret_Nd"]})


def test_mock_model_yields_valid_magic_number_free_spec(tmp_path):
    store = _store(tmp_path, key="sk-test")
    draft = draft_from_brief("find me a crypto edge", llm_enabled=True, store=store, chat=_valid_chat)

    # The model PROPOSED the structure: momentum template, daily bars, its named features.
    assert draft.base_template == "momentum"
    assert draft.spec.horizon.bar_size == "1d"
    assert draft.features  # at least one named feature made it through
    # Magic-number-free: every entry/exit threshold is a ParamRef into param_space, and static_check passes.
    assert draft.valid is True
    assert validate_spec(draft.spec) == []
    for cond in draft.spec.entry:
        assert isinstance(cond.threshold, ParamRef)
        assert cond.threshold.param in draft.spec.param_space
    assert any("llm proposed structure" in n for n in draft.notes)


def test_no_key_falls_back_to_deterministic_template(tmp_path):
    store = _store(tmp_path, key=None)
    # llm_enabled False (no key): the deterministic intent matcher runs, no model is consulted.
    draft = draft_from_brief("oversold mean reversion dip buy on crypto", llm_enabled=False, store=store)
    assert draft.base_template == "mean_reversion"
    assert draft.valid is True
    assert any("deterministic template match used" in n for n in draft.notes)


def test_invalid_hardcoded_number_reply_is_rejected_then_falls_back(tmp_path):
    store = _store(tmp_path, key="sk-test")
    # The model keeps returning an invalid (magic-number-bearing / extra-field) shape; after retries the author
    # falls back to the deterministic template and STILL produces a valid, magic-number-free spec.
    draft = draft_from_brief("trend momentum crypto", llm_enabled=True, store=store, chat=_hardcoded_chat)
    assert draft.valid is True
    assert validate_spec(draft.spec) == []  # no literal_threshold ever reaches the spec
    assert any("invalid proposal" in n for n in draft.notes)
    # And the proposal layer itself reports None (rejected) for the hardcoded reply.
    result = propose_structure("x", model_id="m", valid_features=["ret_Nd"], chat=_hardcoded_chat, max_retries=1)
    assert result.proposal is None


def test_unknown_template_rejected(tmp_path):
    result = propose_structure("x", model_id="m", valid_features=["ret_Nd"], chat=_unknown_template_chat, max_retries=1)
    assert result.proposal is None
    assert any("unknown template" in n for n in result.notes)


def test_unknown_proposed_feature_is_dropped_not_injected():
    # The model proposes a feature outside the registry vocab — it is silently dropped, never injected.
    def chat(_m, _p):
        return json.dumps({"base_template": "momentum", "features": ["ret_Nd", "totally_made_up"]})

    result = propose_structure("x", model_id="m", valid_features=["ret_Nd", "adx"], chat=chat)
    assert result.proposal is not None
    assert result.proposal.features == ["ret_Nd"]
    assert any("dropped unknown proposed feature" in n for n in result.notes)


def test_router_maps_tier_to_model_and_calls_seam():
    seen: dict[str, str] = {}

    def chat(model_id: str, _prompt: str) -> str:
        seen["model_id"] = model_id
        return json.dumps({"base_template": "breakout", "features": []})

    result = route_and_propose(
        "vol breakout",
        valid_features=["ret_Nd"],
        spend=SpendSettings(),
        difficulty="mid",
        chat=chat,
    )
    assert result.proposal is not None
    assert seen["model_id"] == TIER_MODELS["mid"]


def test_router_declines_when_daily_cap_exhausted():
    # No model is called when the spend cap is blown — the seam is never reached.
    called = {"n": 0}

    def chat(_m, _p):
        called["n"] += 1
        return "{}"

    result = route_and_propose(
        "x",
        valid_features=["ret_Nd"],
        spend=SpendSettings(daily_cap_usd=Decimal("1")),
        spent_today=Decimal("5"),
        estimated_cost=Decimal("2"),
        chat=chat,
    )
    assert result.proposal is None
    assert called["n"] == 0
    assert any("router declined" in n for n in result.notes)


def test_proposal_is_structure_only_no_numbers_field():
    # The typed proposal has no place to put a threshold/number — defence at the schema boundary.
    p = LlmProposal(base_template="momentum", features=["ret_Nd"])
    assert set(p.model_dump().keys()) == {"base_template", "features", "bar_size", "rationale"}


def test_graveyard_context_appears_in_llm_prompt_before_authoring(tmp_path):
    """recall() is invoked BEFORE the LLM proposes structure so the model sees why prior specs
    failed and can avoid re-testing dead ideas (graveyard RAG)."""
    from cosmu.evolution.seeder import seed_meanrev_spec
    from cosmu.knowledge.memory import GraveyardMemory
    from cosmu.knowledge.store import utcnow

    store = _store(tmp_path, key="sk-test")
    mem = GraveyardMemory(store)

    dead = seed_meanrev_spec()
    dead.name = "Oversold RSI/BB fade"

    class _DeadEv:
        version_id = "v-dead"
        name = "Oversold RSI/BB fade"
        origin = "seed"
        passed = False
        reasons = ["pbo"]
        deflated_sharpe = 0.1
        oos_return_pct = -2.0

    mem.remember(dead, _DeadEv())

    captured: list[str] = []

    def capturing_chat(model_id: str, prompt: str) -> str | None:  # noqa: ARG001
        captured.append(prompt)
        return None  # triggers deterministic fallback; we only care the prompt is enriched

    draft_from_brief(
        "Fade oversold RSI when Bollinger band z-score is extended",
        llm_enabled=True,
        store=store,
        chat=capturing_chat,
    )

    assert captured, "the LLM chat seam must have been called"
    full_prompt = "\n".join(captured)
    # Dead-end context must reach the model BEFORE it proposes structure.
    assert "graveyard" in full_prompt.lower(), "prompt must reference the graveyard dead-end structures"
    assert "rsi" in full_prompt, "dead feature 'rsi' from the killed spec must appear in the LLM prompt"
