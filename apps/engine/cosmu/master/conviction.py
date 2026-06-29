# intent: the CONVICTION lane — the separate, much-more-chill evaluator for kind='llm' (= conviction = moonshot)
# strategies that CANNOT be backtested cleanly, so they NEVER touch the quant Gate (promote_brut / promote_cohort).
# Instead this applies a conviction CHECK + HARD GUARDRAILS (a per-bet max-loss cap, a small-size cap, a confidence
# floor, a real LIVE-capable venue, a declared maker/taker execution, an optional expiry) and emits a ConvictionVerdict.
# inputs: an AgentSpec carrying a ConvictionDecl + the operator's ConvictionCaps + the venue catalog; outputs: a
# ConvictionVerdict. invariants: this lane only ever PROPOSES — `armed` is ALWAYS False and a human must arm (it
# moves NO money, places NO order); it never up-sizes (only caps/rejects); it is keyless + deterministic + LLM-free
# (the LLM authored the thesis upstream; the dispose is pure here); and a kind='llm' spec routed here is structurally
# kept off the deterministic quant Gate (the choke point in lane_router.evaluate_by_lane refuses kind='llm').
#
# WHY THIS EXISTS. The taxonomy has TWO strategy MODELS: 'quant' (a typed StrategySpec → the locked 0.95 deflated-
# Sharpe + BH-FDR Gate) and 'llm' (an AgentSpec — a reasoning bet that has no clean backtest). Shoving an 'llm'
# conviction bet through the quant Gate is meaningless (there is no honest in-sample to deflate); it would either be
# auto-killed or, worse, fabricate a pass. The conviction lane is the honest home: it can't prove an edge statistically,
# so it bounds the DOWNSIDE (max-loss + small size) and demands a reviewable case (thesis + confidence + disconfirmer)
# that a HUMAN signs off before any capital is armed. Mirrors the snipe-lane "LLM proposes, deterministic disposes"
# split (cosmu/snipe/gate.py) but at the strategy-lane level, across any live venue (IBKR / Kraken / Polymarket).

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

from cosmu.spine.venue import VenueCatalog, default_catalog

if TYPE_CHECKING:  # avoid importing the heavy store/spec at module load — only types
    from cosmu.knowledge.store import Store
    from cosmu.strategy.agent_spec import AgentSpec

# The two strategy MODELS the codebase discriminates on (strategy_versions.kind / spec.kind). 'llm' is the conviction
# lane; everything else is the quant Gate. Kept as a tiny stable constant, not user input.
KIND_LLM = "llm"

KindRoute = Literal["quant", "conviction"]


@dataclass(frozen=True)
class ConvictionCaps:
    """The HARD money envelope the operator sets for the whole conviction lane — conservative by design (this lane
    can't prove an edge, so it bounds the loss). Every conviction bet is capped to these regardless of what the LLM
    proposed. All dollar caps are USD notional. Mirrors snipe.gate.ConvictionCaps in spirit (caps the LLM can't
    exceed) but lane-level + venue-agnostic."""

    max_loss_usd: Decimal = Decimal("50")   # the hardest a SINGLE conviction bet may be declared to lose
    max_size_usd: Decimal = Decimal("50")   # small-size cap — the conviction lane is intentionally tiny
    min_confidence: Decimal = Decimal("0.55")  # require ≥ 55% stated confidence to even propose


@dataclass(frozen=True)
class ConvictionVerdict:
    """The conviction lane's verdict on one bet. `eligible` = it cleared every guardrail (a human MAY now arm it).
    `armed` is ALWAYS False — this lane can only PROPOSE; arming real capital is a human click, never code, never the
    LLM. `requires_human` is True whenever eligible (the explicit "a human must arm" signal). The declared guardrails
    are echoed back so the UI/audit can show exactly what the human is signing off WITHOUT re-reading the spec."""

    eligible: bool
    reasons: list[str]
    armed: bool                 # INVARIANT: always False — propose-only, the human arms
    requires_human: bool        # True iff eligible — a human click is the only path to capital
    # echoed declaration (for the UI / audit trail) — the case + the caps the verdict was judged against
    thesis: str
    confidence: Decimal
    disconfirmer: str
    max_loss_usd: Decimal
    size_usd: Decimal
    venue: str
    execution: str
    expiry: datetime | None


def route_kind(spec: Any) -> KindRoute:
    """The TOP-LEVEL model discriminator: a kind='llm' strategy routes to the CONVICTION lane; everything else
    (quant) routes to the deterministic Gate. Pure read of `spec.kind` (default 'quant' for a legacy/stub spec),
    so this is the one place a runner asks "Gate or conviction?" instead of guessing by which function it called.
    Works on an AgentSpec, a StrategySpec, or any object carrying a `kind` attribute."""
    return "conviction" if getattr(spec, "kind", "quant") == KIND_LLM else "quant"


