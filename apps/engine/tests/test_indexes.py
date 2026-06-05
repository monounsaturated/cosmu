# Offline tests for the LLM qualitative→quantitative INDEX scorer (narrative → rubric-anchored PIT feature).
# The chat seam + evidence are injected so no key / network is needed. Asserts: extra="forbid" rejects smuggled
# fields, rubric range-checking, key-gating returns None/[], retry-on-invalid, hallucinated evidence-id drop,
# the provider's point-in-time stamping (available_at >= ts), the ingest path into the append-only store, the
# feature-registry + store-routing wiring, and a profile_source GO on a materialized index history.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from cosmu.config.feature_registry import feature_names
from cosmu.config.settings import Settings
from cosmu.data.altdata import (
    AltDataPoint,
    AltDataStore,
    FixtureNewsProvider,
    NewsItem,
    StoreBackedAltProvider,
    _STORE_MARKET_WIDE,
    _STORE_PROVIDER_OF,
)
from cosmu.ingest.pipeline import ingest_market_wide_numeric
from cosmu.ingest.profile_source import profile_points
from cosmu.lab.indexes import (
    INDEX_RUBRICS,
    EvidenceSnippet,
    FixtureEvidenceProvider,
    IndexScore,
    LlmIndexProvider,
    NewsEvidenceProvider,
    build_index_provider_from_settings,
    score_index,
)

_T0 = datetime(2023, 1, 1, tzinfo=UTC)
_REG = INDEX_RUBRICS["reg_risk_crypto"]
_RISK = INDEX_RUBRICS["risk_on_off"]


def _chat(reply):
    """A chat seam that returns `reply` (str) or raises if `reply` is an Exception."""

    def chat(model_id: str, prompt: str):
        if isinstance(reply, Exception):
            raise reply
        return reply

    return chat


def _snips(*texts: str) -> list[EvidenceSnippet]:
    from cosmu.lab.indexes import _evidence_id

    return [EvidenceSnippet(id=_evidence_id(t), text=t, available_at=_T0) for t in texts]


# --------------------------------------------------------------------------- the typed boundary


def test_index_score_forbids_extra_fields():
    with pytest.raises(ValidationError):
        IndexScore(score=0.5, confidence=0.9, rationale="x", evidence_ids=[], leverage=3)  # type: ignore[call-arg]


def test_index_score_confidence_bounded():
    with pytest.raises(ValidationError):
        IndexScore(score=0.5, confidence=1.5)


# --------------------------------------------------------------------------- the scorer (LLM-as-judge)


def test_score_index_parses_cot_then_json():
    snips = _snips("SEC sues major exchange", "Country bans crypto trading")
    raw = (
        "The evidence shows aggressive enforcement and an outright ban, so crackdown pressure is high.\n"
        f'{{"score": 0.9, "confidence": 0.8, "rationale": "ban + enforcement", "evidence_ids": ["{snips[0].id}"]}}'
    )
    score = score_index(_REG, snips, chat=_chat(raw), model_id="test")
    assert score is not None
    assert score.score == 0.9 and score.confidence == 0.8
    assert score.evidence_ids == [snips[0].id]


def test_score_index_no_key_returns_none():
    assert score_index(_REG, _snips("x"), chat=lambda m, p: None, model_id="test") is None


def test_score_index_transport_error_degrades_to_none():
    assert score_index(_REG, _snips("x"), chat=_chat(RuntimeError("network down")), model_id="test") is None


def test_score_index_out_of_range_rejected():
    # reg_risk_crypto ∈ [0, 1]; a 1.8 is out of range and must be rejected (then exhausted → None).
    raw = '{"score": 1.8, "confidence": 0.9, "rationale": "x", "evidence_ids": []}'
    assert score_index(_REG, _snips("x"), chat=_chat(raw), model_id="test", max_retries=1) is None


def test_score_index_retries_then_succeeds():
    good = '{"score": -0.7, "confidence": 0.6, "rationale": "risk off", "evidence_ids": []}'
    replies = iter(["not json at all", good])

    def chat(model_id: str, prompt: str):
        return next(replies)

    score = score_index(_RISK, _snips("war escalates"), chat=chat, model_id="test", max_retries=2)
    assert score is not None and score.score == -0.7  # risk_on_off allows negatives


def test_score_index_drops_hallucinated_evidence_id():
    raw = '{"score": 0.4, "confidence": 0.5, "rationale": "x", "evidence_ids": ["deadbeef00", "%s"]}'
    snips = _snips("real headline")
    score = score_index(_REG, snips, chat=_chat(raw % snips[0].id), model_id="test")
    assert score is not None and score.evidence_ids == [snips[0].id]  # the fake id is dropped


# --------------------------------------------------------------------------- the AltDataProvider (PIT)


