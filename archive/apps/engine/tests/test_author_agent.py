# Guard test for the LLM/agent authoring ENTRYPOINT (the prod front door to open_agent_strategy — which until
# now only ever ran in tests, so kind='llm' never got born in prod). Proves: a typed AgentSpec JSON authors a
# kind='llm' observe-only version; an UNSTRUCTURED NL idea — branched off the existing intake's THINK step —
# becomes a valid AgentSpec and authors one too; symbol detection works; the CLI dry-run prints the resolved spec
# without persisting; and the nlp_intake agent_lane routes a vibe to the agent model with ZERO capital. Fully
# offline (no LLM/network). See docs/epics/agentic-lane.md.

from __future__ import annotations

import json

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.lab.nlp_intake import run_pipeline
from cosmu.strategy.agent_spec import AgentExitPolicy, AgentSpec
from cosmu.strategy.author_agent import (
    DEFAULT_SYMBOLS,
    draft_agent_from_brief,
    extract_symbols,
    main,
    open_agent_from_brief,
)


def _store(tmp_path) -> Store:
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/author_agent.sqlite3", openrouter_api_key=None))


def test_extract_symbols_pairs_and_names():
    assert extract_symbols("long BTCUSDT here") == ["BTCUSDT"]
    assert extract_symbols("a dogecoin social catalyst") == ["DOGEUSDT"]
    assert extract_symbols("nothing tradable mentioned") == []  # narrow on purpose — no false symbol


def test_draft_agent_from_brief_is_valid_and_offline():
    brief = "Small-cap social catalyst on a credible X account — a dogecoin sentiment spike could front-run price."
    agent, report = draft_agent_from_brief(brief)  # llm=None → deterministic standardization
    assert isinstance(agent, AgentSpec)
    assert agent.kind == "llm"
    assert agent.symbols == ["DOGEUSDT"]  # detected from the prose
    # the NL thesis is the agent's primary artifact; the forced disconfirmer rides along
    assert report.thesis[:20] in agent.rationale
    assert "Disconfirmer:" in agent.rationale
    # the mandatory exit is filled with concrete bounded-risk defaults (no exit-less LLM strategy)
    assert agent.exit.stop_loss_pct == 0.05 and agent.exit.take_profit_pct == 0.2


def test_draft_agent_defaults_symbol_when_none_detected():
    agent, _ = draft_agent_from_brief("an abstract macro regime musing with no asset named")
    assert agent.symbols == list(DEFAULT_SYMBOLS)


def test_open_agent_from_brief_persists_kind_llm_zero_capital(tmp_path):
    store = _store(tmp_path)
    version_id, agent = open_agent_from_brief(store, "a credible journalist call on solana", symbols=["SOLUSDT"])
    row = store.row("SELECT kind, status, origin, spec FROM strategy_versions WHERE id = ?", (version_id,))
    assert row is not None and row["kind"] == "llm" and row["status"] == "screened"
    assert row["origin"] == "agent-nl"
    again = AgentSpec.model_validate_json(row["spec"])
    assert again.symbols == ["SOLUSDT"]
    # an audit event was written, and NO capital moved (observe-only)
    assert store.row("SELECT id FROM events WHERE ref_id = ? AND kind = 'agent_strategy_authored'", (version_id,)) is not None
    assert store.row("SELECT COUNT(*) AS n FROM tracks")["n"] == 0
    assert store.row("SELECT COUNT(*) AS n FROM positions")["n"] == 0


def test_main_dry_run_brief_prints_spec_without_persisting(capsys):
    rc = main(["--brief", "fade greed on bitcoin when the crowd is euphoric", "--symbols", "BTCUSDT", "--dry-run"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["kind"] == "llm" and out["symbols"] == ["BTCUSDT"]


def test_main_dry_run_spec_file_roundtrips(tmp_path, capsys):
    spec = AgentSpec(
        name="tweet-sniper", rationale="small-cap social catalyst", symbols=["DOGEUSDT"], venues=["binance"],
        exit=AgentExitPolicy(stop_loss_pct=0.05, take_profit_pct=0.2, trailing_pct=0.03), sources=["x:@someone"],
    )
    path = tmp_path / "agent.json"
    path.write_text(json.dumps(spec.model_dump(mode="json")), encoding="utf-8")
    rc = main(["--spec", str(path), "--dry-run"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["name"] == "tweet-sniper" and out["symbols"] == ["DOGEUSDT"]


def test_nl_intake_agent_lane_authors_an_agent_no_capital(tmp_path):
    store = _store(tmp_path)
    inbox = tmp_path / "inbox"
    f = tmp_path / "idea.md"
    f.write_text("A credible journalist's call on a small-cap — a social catalyst that isn't backtestable.\n", encoding="utf-8")

    result = run_pipeline(f, store=store, llm=None, inbox_dir=inbox, agent_lane=True)

    # the unstructured idea routed to the LLM model, NOT the quant inbox
    assert result.agent_version_id is not None
    assert result.queued is None
    row = store.row("SELECT kind, status FROM strategy_versions WHERE id = ?", (result.agent_version_id,))
    assert row is not None and row["kind"] == "llm" and row["status"] == "screened"
    # the branch is audited and moved ZERO capital
    assert store.row("SELECT id FROM events WHERE kind = 'nl_agent_authored'") is not None
    assert store.row("SELECT COUNT(*) AS n FROM tracks")["n"] == 0
    assert store.row("SELECT COUNT(*) AS n FROM positions")["n"] == 0
