# Offline, mock-LLM tests for the NL→strategy pipeline scaffold (document_handler → thinker → matcher →
# signal_builder → nlp_intake). No network, no real LLM, no heavy compute — a tiny .md brief flows through the
# whole chain and produces a StrategySpec-shaped object that the EXISTING inbox/Gate would dispose.

from __future__ import annotations

import json
from pathlib import Path

from cosmu.config.settings import Settings
from cosmu.ingest.document_handler import DocumentHandler
from cosmu.knowledge.store import Store
from cosmu.lab.nlp_intake import run_pipeline
from cosmu.mind.matcher import match
from cosmu.mind.signal_builder import build_signals
from cosmu.mind.thinker import ThinkingReport, interpret
from cosmu.strategy.spec import StrategySpec


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/nl.sqlite3", openrouter_api_key=None))


_BRIEF = """# Old-book momentum vibe

Buy strength, sell weakness — ride the trend in bitcoin.

## Filter

Avoid funding extremes and watch for an oversold RSI bounce. Some say the planets align with the cycle.
"""


def _mock_llm(_prompt: str) -> str:
    # Deterministic stand-in for the model: standardizes the prose into modern terms + a forced disconfirmer.
    return json.dumps(
        {
            "thesis": "Trend-follow bitcoin: buy strength, sell weakness.",
            "edge_hypothesis": "Momentum persists at the swing horizon before it is fully priced.",
            "regime": "bull",
            "recommended_features": ["momentum", "rsi", "funding_rate", "astrological_era"],
            "disconfirmer": "Edge vanishes out-of-sample net of fees or is symmetric in lead-lag.",
        }
    )


def test_document_handler_chunks_md_idempotently(tmp_path):
    f = tmp_path / "idea.md"
    f.write_text(_BRIEF, encoding="utf-8")
    handler = DocumentHandler()
    a = handler.parse_file(f)
    b = handler.parse_file(f)
    assert a, "expected at least one chunk"
    # idempotent: same bytes → identical chunk ids + text
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b]
    assert [c.text for c in a] == [c.text for c in b]
    # section split picked up the headings
    assert all(c.metadata.get("content_hash") for c in a)


def test_pdf_without_parser_is_honest(tmp_path):
    # A non-PDF byte blob with a .pdf suffix → no real parser succeeds → one honest 'unavailable'/'error' chunk,
    # never fabricated content and never a crash.
    f = tmp_path / "fake.pdf"
    f.write_bytes(b"not a real pdf")
    chunks = DocumentHandler().parse_file(f)
    assert len(chunks) == 1
    assert "pdf parsing" in chunks[0].text.lower()


def test_thinker_offline_fallback_has_disconfirmer(tmp_path):
    f = tmp_path / "idea.md"
    f.write_text(_BRIEF, encoding="utf-8")
    chunks = DocumentHandler().parse_file(f)
    rep = interpret(chunks, llm=None)  # no LLM → deterministic brain
    assert isinstance(rep, ThinkingReport)
    assert rep.via == "deterministic"
    assert rep.disconfirmer  # ALWAYS populated
    assert rep.recommended_features  # keyword brain found terms


def test_thinker_uses_mock_llm(tmp_path):
    f = tmp_path / "idea.md"
    f.write_text(_BRIEF, encoding="utf-8")
    chunks = DocumentHandler().parse_file(f)
    rep = interpret(chunks, llm=_mock_llm)
    assert rep.via == "llm"
    assert rep.regime == "bull"
    assert "momentum" in rep.recommended_features
    assert rep.disconfirmer


def test_matcher_grounds_registry_and_routes_claims():
    rep = ThinkingReport(
        thesis="t",
        edge_hypothesis="e",
        regime="bull",
        recommended_features=["momentum", "rsi", "funding_rate", "astrological_era", "exchange_netflow"],
        disconfirmer="d",
    )
    res = match(rep)
    # momentum→ret_Nd, rsi→rsi, funding_rate→funding_rate are enabled registry features
    assert "ret_Nd" in res.matched_features
    assert "rsi" in res.matched_features
    assert "funding_rate" in res.matched_features
    # astrological_era has no registry home → unmapped claim
    assert "astrological_era" in res.unmapped_claims
    # exchange_netflow is a DISABLED feature → never matched (honesty), routed to unmapped
    assert "exchange_netflow" not in res.matched_features
    assert "exchange_netflow" in res.unmapped_claims


def test_signal_builder_emits_spec_only():
    sigs = build_signals(["astrological_era", "recession", "some_unknown_claim"])
    by_claim = {s.source_claim: s for s in sigs}
    assert by_claim["astrological_era"].name == "nl_astrological_era"
    assert by_claim["astrological_era"].provider == "ephemeris"
    # every emitted signal carries a disconfirmer and is NOT computed (spec only)
    for s in sigs:
        assert s.disconfirmer
        assert s.computed is False
        assert s.transform_version


def test_full_pipeline_produces_strategyspec_and_queues(tmp_path):
    store = _store(tmp_path)
    inbox = tmp_path / "inbox"
    f = tmp_path / "idea.md"
    f.write_text(_BRIEF, encoding="utf-8")

    result = run_pipeline(f, store=store, llm=_mock_llm, inbox_dir=inbox)

    # (5) synthesized a StrategySpec-shaped object
    assert isinstance(result.draft.spec, StrategySpec)
    assert result.draft.spec.name
    assert result.draft.spec.entry  # has entry conditions
    # complex claim became a precomputed-signal spec
    assert any(s.name == "nl_astrological_era" for s in result.signals)
    # dropped into the EXISTING inbox intake
    assert result.queued is not None
    assert (inbox / result.queued.filename).exists()

    # every pipeline step was persisted as an audited event
    kinds = {
        r["kind"]
        for r in store.rows("SELECT kind FROM events WHERE kind LIKE 'nl_%' OR kind = 'inbox_queued'")
    }
    assert {"nl_document_parsed", "nl_interpreted", "nl_matched", "nl_signals_built", "nl_drafted", "nl_queued"} <= kinds
    assert "inbox_queued" in kinds  # queue_idea fired the existing intake event


def test_pipeline_dry_run_without_store():
    # No store → chain still runs end-to-end (offline), just doesn't queue.
    here = Path(__file__)
    result = run_pipeline(here, store=None, llm=None, queue=True)
    assert isinstance(result.draft.spec, StrategySpec)
    assert result.queued is None
    assert any("dry-run" in n for n in result.notes)
