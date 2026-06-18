# intent: the AUTHORING ENTRYPOINT for LLM/agent strategies — the prod front door to open_agent_strategy (which
# until now was only ever exercised by tests, so the kind='llm' model never actually got born in prod). Two ways
# in, ONE exit (open_agent_strategy → a kind='llm', observe-only, ZERO-CAPITAL strategy_version):
#   1. a typed AgentSpec serialized as JSON (the authored format), and
#   2. an UNSTRUCTURED natural-language idea — branched off the EXISTING NL intake's THINK step
#      (cosmu.mind.thinker.interpret, the same standardizer cosmu.lab.nlp_intake uses for quant specs) so a vibe
#      that ISN'T backtestable (a journalist's call, a small-cap social catalyst) routes to the agent model
#      instead of being forced through the quant author.
# invariants: observe-only / NO capital (open_agent_strategy opens no track/position/order); offline-safe and
# hermetic (the LLM standardization seam is injected — None → the deterministic keyword brain, no key/network);
# the mandatory exit policy is filled with CONCRETE conservative defaults (an agent spec is exit-complete by
# construction — agents aren't grid-fitted, so these are real fractions, not param_space). See
# docs/epics/agentic-lane.md.
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from cosmu.ingest.document_handler import DocumentChunk
from cosmu.mind.thinker import InterpretFn, ThinkingReport, interpret
from cosmu.strategy.agent_author import open_agent_strategy
from cosmu.strategy.agent_spec import AgentExitPolicy, AgentSpec

if TYPE_CHECKING:
    from cosmu.knowledge.store import Store

# CONCRETE, bounded-risk exit defaults for an NL-authored agent (the operator edits them per strategy later). An
# AgentSpec MUST carry an exit (no exit-less LLM strategy) and an agent is NOT grid-fitted, so these are honest
# concrete fractions, never param_space magic numbers.
DEFAULT_EXIT = AgentExitPolicy(stop_loss_pct=0.05, take_profit_pct=0.2, trailing_pct=0.03)
# When an NL idea names no asset we fall back to the deepest, most-liquid product so the spec is valid (symbols is
# mandatory, min 1) — the author should set symbols explicitly; this is a documented fallback, not a guess at edge.
DEFAULT_SYMBOLS: tuple[str, ...] = ("BTCUSDT",)
DEFAULT_VENUES: tuple[str, ...] = ("binance",)

# Conservative ticker detection from free text. A perp/spot pair (BTCUSDT, ETH-PERP) OR a handful of common asset
# names mapped to their canonical Binance symbol. Deliberately narrow — a false symbol is worse than the default.
_SYMBOL_RE = re.compile(r"\b([A-Z]{2,10}(?:USDT|USDC|USD|PERP))\b")
_NAME_TO_SYMBOL: dict[str, str] = {
    "bitcoin": "BTCUSDT", "btc": "BTCUSDT",
    "ethereum": "ETHUSDT", "eth": "ETHUSDT",
    "solana": "SOLUSDT", "sol": "SOLUSDT",
    "dogecoin": "DOGEUSDT", "doge": "DOGEUSDT",
    "ripple": "XRPUSDT", "xrp": "XRPUSDT",
}


def extract_symbols(text: str) -> list[str]:
    """Best-effort symbol extraction from an NL idea: explicit pairs first (BTCUSDT, ETH-PERP), then common asset
    names. Order-preserving + deduped. Empty when nothing is recognised (the caller falls back to DEFAULT_SYMBOLS)
    — narrow on purpose: a fabricated symbol would point the agent at the wrong market."""
    found: list[str] = []
    for sym in _SYMBOL_RE.findall(text or ""):
        if sym not in found:
            found.append(sym)
    low = (text or "").lower()
    for keyword, sym in _NAME_TO_SYMBOL.items():
        if re.search(rf"\b{re.escape(keyword)}\b", low) and sym not in found:
            found.append(sym)
    return found


def _name_from_report(report: ThinkingReport) -> str:
    """A short human title from the standardized thesis (the agent's NL summary is its primary artifact)."""
    words = report.thesis.strip().split()
    short = " ".join(words[:8]) if words else "Unstructured NL agent"
    return f"{short[:56]} (agent)"


def agent_from_report(
    report: ThinkingReport,
    *,
    name: str | None = None,
    symbols: list[str] | None = None,
    venues: list[str] | None = None,
    exit: AgentExitPolicy | None = None,
    max_position_pct: float = 0.05,
    mode: str = "autonomous",
    cadence: str = "4h",
    sources: list[str] | None = None,
) -> AgentSpec:
    """Map a standardized NL ThinkingReport (the EXISTING intake's THINK output) into a typed AgentSpec — the
    branch from the quant author. The thesis + edge + disconfirmer become the agent's NL rationale (its primary
    artifact); the report's recommended-feature TERMS become the free-form `sources` the agent looks at (no
    allow/deny list); symbols are explicit → extracted from the thesis → the documented default; the mandatory
    exit is filled with concrete bounded-risk defaults. Pure + offline — no store, no IO, no LLM here."""
    syms = list(symbols) if symbols else extract_symbols(f"{report.thesis} {report.edge_hypothesis}") or list(DEFAULT_SYMBOLS)
    parts = [report.thesis.strip()]
    if report.edge_hypothesis.strip():
        parts.append(f"Edge: {report.edge_hypothesis.strip()}")
    if report.disconfirmer.strip():
        parts.append(f"Disconfirmer: {report.disconfirmer.strip()}")
    rationale = " ".join(p for p in parts if p) or "Unstructured NL idea (no explicit thesis extracted)."
    srcs = list(sources) if sources is not None else list(dict.fromkeys(report.recommended_features))
    return AgentSpec(
        name=name or _name_from_report(report),
        rationale=rationale,
        symbols=syms,
        venues=list(venues) if venues else list(DEFAULT_VENUES),
        exit=exit or DEFAULT_EXIT.model_copy(),  # copy the shared default so no two specs alias one exit policy
        max_position_pct=max_position_pct,
        sources=srcs,
        mode=mode,  # type: ignore[arg-type]
        cadence=cadence,  # type: ignore[arg-type]
    )


