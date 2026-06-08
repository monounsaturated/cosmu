# The Mind's LLM-as-JUDGE committee — each market pillar emits a rubric-scored, structured (instructor) Verdict
# {lean, score, confidence, rationale}; the consensus is a DETERMINISTIC, auditable aggregation of those scores.
# These tests pin the contract: the Verdict is a typed boundary (extra fields rejected, ranges clamped); a mock
# LLM flows real verdicts into a deterministic consensus; a pillar with NO data is never handed to the model
# (abstain, never fabricate); any LLM failure falls back to the deterministic heuristic; and the railguard holds
# — the Mind only reasons, the gate disposes. All offline: the chat seam is mocked, no key, no network.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store, utcnow
from cosmu.mind import (
    RAILGUARD,
    RUBRICS,
    Verdict,
    build_judge,
    build_mind,
    gather_context,
    judge_from_settings,
    judge_pillar,
    run_panel,
)
from cosmu.mind.rubric import Rubric


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/judges.sqlite3", openrouter_api_key=None))


def _seed_metric(store: Store, metric: str, value: float, *, provider: str = "test") -> None:
    # Seed alt_data AND its summary rollup (latest_value) as the real ingest path does — the Mind KNOWS panel
    # reads the newest value per metric off the rollup, not alt_data directly.
    from cosmu.ingest.alt_summary import record_ingest

    ts = datetime.now(UTC) - timedelta(days=0)
    store.rows(
        "INSERT INTO alt_data(provider, symbol, metric, ts, available_at, value, ingested_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (provider, "BTCUSDT", metric, ts.isoformat(), ts.isoformat(), value, utcnow()),
    )
    with store.batch() as w:
        record_ingest(w, provider, metric, n_rows=1, latest_available_at=ts.isoformat(), latest_value=str(value))


def _chat_returning(payload: str):
    """A mock ChatFn that always returns the same canned model text (offline, deterministic)."""

    def chat(model_id: str, prompt: str) -> str:
        return payload

    return chat


# --------------------------------------------------------------------------- the typed Verdict boundary


def test_verdict_is_a_typed_boundary():
    v = Verdict(lean="bullish", score=0.7, confidence=0.8, rationale="extreme fear, contrarian long")
    assert v.lean == "bullish" and v.score == 0.7 and v.confidence == 0.8

    # Out-of-range score/confidence are clamped, not trusted blindly.
    assert Verdict(lean="bearish", score=-9.0, confidence=2.0, rationale="x").score == -1.0
    assert Verdict(lean="bearish", score=0.0, confidence=2.0, rationale="x").confidence == 1.0

    # extra="forbid": a model that smuggles ANY other field (e.g. a money instruction) is rejected outright.
    with pytest.raises(ValidationError):
        Verdict(lean="bullish", score=0.1, confidence=0.5, rationale="x", position_size=1.0)

    # The model may NOT abstain (abstain is a no-data fact decided in Python) and may not return empty rationale.
    with pytest.raises(ValidationError):
        Verdict(lean="abstain", score=0.0, confidence=0.0, rationale="x")
    with pytest.raises(ValidationError):
        Verdict(lean="neutral", score=0.0, confidence=0.0, rationale="   ")


# --------------------------------------------------------------------------- the judge seam (mock-LLM)


def test_judge_pillar_parses_a_valid_mock_verdict():
    chat = _chat_returning('{"lean": "bearish", "score": -0.6, "confidence": 0.7, "rationale": "crowded longs"}')
    v = judge_pillar(RUBRICS["Positioning"], ["funding_z=+2.0"], "bearish", chat=chat, model_id="mock")
    assert v is not None and v.lean == "bearish" and v.confidence == 0.7


def test_judge_pillar_falls_back_when_no_model():
    # chat returns None (no key) → no verdict → caller keeps the deterministic heuristic.
    chat = lambda model_id, prompt: None  # noqa: E731
    assert judge_pillar(RUBRICS["Macro"], ["macro_regime=+0.8"], "bullish", chat=chat, model_id="mock") is None


def test_judge_pillar_falls_back_on_invalid_output():
    chat = _chat_returning("not json at all, the model rambled")
    assert judge_pillar(RUBRICS["Sentiment"], ["fear_greed=15"], "bullish", chat=chat, model_id="mock") is None


def test_judge_pillar_never_runs_on_empty_evidence():
    # Defence in depth: a no-data pillar must never reach the model — it cannot fabricate from nothing.
    called = {"n": 0}

    def chat(model_id, prompt):  # noqa: ANN001
        called["n"] += 1
        return '{"lean":"bullish","score":1,"confidence":1,"rationale":"x"}'

    assert judge_pillar(RUBRICS["OSINT"], [], "neutral", chat=chat, model_id="mock") is None
    assert called["n"] == 0


