# intent: the NL→STRATEGY PIPELINE orchestrator — chain the four scaffold agents so a natural-language idea (a
# vibe, an abstract, a passage from an old book, a research PDF) becomes a typed StrategySpec that flows into the
# EXISTING inbox/Gate. The chain: (1) DocumentHandler.parse_file → chunks; (2) thinker.interpret(chunks, llm) →
# a standardized ThinkingReport; (3) matcher.match → registry-grounded features + unmapped claims; (4)
# signal_builder.build_signals → typed PrecomputedSignal specs for the complex claims; (5) author.draft_from_brief
# synthesizes a StrategySpec from a brief built out of the report + matched features, which is dropped into
# strategies/inbox via lab.inbox.queue_idea (the SAME intake the boot scan / autonomy tick later gates).
# invariants: this NEVER duplicates the existing intake (it ENDS at queue_idea / scan_inbox) and NEVER touches
# the scorer/Gate/spec-schema; the LLM is gated behind an injected callable (offline-testable); every step is
# persisted as an audited Store event (kind 'nl_*'); offline + idempotent (the document's content-hash gates
# re-processing, mirroring the inbox scanner). NEVER on a money path — the deterministic Gate alone disposes.

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from cosmu.ingest.document_handler import DocumentChunk, DocumentHandler
from cosmu.lab.author import AuthorDraft, draft_from_brief
from cosmu.lab.inbox import QueuedIdea, queue_idea
from cosmu.mind.matcher import MatcherResult, match
from cosmu.mind.signal_builder import PrecomputedSignal, build_signals
from cosmu.mind.thinker import InterpretFn, ThinkingReport, interpret

if TYPE_CHECKING:
    from cosmu.knowledge.store import Store


@dataclass
class NlIntakeResult:
    """The full audit trail of one NL→strategy run."""

    source: str
    chunks: list[DocumentChunk]
    report: ThinkingReport
    matched: MatcherResult
    signals: list[PrecomputedSignal]
    draft: AuthorDraft
    queued: QueuedIdea | None = None  # the inbox drop (None when queue is skipped / store absent)
    explore_version_id: str | None = None  # the explore-lane version opened (None when explore is off / draft invalid)
    agent_version_id: str | None = None  # the kind='llm' AgentSpec authored (None unless agent_lane is on)
    notes: list[str] = field(default_factory=list)


def _record(store: "Store | None", kind: str, payload: dict) -> None:
    """Persist one pipeline step as an audited event. Best-effort — a store hiccup must not break the chain
    (the pipeline is advisory authoring; the Gate alone disposes)."""
    if store is None:
        return
    try:
        store.append_event(actor="agent", kind=kind, ref_type="strategy_spec", payload=payload)
    except Exception:  # noqa: BLE001 — audit is best-effort; never raise into the pipeline
        pass


def _build_brief(report: ThinkingReport, matched: MatcherResult, signals: list[PrecomputedSignal]) -> str:
    """Synthesize the prose brief draft_from_brief consumes. It carries the standardized thesis/edge/regime, the
    registry feature TERMS (so the author's keyword detector + feature validation pick them up), and the
    precomputed-signal claims (named so the author records them as research context). No thresholds — structure
    only, exactly as the author contract requires."""
    lines = [report.thesis.strip()]
    if report.edge_hypothesis:
        lines.append(f"Edge: {report.edge_hypothesis.strip()}")
    if report.regime and report.regime != "any":
        lines.append(f"Regime: {report.regime}.")
    if matched.matched_features:
        lines.append("Use features: " + ", ".join(matched.matched_features) + ".")
    if signals:
        lines.append("Precomputed alt-data signals: " + ", ".join(s.name for s in signals) + ".")
    if report.disconfirmer:
        lines.append(f"Disconfirmer: {report.disconfirmer.strip()}")
    return "\n".join(l for l in lines if l.strip())