def draft_agent_from_brief(
    brief: str,
    *,
    name: str | None = None,
    symbols: list[str] | None = None,
    venues: list[str] | None = None,
    exit: AgentExitPolicy | None = None,
    max_position_pct: float = 0.05,
    mode: str = "autonomous",
    cadence: str = "4h",
    llm: InterpretFn | None = None,
) -> tuple[AgentSpec, ThinkingReport]:
    """Turn one NL idea (a vibe / abstract) into a typed AgentSpec by REUSING the intake's THINK step
    (thinker.interpret) — the same standardizer the quant pipeline runs, branched here toward the agent model.
    `llm` is the injected interpret seam (None → deterministic keyword standardization, fully offline). Returns
    (AgentSpec, ThinkingReport) so the caller can audit how the prose was standardized. Authors nothing — pure."""
    chunk = DocumentChunk(path="<brief>", chunk_id="brief-000", text=brief or "", metadata={"parser": "brief"})
    report = interpret([chunk], llm=llm)
    agent = agent_from_report(
        report,
        name=name,
        symbols=symbols,
        venues=venues,
        exit=exit,
        max_position_pct=max_position_pct,
        mode=mode,
        cadence=cadence,
    )
    return agent, report


def open_agent_from_brief(
    store: Store,
    brief: str,
    *,
    name: str | None = None,
    symbols: list[str] | None = None,
    venues: list[str] | None = None,
    exit: AgentExitPolicy | None = None,
    max_position_pct: float = 0.05,
    mode: str = "autonomous",
    cadence: str = "4h",
    llm: InterpretFn | None = None,
    origin: str = "agent-nl",
) -> tuple[str, AgentSpec]:
    """The NL → AgentSpec → kind='llm' strategy_version path: standardize the brief, author the spec, and persist
    it via open_agent_strategy (observe-only, ZERO capital). Returns (version_id, AgentSpec)."""
    agent, _report = draft_agent_from_brief(
        brief,
        name=name,
        symbols=symbols,
        venues=venues,
        exit=exit,
        max_position_pct=max_position_pct,
        mode=mode,
        cadence=cadence,
        llm=llm,
    )
    version_id = open_agent_strategy(store, agent, origin=origin)
    return version_id, agent


def _load_spec(path: str) -> AgentSpec:
    text = Path(path).read_text(encoding="utf-8")
    return AgentSpec.model_validate_json(text)


def _csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()] or None


def main(argv: list[str] | None = None) -> int:
    """CLI authoring front door. Either author a typed AgentSpec from JSON, or standardize an unstructured NL idea
    into one and author it. ZERO capital — open_agent_strategy opens no track/position/order.

    Examples:
      python3 -m cosmu.strategy.author_agent --spec my_agent.json
      python3 -m cosmu.strategy.author_agent --brief "small-cap social catalyst on a credible X account" --symbols DOGEUSDT
      python3 -m cosmu.strategy.author_agent --idea-file idea.md --dry-run
    """
    parser = argparse.ArgumentParser(
        description="Author a kind='llm' agent strategy from a typed AgentSpec JSON or an unstructured NL idea "
        "(observe-only, ZERO capital). NL standardization is deterministic + offline."
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--spec", help="path to a JSON file holding a typed AgentSpec")
    src.add_argument("--brief", help="an unstructured NL idea (inline text)")
    src.add_argument("--idea-file", help="path to a file holding an unstructured NL idea (.md/.txt)")
    parser.add_argument("--name", help="override the strategy name")
    parser.add_argument("--symbols", help="comma-separated symbols (NL path; default: detected or BTCUSDT)")
    parser.add_argument("--venues", help="comma-separated venues (NL path; default: binance)")
    parser.add_argument("--dry-run", action="store_true", help="print the resolved AgentSpec JSON; do NOT persist")
    args = parser.parse_args(argv)

    if args.spec:
        agent = _load_spec(args.spec)
    else:
        brief = args.brief if args.brief is not None else Path(args.idea_file).read_text(encoding="utf-8")
        # CLI keeps standardization deterministic/offline (llm=None): the rationale is the NL thesis, structure-only.
        agent, _report = draft_agent_from_brief(
            brief, name=args.name, symbols=_csv(args.symbols), venues=_csv(args.venues)
        )
    if args.name and args.spec:
        agent = agent.model_copy(update={"name": args.name})

    if args.dry_run:
        print(json.dumps(agent.model_dump(mode="json"), indent=2, sort_keys=True))
        return 0

    # Real run: persist via the ONE kind='llm' write site. Offline-safe (no LLM needed to author).
    from cosmu.config.settings import Settings
    from cosmu.knowledge.store import Store

    store = Store(Settings())
    origin = "agent" if args.spec else "agent-nl"
    version_id = open_agent_strategy(store, agent, origin=origin)
    print(
        f"AUTHORED kind='llm' agent (observe-only, $0) — version_id={version_id} "
        f"name={agent.name!r} symbols={agent.symbols} venues={agent.venues}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