def is_conviction(spec: Any) -> bool:
    """True iff the spec routes to the conviction lane (kind='llm'). Thin alias for callers that want a boolean."""
    return route_kind(spec) == "conviction"


def assert_quant(spec: Any) -> None:
    """Guard for the QUANT Gate entry: raise loudly if a kind='llm' conviction spec is about to be fed to the
    deterministic Gate (promote_brut / promote_cohort). A conviction bet has no honest backtest to deflate — it must
    go through `propose_conviction`, never the Gate. This is the structural wall the taxonomy demands; call it at the
    spec→Gate boundary (lane_router does)."""
    if route_kind(spec) == "conviction":
        name = getattr(spec, "name", "<spec>")
        raise ValueError(
            f"spec {name!r} is kind='llm' (a conviction strategy) — it must NOT be routed through the quant Gate "
            f"(promote_brut/promote_cohort); route it to cosmu.master.conviction.propose_conviction instead. The "
            f"conviction lane bounds downside with guardrails (max-loss, small size, human-armed); the Gate proves "
            f"a statistical edge a conviction bet does not have."
        )


def _venue_reason(venue_id: str, *, catalog: VenueCatalog) -> str | None:
    """None when `venue_id` is a usable conviction venue; else the rejection reason. A conviction bet declares where
    it fills, so the venue must (a) exist in the catalog and (b) be LIVE-capable — NOT a paper-only venue (e.g.
    Alpaca, live_enabled=False), which can never host a real-money bet. Using the catalog's `live_enabled` as the
    source of truth means the rule tracks the catalog, not a hard-coded list that drifts (IBKR / Kraken / Polymarket
    are the live-capable execution venues today)."""
    try:
        venue = catalog.venue(venue_id)
    except KeyError:
        return f"unknown_venue({venue_id})"
    if not venue.live_enabled:
        return f"paper_only_venue({venue_id})"  # e.g. Alpaca — data/paper only, never a real-money conviction bet
    return None


def propose_conviction(
    spec: AgentSpec,
    caps: ConvictionCaps | None = None,
    *,
    catalog: VenueCatalog | None = None,
    now: datetime | None = None,
) -> ConvictionVerdict:
    """The conviction CHECK + GUARDRAILS for one kind='llm' bet. Pure function of (spec, caps, catalog, now) — same
    inputs → same verdict. It NEVER moves money and NEVER arms (the returned `armed` is always False); it only decides
    whether the bet is eligible for a HUMAN to arm, inside the operator's hard caps.

    Refuses a non-conviction spec loudly (a quant spec belongs on the Gate, not here). A kind='llm' spec carrying NO
    ConvictionDecl is observe-only → not eligible (reason 'no_conviction_declaration'), never an error. Otherwise it
    checks, in order: a stated confidence floor; the per-bet max-loss cap; the small-size cap; that the stake can't
    lose more than its own declared max-loss (a cash bet's worst case is its size); a real LIVE-capable venue (not
    paper-only Alpaca); a declared maker/taker execution; and the optional expiry. Any failed check appends a reason;
    the bet is eligible iff there are none."""
    if route_kind(spec) != "conviction":
        raise ValueError(
            f"propose_conviction got a kind={getattr(spec, 'kind', 'quant')!r} spec — the conviction lane is for "
            f"kind='llm' only; quant specs go through the deterministic Gate."
        )
    caps = caps or ConvictionCaps()
    catalog = catalog or default_catalog()
    now = now or datetime.now(tz=UTC)

    decl = getattr(spec, "conviction", None)
    if decl is None:
        # A kind='llm' spec with no conviction declaration is observe-only — it proposes nothing. Honest "not
        # eligible", not an error, so the observe-only agent path is unaffected.
        return ConvictionVerdict(
            eligible=False,
            reasons=["no_conviction_declaration"],
            armed=False,
            requires_human=False,
            thesis="",
            confidence=Decimal("0"),
            disconfirmer="",
            max_loss_usd=Decimal("0"),
            size_usd=Decimal("0"),
            venue="",
            execution="",
            expiry=None,
        )

    reasons: list[str] = []
    confidence = Decimal(str(decl.confidence))
    max_loss = Decimal(str(decl.max_loss_usd))
    size = Decimal(str(decl.size_usd))

    if confidence < caps.min_confidence:
        reasons.append(f"confidence_below_min({confidence}<{caps.min_confidence})")
    if max_loss > caps.max_loss_usd:
        reasons.append(f"max_loss_over_cap({max_loss}>{caps.max_loss_usd})")
    if size > caps.max_size_usd:
        reasons.append(f"size_over_cap({size}>{caps.max_size_usd})")
    # A cash bet can lose at most its stake — so a stake larger than the declared max-loss is an inconsistent
    # declaration (the max-loss would understate the real downside). Reject it rather than trust the smaller number.
    if size > max_loss:
        reasons.append(f"size_exceeds_max_loss({size}>{max_loss})")

    venue_reason = _venue_reason(decl.venue, catalog=catalog)
    if venue_reason is not None:
        reasons.append(venue_reason)
    if decl.execution not in ("maker", "taker"):
        reasons.append(f"bad_execution({decl.execution})")
    if decl.expiry is not None and now > decl.expiry:
        reasons.append("expired")

    eligible = not reasons
    return ConvictionVerdict(
        eligible=eligible,
        reasons=reasons or ["pass"],
        armed=False,                 # INVARIANT — propose-only, never auto-armed
        requires_human=eligible,     # eligible → a human must arm; not eligible → nothing to arm
        thesis=decl.thesis,
        confidence=confidence,
        disconfirmer=decl.disconfirmer,
        max_loss_usd=max_loss,
        size_usd=size,
        venue=decl.venue,
        execution=decl.execution,
        expiry=decl.expiry,
    )


