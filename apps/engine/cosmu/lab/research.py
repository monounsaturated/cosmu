# intent: the autonomous RESEARCH BRAIN pass — LLM PROPOSES, deterministic DISPOSES. It (1) gathers
# context via the propose-only lab tool bus (web_search / news_read / social / pine_fetch / rag_read), (2)
# authors N candidate StrategySpecs via lab/author (LLM-OPTIONAL — offline it uses the deterministic template
# matcher), each referencing NAMED features incl. the new OSINT source, (3) compiles + static-checks them,
# and (4) runs them through the DETERMINISTIC evolution screen / gate (FarmLoop → out-of-reach scorer), then
# records survivors + graveyard WITH reasons. Invariants: the scorer/gate stay out of every LLM path and
# decide what survives; the whole pass runs fully offline (no key, no network, no live DB) and is
# reproducible for a fixed seed; BOUNDED (one pass per call, --n N), not a daemon; secrets stay server-side.

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field

from cosmu.config.feature_registry import FEATURE_REGISTRY
from cosmu.config.settings import Settings
from cosmu.data.market import Bar, MarketDataProvider
from cosmu.evolution.loop import CohortSummary, Evaluated, FarmLoop, fit_params
from cosmu.knowledge.store import Store
from cosmu.lab.author import AuthorDraft, draft_from_brief
from cosmu.lab.tools.registry import ToolBus
from cosmu.lab.tools.research_tools import research_tool_bus
from cosmu.research.fixtures import synthetic_cross_asset_inputs
from cosmu.strategy.compiler import compile_spec
from cosmu.strategy.static_check import validate_spec

# The candidate briefs the research brain proposes. Each pairs a plain-language thesis with the NAMED
# features it should reference (validated to the asset class downstream). The OSINT air-activity source
# appears here so it can earn — or fail to earn — its place via the deterministic gate. This list is the
# LLM-OPTIONAL seam: with a key, the model rewrites/extends these; offline they are the deterministic corpus.
_BRIEFS: tuple[tuple[str, list[str]], ...] = (
    ("Fade oversold RSI on crypto when the band z-score is washed out, swing horizon", ["rsi", "bb_z"]),
    ("Trend-confirmed momentum on crypto with ADX confirmation", ["ret_Nd", "adx"]),
    ("Funding-pressure carry: fade crowded perp leverage on crypto", ["funding_rate"]),
    ("Volatility breakout on crypto gated by realized vol", ["ret_Nd", "vol_realized"]),
    ("Buy fear on crypto when the crowd is washed out (fear & greed)", ["fear_greed"]),
    ("OSINT macro proxy: condition crypto entries on aircraft activity (low-confidence, must earn its place)", ["ret_Nd", "osint_air_activity"]),
)


@dataclass
class CandidateRecord:
    brief: str
    name: str
    base_template: str
    features: list[str]
    data_sources: list[str]
    valid: bool
    compiled: bool
    issues: list[str] = field(default_factory=list)
    code_hash: str | None = None


@dataclass
class ResearchReport:
    n_requested: int
    context_tools: list[str]
    context_samples: dict[str, object]
    authored: list[CandidateRecord]
    cohort: CohortSummary
    llm_enabled: bool
    seed: int

    @property
    def survivors(self) -> list[Evaluated]:
        return self.cohort.survivors

    @property
    def graveyard(self) -> list[Evaluated]:
        return self.cohort.graveyard


class _FixtureBars:
    """Deterministic offline bars (the cross-asset crypto fixtures) so the screen runs with no network/DB.
    The screen asks for crypto symbols; we return the same edge-bearing series for each so the gate has
    something real (and reproducible) to judge."""

    def __init__(self) -> None:
        market_by_class, *_ = synthetic_cross_asset_inputs()
        crypto = market_by_class["crypto"]
        self._default = next(iter(crypto.values()))
        self._by_symbol = dict(crypto)

    def fetch_bars(self, symbol: str, timeframe: str, *, limit: int) -> list[Bar]:
        bars = self._by_symbol.get(symbol, self._default)
        return bars[-limit:]


def gather_context(bus: ToolBus, *, symbol: str = "BTCUSDT", offline: bool = True) -> dict[str, object]:
    """Read context off the propose-only tool bus before authoring. Pure context — NO execution, NO scoring.
    Returns a small machine-readable digest the author/LLM would condition on."""
    return {
        "tools": [t["name"] for t in bus.list_tools()],
        "web_search": bus.call("web_search", {"query": "crypto swing strategy edge"}),
        "news_read": bus.call("news_read", {"symbol": symbol, "limit": 4, "offline": offline}),
        "social": bus.call("social", {"symbol": symbol}),
        "rag_read": bus.call("rag_read", {"query": "prior art"}),
        "pine_fetch": bus.call("pine_fetch", {}),
    }