# --------------------------------------------------------------------------- the panel: verdicts → consensus


def test_abstaining_pillars_are_never_judged(tmp_path):
    # Empty store → every market pillar abstains → the judge is NEVER called (no fabrication).
    store = _store(tmp_path)
    ctx = gather_context(store)
    seen: list[str] = []

    def spy_judge(rubric: Rubric, evidence: list[str], heuristic_lean: str):
        seen.append(rubric.pillar)
        return Verdict(lean="bullish", score=1.0, confidence=1.0, rationale="should never happen")

    stances = run_panel(ctx, judge=spy_judge)
    assert seen == [], "an abstaining (no-data) pillar must never be handed to the LLM"
    market = [s for s in stances if s.kind == "market"]
    assert market and all(s.lean == "abstain" and s.source == "abstain" for s in market)


def test_llm_verdicts_flow_into_a_deterministic_consensus(tmp_path):
    store = _store(tmp_path)
    _seed_metric(store, "fear_greed", 15.0)  # has data → judgeable
    _seed_metric(store, "macro_regime", 0.8)  # has data → judgeable
    # A mock judge that turns every judged pillar bullish with a fixed confidence.
    judge = build_judge(
        _chat_returning('{"lean": "bullish", "score": 0.9, "confidence": 0.9, "rationale": "model says up"}'),
        model_id="mock",
    )
    a = build_mind(store, judge=judge)
    b = build_mind(store, judge=judge)

    # The model SCORED the pillars; the aggregation is deterministic → identical snapshots across runs.
    assert a == b
    judged = [s for s in a["stances"] if s["source"] == "llm"]
    assert judged, "pillars with data should carry an LLM verdict"
    for s in judged:
        assert s["lean"] == "bullish" and s["conviction"] == 0.9 and s["rationale"] == "model says up"
        assert s["rubric"] in RUBRICS
    assert a["consensus"] == "bullish"

    # The consensus audit is replayable: contributions sum to the per-lean tally, and argmax is the consensus.
    audit = a["consensus_audit"]
    bull = round(sum(c["contribution"] for c in audit["contributions"] if c["lean"] == "bullish"), 4)
    assert bull == audit["tally"]["bullish"]
    assert audit["consensus"] == a["consensus"]


def test_invalid_llm_keeps_the_deterministic_heuristic(tmp_path):
    store = _store(tmp_path)
    _seed_metric(store, "fear_greed", 15.0)  # extreme fear → heuristic is bullish
    judge = build_judge(_chat_returning("garbage, not a verdict"), model_id="mock")
    mind = build_mind(store, judge=judge)
    sentiment = next(s for s in mind["stances"] if s["perspective"] == "Sentiment")
    # The LLM failed → we fall back to the deterministic read, NOT to silence.
    assert sentiment["source"] == "heuristic"
    assert sentiment["lean"] == "bullish"


def test_judge_default_off_matches_deterministic_panel(tmp_path):
    # build_mind with no judge must be byte-identical to the deterministic panel (the default everywhere).
    store = _store(tmp_path)
    _seed_metric(store, "fear_greed", 80.0)
    assert build_mind(store) == build_mind(store, judge=None)


def test_railguard_and_typed_scores_hold_with_a_judge(tmp_path):
    store = _store(tmp_path)
    _seed_metric(store, "macro_regime", -0.9)  # risk-off
    judge = build_judge(
        _chat_returning('{"lean": "bearish", "score": -0.8, "confidence": 0.6, "rationale": "risk-off"}'),
        model_id="mock",
    )
    mind = build_mind(store, judge=judge)
    assert mind["railguard"] == RAILGUARD
    for s in mind["stances"]:
        assert s["lean"] in ("bullish", "bearish", "neutral", "abstain")
        assert -1.0 <= s["score"] <= 1.0
        assert 0.0 <= s["conviction"] <= 1.0
        assert s["source"] in ("heuristic", "llm", "abstain")


def test_judge_from_settings_is_none_without_a_key():
    # No LLM key → no judge → the Mind stays deterministic (never silently calls a non-existent model).
    assert judge_from_settings(Settings(openrouter_api_key=None, xai_api_key=None)) is None


def test_every_market_rubric_lines_up_with_an_analyst(tmp_path):
    # The rubrics must key exactly to the MARKET perspectives — no orphan rubric, no unscored market pillar.
    store = _store(tmp_path)
    ctx = gather_context(store)
    market_perspectives = {s.perspective for s in run_panel(ctx) if s.kind == "market"}
    assert set(RUBRICS) == market_perspectives