def verdict_payload(spec: AgentSpec, verdict: ConvictionVerdict) -> dict[str, Any]:
    """The JSON-able snapshot of a conviction verdict — the queryable record (mirrors verdict_log's cohort payload
    shape, kind='conviction'). Decimals → str so it round-trips through JSON without precision loss."""
    return {
        "kind": "conviction",
        "name": getattr(spec, "name", None),
        "eligible": verdict.eligible,
        "armed": verdict.armed,
        "requires_human": verdict.requires_human,
        "reasons": list(verdict.reasons),
        "thesis": verdict.thesis,
        "confidence": str(verdict.confidence),
        "disconfirmer": verdict.disconfirmer,
        "max_loss_usd": str(verdict.max_loss_usd),
        "size_usd": str(verdict.size_usd),
        "venue": verdict.venue,
        "execution": verdict.execution,
        "expiry": verdict.expiry.isoformat() if verdict.expiry is not None else None,
    }


def persist_conviction_verdict(
    store: Store,
    spec: AgentSpec,
    verdict: ConvictionVerdict,
    *,
    version_id: str | None = None,
    run_id: str | None = None,
) -> bool:
    """Write ONE `gate_verdicts` row (payload kind='conviction') + a `conviction_proposed` event, so the conviction
    lane's verdicts are first-class queryable experiment-memory alongside the quant cohort verdicts — never a
    money-path write. `decision` = 'PROPOSED' when eligible (a human may arm), else 'BLOCKED'. Best-effort + offline-
    safe: any failure is swallowed + returns False (a verdict-persist must never break the propose path). Reuses the
    EXISTING gate_verdicts table (no schema change)."""
    from cosmu.knowledge.store import utcnow

    try:
        import json

        decision = "PROPOSED" if verdict.eligible else "BLOCKED"
        payload = verdict_payload(spec, verdict)
        if run_id is not None:
            payload["run_id"] = run_id
        if version_id is not None:
            payload["version_id"] = version_id
        store.rows(
            "INSERT INTO gate_verdicts(ts, decision, data_source, payload) VALUES (?, ?, ?, ?)",
            (utcnow(), decision, "conviction", json.dumps(payload, sort_keys=True)),
        )
        store.append_event(
            actor="master",
            kind="conviction_proposed",
            ref_type="strategy_version" if version_id else "conviction",
            ref_id=version_id or (run_id or payload.get("name") or "conviction"),
            payload={"decision": decision, "venue": verdict.venue, "size_usd": str(verdict.size_usd)},
        )
        return True
    except Exception:  # noqa: BLE001 — a verdict-persist failure must never break the propose path.
        return False


def open_conviction_track(
    store: Store,
    *,
    version_id: str,
    verdict: ConvictionVerdict,
) -> str | None:
    """Open the FORWARD-OBSERVE track for an eligible conviction bet — born honest at the declared stake
    (equity = size_usd, return 0), on the SAME zero-real-capital paper machinery the quant survivors use. This makes
    a conviction bet first-class in the lifecycle (it gets a track), WITHOUT arming real money: the track is paper /
    observe-only, NOT 'live' (a human still arms live separately). Refuses an ineligible verdict (returns None) so a
    blocked bet never gets a track. Delegates the insert to tracks.open_paper_track (the one sanctioned track birth)."""
    if not verdict.eligible:
        return None
    from cosmu.master.tracks import open_paper_track

    return open_paper_track(
        store,
        version_id=version_id,
        starting_capital=verdict.size_usd,
        venue_id=verdict.venue,
        store=store,
    )