def author_candidates(n: int, *, llm_enabled: bool = False) -> list[tuple[AuthorDraft, CandidateRecord]]:
    """Author N candidate specs via lab/author (LLM-OPTIONAL), compile + static-check each. The author only
    produces STRUCTURE (thresholds stay in param_space); the gate, not this path, decides what survives."""
    out: list[tuple[AuthorDraft, CandidateRecord]] = []
    briefs = [_BRIEFS[i % len(_BRIEFS)] for i in range(max(1, n))]
    for brief, feats in briefs:
        draft = draft_from_brief(brief, features=feats, llm_enabled=llm_enabled)
        issues = list(draft.issues) or validate_spec(draft.spec)
        compiled_ok = False
        code_hash: str | None = None
        if not issues:
            try:
                compiled = compile_spec(draft.spec, fit_params(draft.spec))
                compiled_ok = True
                code_hash = compiled.code_hash
            except ValueError as exc:  # static_check inside compile_spec rejected it
                issues.append(str(exc))
        record = CandidateRecord(
            brief=brief,
            name=draft.spec.name,
            base_template=draft.base_template,
            features=draft.features,
            data_sources=draft.data_sources,
            valid=draft.valid and not issues,
            compiled=compiled_ok,
            issues=issues,
            code_hash=code_hash,
        )
        out.append((draft, record))
    return out


def run_research_pass(
    store: Store,
    *,
    n: int = 4,
    seed: int = 7,
    llm_enabled: bool = False,
    market_data: MarketDataProvider | None = None,
    tool_bus: ToolBus | None = None,
) -> ResearchReport:
    """ONE bounded research pass: gather context → author N specs → compile+static_check → run through the
    DETERMINISTIC evolution screen/gate (scorer out of any LLM's reach) → record survivors + graveyard. The
    authored specs enter the cohort as `extra_seeds`; FarmLoop screens + scores them exactly like seeds, so
    the deterministic wall is the sole judge. Reproducible for a fixed (n, seed) offline."""
    bus = tool_bus or research_tool_bus()
    context = gather_context(bus)

    authored = author_candidates(n, llm_enabled=llm_enabled)
    extra_seeds = [draft.spec for draft, rec in authored if rec.compiled]

    loop = FarmLoop(settings=store.settings, store=store, market_data=market_data or _FixtureBars())
    # Cohort = the authored candidates only (no extra mutation/explore waves) so the report maps 1:1 onto
    # what the brain proposed; the deterministic screen + out-of-reach scorer decide PASS/STOP per candidate.
    cohort = loop.run_cohort(seed=seed, cohort_size=len(extra_seeds), explore_pct=0.0, extra_seeds=extra_seeds)

    return ResearchReport(
        n_requested=n,
        context_tools=context["tools"],  # type: ignore[arg-type]
        context_samples=context,
        authored=[rec for _, rec in authored],
        cohort=cohort,
        llm_enabled=llm_enabled,
        seed=seed,
    )


def _offline_store() -> Store:
    """A throwaway sqlite store so the CLI runs fully offline (no live DB, no keys). Real schedulers can pass
    their own Store; this keeps `python3 -m cosmu.lab.research` reproducible and side-effect-free in CI."""
    tmp = tempfile.mkdtemp(prefix="cosmu-research-")
    return Store(Settings(database_url=f"sqlite:///{tmp}/research.sqlite3", openrouter_api_key=None))


def _print_report(report: ResearchReport) -> None:
    print(f"RESEARCH BRAIN — authored {len(report.authored)} candidate(s) (n={report.n_requested}, seed={report.seed}, llm={'on' if report.llm_enabled else 'off (deterministic)'})")
    print(f"  context tools on the bus: {', '.join(report.context_tools)}")
    print("  AUTHORED (LLM proposes — structure only, thresholds in param_space):")
    for rec in report.authored:
        flag = "ok" if rec.compiled else ("invalid" if not rec.valid else "uncompiled")
        feats = ", ".join(rec.features) or "-"
        print(f"    [{flag}] {rec.name}  · template={rec.base_template} · features={feats} · sources={','.join(rec.data_sources)}")
        if rec.issues:
            print(f"           issues: {rec.issues}")
    print(f"  GATED (deterministic disposes — scorer out of reach): generated={report.cohort.generated} passed={report.cohort.passed} killed={report.cohort.killed} kill_rate={report.cohort.kill_rate}")
    if report.survivors:
        print("  SURVIVORS:")
        for s in report.survivors:
            print(f"    PASS  {s.name}  · deflated_sharpe={s.deflated_sharpe:.4f} · oos={s.oos_return_pct:+.2f}%")
    print("  GRAVEYARD (with reasons):")
    for g in report.graveyard:
        print(f"    STOP  {g.name}  · reasons={','.join(g.reasons) or 'screened_out'}")
    has_osint = any(f.name == "osint_air_activity" for f in FEATURE_REGISTRY)
    print(f"  OSINT source registered in feature vocabulary: {'yes (osint_air_activity)' if has_osint else 'no'}")


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Bounded autonomous research pass: gather context → author N specs → gate them deterministically (no keys).")
    parser.add_argument("--n", type=int, default=4, help="number of candidate strategies to author (default 4)")
    parser.add_argument("--seed", type=int, default=7, help="cohort seed for reproducibility (default 7)")
    args = parser.parse_args(argv)

    report = run_research_pass(_offline_store(), n=max(1, args.n), seed=args.seed)
    _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