def run_pipeline(
    source: str | Path,
    *,
    store: "Store | None" = None,
    llm: InterpretFn | None = None,
    queue: bool = True,
    inbox_dir: Path | None = None,
    explore: bool = False,
    agent_lane: bool = False,
    agent_symbols: list[str] | None = None,
    agent_venues: list[str] | None = None,
) -> NlIntakeResult:
    """Run the full NL→strategy chain on one document and (optionally) drop the synthesized brief into the inbox.

    `source` is a file path. `llm` is the injected interpret seam (None → deterministic standardization, fully
    offline). `store` enables the audited event trail + the inbox queue. `queue=False` runs the chain WITHOUT
    writing to the inbox (preview/dry-run). Returns the full NlIntakeResult audit trail. Offline-safe; the only
    side effects are Store events + (when queue) one strategies/inbox/*.md file — the Gate later disposes.

    `explore=True` routes the synthesized vibe into the VIBE/EXPLORE disposition INSTEAD of the strict gate: the
    drafted spec is persisted lane='explore' (paper, ZERO capital) and a zero-capital paper track is opened so the
    SIM executor observes its own logic forward (observe-only). A vibe GRADUATES to the gate-lane only if it later
    clears the unchanged gate — explore NEVER loosens or bypasses the gate, it just lets a low-confidence idea be
    watched on paper first. Default False keeps every existing caller byte-for-byte unchanged (queue-to-gate path).

    `agent_lane=True` routes the SAME standardized report to the LLM/agent MODEL instead of the quant inbox: an
    UNSTRUCTURED idea (a journalist's call, a social catalyst — not backtestable, no clean registry features)
    becomes a typed AgentSpec and is authored as a kind='llm', observe-only, ZERO-capital strategy_version (Gate B
    + a human launch later). This is the branch the dead `open_agent_strategy` write site needed; it is mutually
    exclusive with the quant queue/explore disposition (an idea goes to one model, not both). Default False keeps
    every existing caller unchanged.
    """
    notes: list[str] = []

    # (1) PARSE — pure, offline, idempotent (chunk ids derive from file bytes).
    chunks = DocumentHandler().parse_file(source)
    content_hash = chunks[0].metadata.get("content_hash", "") if chunks else ""
    _record(
        store,
        "nl_document_parsed",
        {"source": str(source), "chunks": len(chunks), "content_hash": content_hash, "parser": chunks[0].metadata.get("parser") if chunks else None},
    )

    # (2) THINK — standardize prose → modern computable terms (LLM-gated, offline fallback).
    report = interpret(chunks, llm=llm)
    _record(
        store,
        "nl_interpreted",
        {
            "source": str(source),
            "content_hash": content_hash,
            "via": report.via,
            "regime": report.regime,
            "recommended_features": report.recommended_features,
            "has_disconfirmer": bool(report.disconfirmer),
        },
    )

    # (3) MATCH — ground feature terms against the enabled FEATURE_REGISTRY (deterministic).
    matched = match(report)
    _record(
        store,
        "nl_matched",
        {
            "source": str(source),
            "content_hash": content_hash,
            "matched_features": matched.matched_features,
            "unmapped_claims": matched.unmapped_claims,
        },
    )

    # (4) BUILD — complex claims → typed PrecomputedSignal specs (emit spec only, no heavy compute).
    signals = build_signals(matched.unmapped_claims, report=report)
    _record(
        store,
        "nl_signals_built",
        {
            "source": str(source),
            "content_hash": content_hash,
            "signals": [{"name": s.name, "provider": s.provider, "metric": s.metric, "disconfirmer": s.disconfirmer} for s in signals],
        },
    )

    # (5) SYNTHESIZE — author a typed StrategySpec from the standardized brief (REUSE draft_from_brief; the spec
    # builder GUARANTEES thresholds stay in param_space). The matched features are passed explicitly so the
    # author validates them to the chosen asset class.
    brief = _build_brief(report, matched, signals)
    draft = draft_from_brief(
        brief,
        features=matched.matched_features or None,
        llm_enabled=False,  # the LLM already ran at the THINK step — keep authoring deterministic + offline
        store=store,
    )
    _record(
        store,
        "nl_drafted",
        {
            "source": str(source),
            "content_hash": content_hash,
            "name": draft.spec.name,
            "valid": draft.valid,
            "features": draft.features,
            "issues": draft.issues,
        },
    )

    queued: QueuedIdea | None = None
    explore_version_id: str | None = None
    agent_version_id: str | None = None
    if agent_lane and store is not None:
        # AGENT MODEL branch: the unstructured idea routes to kind='llm' instead of the quant inbox. Reuse the
        # SAME standardized `report` (the THINK step already ran) — agent_from_report maps it to a typed AgentSpec
        # and open_agent_strategy persists it observe-only / ZERO capital. Lazy import to avoid a module cycle
        # (author_agent → agent_author → store), mirroring the explore branch's local import.
        from cosmu.strategy.agent_author import open_agent_strategy
        from cosmu.strategy.author_agent import agent_from_report

        agent = agent_from_report(report, name=draft.spec.name, symbols=agent_symbols, venues=agent_venues)
        agent_version_id = open_agent_strategy(store, agent, origin="agent-nl")
        _record(
            store,
            "nl_agent_authored",
            {
                "source": str(source),
                "content_hash": content_hash,
                "name": agent.name,
                "version_id": agent_version_id,
                "symbols": agent.symbols,
                "venues": agent.venues,
                "sources": agent.sources,
            },
        )
    elif explore and store is not None and draft.valid:
        # VIBE/EXPLORE disposition: a low-confidence NL idea is NOT shoved at the strict gate. Persist the drafted
        # spec lane='explore' (paper, ZERO capital) and open a zero-capital paper track so the SIM executor
        # observes its own logic forward. It graduates to the gate-lane only if it later clears the unchanged gate.
        from cosmu.master.zero_capital import enter_explore

        result = enter_explore(store, draft.spec)
        explore_version_id = result.strategy_version_id if (result and result.opened) else None
        _record(
            store,
            "nl_explored",
            {
                "source": str(source),
                "content_hash": content_hash,
                "name": draft.spec.name,
                "version_id": explore_version_id,
                "opened": bool(result and result.opened),
            },
        )
        if explore_version_id is None:
            notes.append("explore requested but the vibe could not be paper-tracked (unresolved symbol / duplicate)")
    elif explore and (store is None or not draft.valid):
        notes.append("explore requested but skipped (no store or invalid draft) — chain ran without paper-tracking")
    elif queue and store is not None:
        # Drop the synthesized brief into the EXISTING inbox intake — this is the ONLY write into the pipeline
        # the rest of the system already owns (the boot scan / autonomy tick translates + gates it). We queue the
        # standardized BRIEF (not a raw spec) so the existing scanner re-runs the deterministic author path and
        # the Gate disposes — never duplicating intake.
        queued = queue_idea(store, brief, name=draft.spec.name, inbox_dir=inbox_dir)
        _record(
            store,
            "nl_queued",
            {"source": str(source), "content_hash": content_hash, "filename": queued.filename, "path": queued.path},
        )
    elif queue and store is None:
        notes.append("queue requested but no store provided — chain ran in dry-run mode")

    return NlIntakeResult(
        source=str(source),
        chunks=chunks,
        report=report,
        matched=matched,
        signals=signals,
        draft=draft,
        queued=queued,
        explore_version_id=explore_version_id,
        agent_version_id=agent_version_id,
        notes=notes,
    )