def test_provider_emits_point_in_time_score():
    ev = FixtureEvidenceProvider({"reg_risk_crypto": _snips("SEC enforcement action")})
    raw = '{"score": 0.8, "confidence": 0.7, "rationale": "x", "evidence_ids": []}'
    prov = LlmIndexProvider(evidence=ev, chat=_chat(raw), model_id="test")
    pts = prov.fetch_series("MARKET", "reg_risk_crypto", limit=10)
    assert len(pts) == 1
    p = pts[0]
    assert p.value == 0.8
    assert p.available_at >= p.ts  # point-in-time: never known before observed (no look-ahead)


def test_provider_unknown_metric_returns_empty():
    prov = LlmIndexProvider(evidence=FixtureEvidenceProvider({}), chat=_chat("{}"), model_id="test")
    assert prov.fetch_series("MARKET", "not_an_index", limit=10) == []


def test_provider_no_key_returns_empty():
    # chat=None (no LLM key) → honest degradation: the source ingests nothing, never a fabricated score.
    prov = LlmIndexProvider(evidence=FixtureEvidenceProvider({"reg_risk_crypto": _snips("x")}), chat=None)
    assert prov.fetch_series("MARKET", "reg_risk_crypto", limit=10) == []


def test_provider_no_evidence_returns_empty():
    prov = LlmIndexProvider(evidence=FixtureEvidenceProvider({}), chat=_chat("{}"), model_id="test")
    assert prov.fetch_series("MARKET", "reg_risk_crypto", limit=10) == []


def test_news_evidence_provider_adapts_and_dedupes():
    news = FixtureNewsProvider(
        {
            "BTCUSDT": [
                NewsItem(ts=_T0, available_at=_T0, headline="SEC sues exchange"),
                NewsItem(ts=_T0, available_at=_T0, headline="SEC sues exchange"),  # dup → one snippet
            ],
            "ETHUSDT": [NewsItem(ts=_T0, available_at=_T0, headline="ETF approved")],
        }
    )
    ev = NewsEvidenceProvider(news)
    snips = ev.fetch_evidence("reg_risk_crypto", limit=30)
    assert {s.text for s in snips} == {"SEC sues exchange", "ETF approved"}


def test_build_from_settings_is_key_gated():
    # no key → chat None → provider ingests nothing
    prov = build_index_provider_from_settings(
        Settings(xai_api_key=None, openrouter_api_key=None),
        evidence=FixtureEvidenceProvider({"reg_risk_crypto": _snips("x")}),
    )
    assert prov.chat is None
    assert prov.fetch_series("MARKET", "reg_risk_crypto", limit=10) == []
    # with a key the chat seam is live (xAI preferred)
    keyed = build_index_provider_from_settings(Settings(xai_api_key="xai-test"))
    assert keyed.chat is not None


# --------------------------------------------------------------------------- wiring (registry + store routing)


def test_indexes_registered_and_routed():
    names = feature_names()
    for idx in INDEX_RUBRICS:
        assert idx in names  # registered as a feature
        assert _STORE_PROVIDER_OF[idx] == "llm_index"  # routed to the llm_index provider
        assert idx in _STORE_MARKET_WIDE  # stored under the MARKET key


def test_ingest_writes_pit_and_reads_back(tmp_path):
    store = AltDataStore(tmp_path / "alt")
    ev = FixtureEvidenceProvider({"reg_risk_crypto": _snips("SEC enforcement")})
    raw = '{"score": 0.75, "confidence": 0.6, "rationale": "x", "evidence_ids": []}'
    prov = LlmIndexProvider(evidence=ev, chat=_chat(raw), model_id="test")

    n = ingest_market_wide_numeric(
        store, prov, source_metric="reg_risk_crypto", stored_metric="reg_risk_crypto", provider_name="llm_index"
    )
    assert n == 1
    # stored market-wide under the MARKET key, readable point-in-time...
    pit = store.read_asof("llm_index", "MARKET", "reg_risk_crypto", datetime.now(tz=UTC))
    assert len(pit) == 1 and pit[0].value == 0.75
    # ...and the same gate-facing seam reads it back through the routing table
    reader = StoreBackedAltProvider(store)
    assert reader.fetch_series("BTCUSDT", "reg_risk_crypto", limit=10)[0].value == 0.75


# --------------------------------------------------------------------------- data-trust audit (profile GO)


def test_materialized_index_history_profiles_go():
    # A clean daily index history (deep, dense, fresh, PIT-honest) must earn a GO before it can shape the gate.
    points = [
        AltDataPoint(ts=_T0 + timedelta(days=i), available_at=_T0 + timedelta(days=i), value=0.3 + 0.001 * i)
        for i in range(60)
    ]
    now = points[-1].available_at
    profile = profile_points(points, provider="llm_index", symbol="MARKET", metric="reg_risk_crypto", now=now)
    assert profile.verdict == "GO", profile.to_text()
    assert profile.coverage.lookahead_violations == 0
