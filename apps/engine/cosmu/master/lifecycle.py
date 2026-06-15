# intent: the ADDITIVE lifecycle-trace audit — a thin, append-only journal of a strategy version's
# backtest → paper → forward → live-ready journey, written onto the EXISTING events ledger as new event-kind
# strings (NO schema change, NO money path touched). inputs: the store + a version_id + a lifecycle kind +
# optional meta; outputs: one appended row on `events`; invariants: write-only audit (never gates, never
# promotes, never arms real money — the existing interlocks in live_eligibility/execution stay the sole
# authority); reuses store.append_event verbatim; unknown kinds raise so the vocabulary stays closed; fully
# deterministic + LLM-free. The READ side (api/routers/readiness) composes the existing verdicts over this
# trace — this module only ever WRITES the trace marks.

from __future__ import annotations

from typing import Any

from cosmu.knowledge.store import Store

# The CLOSED lifecycle vocabulary — the named transition points of a version's journey. These are AUDIT marks
# layered onto the append-only events ledger; they never replace or alter the operational events the money path
# already writes (track_opened, live_launched, live_defunded, …). A few intentionally MIRROR an operational
# event at the same transition so the lifecycle trace is queryable on ONE kind-set without re-deriving meaning:
#   screened_passed — the deterministic gate passed a screen (a track is about to open)
#   paper_started   — the standalone paper track opened (paper clock begins)
#   paper_matured   — the paper track reached >= PAPER_MIN_DAYS net-positive (forward-proven)
#   live_eligible   — both HARD preconditions (paper maturity AND proven regime) now pass
#   live_armed      — a human armed/launched the strategy live
#   live_disarmed   — the strategy was defunded / disarmed
#   strategy_killed — the strategy was graveyarded / killed
LIFECYCLE_KINDS: frozenset[str] = frozenset(
    {
        "screened_passed",
        "paper_started",
        "paper_matured",
        "live_eligible",
        "live_armed",
        "live_disarmed",
        "strategy_killed",
    }
)

# Lifecycle order — the canonical position of each stage along the journey. Used by the read side to render a
# monotone trace (and to pick the LATEST reached stage). Not a gate: a version may skip stages (e.g. killed
# before maturity), and the audit never enforces ordering.
LIFECYCLE_ORDER: tuple[str, ...] = (
    "screened_passed",
    "paper_started",
    "paper_matured",
    "live_eligible",
    "live_armed",
    "live_disarmed",
    "strategy_killed",
)

# The actor stamped on lifecycle audit marks — same convention as the deterministic master path.
_ACTOR = "master"


def emit_lifecycle_event(
    store: Store,
    version_id: str,
    kind: str,
    meta: dict[str, Any] | None = None,
    *,
    actor: str = _ACTOR,
) -> None:
    """Append ONE lifecycle audit mark for `version_id` onto the existing events ledger. Pure write-only
    journaling: it never reads back, never gates, never promotes, never arms money — the live_eligibility /
    execution interlocks remain the sole authority over what can trade. `kind` must be one of LIFECYCLE_KINDS
    (a closed vocabulary; an unknown kind raises so the trace can't silently drift). `meta` is stored verbatim
    as the event payload (defaults to empty). Reuses store.append_event verbatim, so it works on both backends
    and stays inside the append-only invariant."""
    if kind not in LIFECYCLE_KINDS:
        raise ValueError(f"unknown lifecycle kind {kind!r}; expected one of {sorted(LIFECYCLE_KINDS)}")
    store.append_event(
        actor=actor,
        kind=kind,
        ref_type="strategy_version",
        ref_id=version_id,
        payload=meta or {},
    )
