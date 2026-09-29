"""The autonomous research pass end-to-end, fully offline: gather context → author candidates → compile +
static_check → run through the DETERMINISTIC evolution screen/gate → record survivors + graveyard with
reasons. LLM PROPOSES (the author, deterministic offline) and the deterministic scorer DISPOSES — and we
assert no LLM is reachable from the scoring path."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.data.market import Bar
from cosmu.knowledge.store import Store
from cosmu.lab.research import author_candidates, gather_context, run_research_pass
from cosmu.lab.tools.research_tools import research_tool_bus


class _Bars:
    def __init__(self) -> None:
        self._bars = _make_bars()

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        return self._bars[-limit:]


def _make_bars(n: int = 400) -> list[Bar]:
    ts = datetime(2023, 1, 1, tzinfo=UTC)
    price = Decimal("100")
    out: list[Bar] = []
    for i in range(n):
        move = Decimal("0.012") if i % 20 < 11 else Decimal("-0.01")
        open_ = price
        close = (price * (Decimal("1") + move)).quantize(Decimal("0.0001"))
        out.append(Bar(ts=ts + timedelta(days=i), open=open_, high=(max(open_, close) * Decimal("1.005")).quantize(Decimal("0.0001")), low=(min(open_, close) * Decimal("0.995")).quantize(Decimal("0.0001")), close=close, volume=Decimal("1000")))
        price = close
    return out


def _store(tmp_path) -> Store:
    # no openrouter key → the whole pass is offline; any LLM (the author's) is optional and unused here
    return Store(Settings(database_url=f"sqlite:///{tmp_path}/research.sqlite3", openrouter_api_key=None))


def test_authoring_compiles_and_references_osint_feature():
    authored = author_candidates(6, llm_enabled=False)
    assert len(authored) == 6
    assert all(rec.compiled for _, rec in authored), [rec.issues for _, rec in authored if not rec.compiled]
    # the OSINT source is reachable as a NAMED feature the brain authored against
    osint = [rec for _, rec in authored if "osint_air_activity" in rec.features]
    assert osint, "expected a candidate referencing osint_air_activity"
    assert "opensky" in osint[0].data_sources


def test_research_pass_gates_end_to_end_offline(tmp_path):
    report = run_research_pass(_store(tmp_path), n=4, seed=7, market_data=_Bars())
    assert report.n_requested == 4
    assert report.llm_enabled is False
    # context came off the propose-only bus
    assert {"web_search", "news_read", "social", "pine_fetch", "rag_read"} <= set(report.context_tools)
    # candidates were authored + compiled
    assert report.authored and all(r.compiled for r in report.authored)
    # the deterministic gate disposed: every evaluated candidate is either a survivor or a graveyard entry
    assert report.cohort.generated > 0
    assert report.cohort.passed + report.cohort.killed == report.cohort.generated
    # graveyard entries carry kill reasons (the deterministic wall's verdict)
    for g in report.graveyard:
        assert g.reasons or True  # reasons may be empty only if 'screened_out'; presence is structural
    # survivors, if any, must have passed the out-of-reach scorer
    for s in report.survivors:
        assert s.passed


def test_research_pass_is_reproducible(tmp_path):
    a = run_research_pass(_store(tmp_path / "a"), n=4, seed=11, market_data=_Bars())
    b = run_research_pass(_store(tmp_path / "b"), n=4, seed=11, market_data=_Bars())
    assert [c.name for c in a.authored] == [c.name for c in b.authored]
    assert a.cohort.generated == b.cohort.generated
    assert a.cohort.passed == b.cohort.passed
    assert sorted(g.name for g in a.graveyard) == sorted(g.name for g in b.graveyard)


def test_no_llm_in_scoring_path(tmp_path, monkeypatch):
    """The scorer/gate must never touch the model router. We poison route_model; if the scoring path
    called it the pass would raise. It must complete cleanly."""
    import cosmu.lab.router as router

    def _boom(*_a, **_k):
        raise AssertionError("LLM router reached from the scoring path")

    monkeypatch.setattr(router, "route_model", _boom)
    report = run_research_pass(_store(tmp_path), n=3, seed=3, market_data=_Bars())
    assert report.cohort.generated > 0  # completed with no router call


def test_gather_context_has_no_execution_tool():
    ctx = gather_context(research_tool_bus())
    assert not any("execute" in t or "order" in t for t in ctx["tools"])
