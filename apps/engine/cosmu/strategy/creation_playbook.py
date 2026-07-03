# intent: the STRATEGY-CREATION PLAYBOOK — a set of deterministic PRE-GATE rules that make every authored
# strategy realistic / coherent / live-feasible BEFORE it ever reaches the (locked) Gate, so a human or an LLM
# chatting with Claude cannot author something structurally stupid. This is NOT the Gate and it moves no money:
# it is the authoring railing that runs ALONGSIDE static_check.validate_spec + the inbox lint. inputs: a typed
# StrategySpec (+ the venue catalog); outputs: a PlaybookReport (pass / warn / fail + per-rule reasons).
# invariants: PURE + DETERMINISTIC (no DB, no network, no clock) for the rule checks; NEVER mutates the spec;
# NEVER touches the scorer / FDR / cohort math. The learning-loop scaffold (record_outcome / learned_maker_fill)
# is the ONLY part that reads/writes the event ledger, and it is offline-safe (store=None → conservative defaults).
#
# The rules (each returns one PlaybookFinding):
#   1. execution_coherence — a maker strategy must have maker (passive/reversion) LOGIC, a taker taker logic. A
#      breakout/ORB/FVG setup declared maker is a hard contradiction (a breakout must CROSS to chase).
#   2. venue_feasibility — the declared execution mode must be POSSIBLE on the chosen venue (IBKR / Kraken /
#      Polymarket / Binance / …, NOT Alpaca which is paper-only) and the venue must exist in the catalog. Plus a
#      light size-vs-liquidity sanity check.
#   3. fee_realism      — fees are venue-derived (never spec-set); flag an edge that DEPENDS on earning a maker
#      rebate, since the backtest never credits one (the no-spread-credit floor).
#   4. disconfirmer     — a NAMED disconfirmer is required (spec.disconfirmer, or a disconfirmer cue in the
#      rationale): the disconfirmable thesis is exactly what the Gate is testing.
#   5. no_lookahead     — structural look-ahead guard (a feature lookback must be strictly positive; a
#      settle-at-resolution flag only means something for a prediction universe).

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from cosmu.data.backtest import DEFAULT_MAKER_FILL, MakerFillModel
from cosmu.spine.venue import VenueCatalog, default_catalog
from cosmu.strategy.spec import StrategySpec

if TYPE_CHECKING:
    from cosmu.knowledge.store import Store

Severity = Literal["pass", "warn", "fail"]

# Disconfirmer cues — a rationale that names ANY of these is treated as carrying a disconfirmer even without the
# dedicated `disconfirmer` field (so the existing corpus, which discusses disconfirmation in prose, still passes).
_DISCONFIRMER_CUES: tuple[str, ...] = (
    "disconfirm", "falsif", "invalidat", "would fail", "fails if", "fail if", "kill if", "no edge if",
    "stop if", "reject if", "prove it wrong", "proven wrong", "shuffle", "placebo", "null control",
    "negative control", "ic ≤", "ic <=", "loses to buy", "lose to buy",
)
# Maker-rebate cues — an edge whose rationale leans on EARNING the spread/rebate cannot survive the honest maker
# fill model (the rebate is never credited), so flag it.
_REBATE_CUES: tuple[str, ...] = (
    "rebate", "earn the spread", "capture the spread", "free spread", "collect the spread", "spread capture",
)
# Entry ops that BUY/SELL INTO the move (chase strength) vs FADE it. A maker (passive) order is natural for a
# FADE (post a bid below, get filled on a dip); chasing a breakout needs a TAKER cross.
_CHASE_OPS: frozenset[str] = frozenset({"gt", "gte", "cross_up"})
_FADE_OPS: frozenset[str] = frozenset({"lt", "lte", "cross_down"})


@dataclass(frozen=True)
class PlaybookFinding:
    """One rule's verdict. `severity` is per-rule (pass | warn | fail); `reason` is a human-readable, specific
    explanation an author (human or LLM) can act on."""

    rule: str
    severity: Severity
    reason: str


@dataclass
class PlaybookReport:
    """The aggregate authoring verdict: the WORST per-rule severity + every finding. `ok()` is True unless a rule
    FAILED (a warn-only report is allowed through the authoring path, surfaced as advice)."""

    verdict: Severity
    findings: list[PlaybookFinding] = field(default_factory=list)

    def ok(self) -> bool:
        return self.verdict != "fail"

    def fails(self) -> list[PlaybookFinding]:
        return [f for f in self.findings if f.severity == "fail"]

    def warns(self) -> list[PlaybookFinding]:
        return [f for f in self.findings if f.severity == "warn"]

    def summary(self) -> str:
        """A one-line manifest: 'PASS' / 'WARN: …' / 'FAIL: …' with the offending rules — for the lint table."""
        if self.verdict == "pass":
            return "PASS"
        offenders = self.fails() if self.verdict == "fail" else self.warns()
        rules = ", ".join(f"{f.rule}" for f in offenders)
        return f"{self.verdict.upper()}: {rules}"


def _worst(severities: list[Severity]) -> Severity:
    if "fail" in severities:
        return "fail"
    if "warn" in severities:
        return "warn"
    return "pass"


# --------------------------------------------------------------------------- the five rules


def check_execution_coherence(spec: StrategySpec) -> PlaybookFinding:
    """A MAKER strategy must have maker (passive) logic; a TAKER strategy taker logic. Taker is always coherent
    (crossing is always feasible) → PASS. For maker / both: a breakout setup (ORB / FVG) is a hard contradiction
    (a breakout must CROSS to chase, it cannot rest passively) → FAIL; entries that all CHASE strength (gt /
    cross_up for a long, the mirror for a short) are suspicious for a passive order → WARN; a fade/reversion
    shape → PASS."""
    mode = getattr(spec, "execution_mode", "taker")
    if mode == "taker":
        return PlaybookFinding("execution_coherence", "pass", "taker mode — crossing is always feasible")

    setup = spec.setup
    if setup is not None and (setup.orb is not None or setup.fvg is not None):
        return PlaybookFinding(
            "execution_coherence",
            "fail",
            f"{mode} mode declared with a breakout setup (ORB/FVG): a breakout must CROSS the spread to chase the "
            "move — it cannot be posted as a passive maker order. Use execution_mode='taker', or drop the breakout "
            "setup for a reversion/fade entry.",
        )

    # Fade vs chase: for a long (d=+1) a FADE buys weakness (lt/cross_down); a short (d=-1) fades strength
    # (gt/cross_up). An entry that chases the move is taker-shaped.
    direction = getattr(spec, "direction", 1)
    fade_ops = _FADE_OPS if direction != -1 else _CHASE_OPS
    chase_ops = _CHASE_OPS if direction != -1 else _FADE_OPS
    ops = [c.op for c in spec.entry]
    if ops and all(op in chase_ops for op in ops) and not any(op in fade_ops for op in ops):
        return PlaybookFinding(
            "execution_coherence",
            "warn",
            f"{mode} mode but every entry CHASES the move ({', '.join(sorted(set(ops)))}); a passive maker order is "
            "natural for a FADE/reversion (buy weakness / sell strength). Confirm the entry can realistically rest "
            "passively, or screen it taker.",
        )
    return PlaybookFinding("execution_coherence", "pass", f"{mode} mode with reversion/fade-compatible entry logic")


def check_venue_feasibility(spec: StrategySpec, catalog: VenueCatalog) -> PlaybookFinding:
    """The declared execution mode must be POSSIBLE on the chosen venue. Every declared venue must exist in the
    catalog; a maker (or both) mode is INFEASIBLE on a paper-only venue (Alpaca — it can place no real order). A
    light size-vs-liquidity sanity check (declared min liquidity below the venue's min notional) is a WARN."""
    declared = list(spec.universe.venues or [])
    unknown = [v for v in declared if not _venue_exists(catalog, v)]
    if unknown:
        return PlaybookFinding(
            "venue_feasibility",
            "fail",
            f"unknown venue(s) {unknown}: not in the catalog, so the strategy cannot be priced or executed. Declare "
            "a real venue (binance / kraken / ibkr / polymarket / hyperliquid / okx / coinbase).",
        )
    mode = getattr(spec, "execution_mode", "taker")
    if mode in ("maker", "both"):
        # The venue the spec is actually priced/executed against (the same resolution the screen uses).
        primary = catalog.venue_for(declared)
        if not primary.supports_maker():
            return PlaybookFinding(
                "venue_feasibility",
                "fail",
                f"{mode} mode is infeasible on '{primary.id}' ({primary.name}): it is a paper-only data account "
                "and can place no real (maker) order. Choose a real order-book venue (ibkr / kraken / polymarket / "
                "binance / hyperliquid).",
            )
        if spec.universe.min_liquidity_usd < float(primary.min_notional):
            return PlaybookFinding(
                "venue_feasibility",
                "warn",
                f"declared min_liquidity_usd ({spec.universe.min_liquidity_usd:g}) is below '{primary.id}' "
                f"min_notional ({primary.min_notional}); the order size may be infeasible at this venue's depth.",
            )
    return PlaybookFinding("venue_feasibility", "pass", "execution mode is feasible on the declared venue(s)")


def check_fee_realism(spec: StrategySpec, catalog: VenueCatalog) -> PlaybookFinding:
    """Fees are venue-derived (never spec-set), so the realism failure mode is an edge that DEPENDS on earning a
    maker rebate: the backtest NEVER credits one (the no-spread-credit floor), so such an edge will evaporate
    under the honest fill model. Flag it as a WARN when the rationale leans on the rebate/spread-capture."""
    mode = getattr(spec, "execution_mode", "taker")
    rationale = (spec.rationale or "").lower()
    if mode in ("maker", "both") and any(cue in rationale for cue in _REBATE_CUES):
        return PlaybookFinding(
            "fee_realism",
            "warn",
            "the rationale leans on earning / capturing the spread or a maker rebate — the backtest NEVER credits a "
            "rebate (the no-spread-credit floor), so an edge that depends on it will not survive the honest maker "
            "fill model. The maker benefit is the LOWER fee + avoiding paying the half-spread, never earning it.",
        )
    return PlaybookFinding("fee_realism", "pass", "fees are venue-derived and the edge does not assume a rebate")


def check_disconfirmer(spec: StrategySpec) -> PlaybookFinding:
    """A NAMED disconfirmer is required — the single observation that would prove the hypothesis wrong. It may
    live in the dedicated `spec.disconfirmer` field or be named in the rationale (a disconfirmer cue). Missing →
    FAIL: a thesis with no way to be wrong is not a testable hypothesis the Gate can adjudicate."""
    disc = (getattr(spec, "disconfirmer", None) or "").strip()
    if disc:
        return PlaybookFinding("disconfirmer", "pass", "a named disconfirmer is declared on the spec")
    rationale = (spec.rationale or "").lower()
    if any(cue in rationale for cue in _DISCONFIRMER_CUES):
        return PlaybookFinding("disconfirmer", "pass", "the rationale names a disconfirmer")
    return PlaybookFinding(
        "disconfirmer",
        "fail",
        "no named disconfirmer: set spec.disconfirmer (e.g. \"no edge if the signal IC ≤ a shuffled-null control\" "
        "/ \"kill if it loses to buy-and-hold net of fees on its own cell\"), or name one in the rationale.",
    )


def check_no_lookahead(spec: StrategySpec) -> PlaybookFinding:
    """Structural look-ahead guard. A FeatureRef with a non-positive INTEGER lookback could read the current/
    future bar → FAIL. A settle_at_resolution flag on a non-prediction universe does nothing (likely mis-set) →
    WARN. (The engine already enforces prior-bar-signal / next-bar-fill, so most look-ahead is impossible to
    express; this catches the spec-level red flags.)"""
    bad: list[str] = []
    for cond in [*spec.entry, *spec.exit.signal_exits]:
        lb = cond.feature.lookback
        if isinstance(lb, int) and lb <= 0:
            bad.append(f"{cond.feature.name}(lookback={lb})")
    if spec.meta_label is not None:
        for ref in spec.meta_label.features:
            if isinstance(ref.lookback, int) and ref.lookback <= 0:
                bad.append(f"{ref.name}(lookback={ref.lookback})")
    if bad:
        return PlaybookFinding(
            "no_lookahead",
            "fail",
            f"non-positive feature lookback(s) {bad}: a 0/negative lookback can read the current or future bar. "
            "Every feature lookback must be strictly positive (or a fitted ParamRef).",
        )
    if spec.exit.settle_at_resolution and "prediction" not in spec.universe.asset_classes:
        return PlaybookFinding(
            "no_lookahead",
            "warn",
            "settle_at_resolution=True but the universe has no 'prediction' asset class — the flag does nothing "
            "here (only prediction markets resolve). Drop it or target a prediction universe.",
        )
    return PlaybookFinding("no_lookahead", "pass", "no spec-level look-ahead red flags")


def run_playbook(spec: StrategySpec, *, catalog: VenueCatalog | None = None) -> PlaybookReport:
    """Run all five creation-playbook rules and return the aggregate report (verdict = the worst per-rule
    severity). Pure + deterministic — no DB, no network, no clock. This is the authoring railing, NOT the Gate;
    it disposes nothing and moves no money. Wire it alongside validate_spec in the authoring path: a FAIL means
    'fix the spec before it reaches the Gate'; a WARN is surfaced as advice."""
    cat = catalog or default_catalog()
    findings = [
        check_execution_coherence(spec),
        check_venue_feasibility(spec, cat),
        check_fee_realism(spec, cat),
        check_disconfirmer(spec),
        check_no_lookahead(spec),
    ]
    return PlaybookReport(verdict=_worst([f.severity for f in findings]), findings=findings)


def _venue_exists(catalog: VenueCatalog, venue_id: str) -> bool:
    try:
        catalog.venue(venue_id)
        return True
    except KeyError:
        return False


# --------------------------------------------------------------------------- learning-loop scaffold
#
# The place the operator + Claude tighten the rules over time from REAL paper/live outcomes. Today it is a thin,
# offline-safe stub: it records observed execution outcomes as audited events and reads them back into adjusted
# assumptions. The first concrete lever is the MAKER fill model — when live tells us a passive order's realized
# fill rate is materially worse (or better) than the conservative DEFAULT_MAKER_FILL, the backtest assumption
# should follow the evidence. With no recorded outcomes it returns the conservative defaults, so nothing changes
# until there is real data to learn from.

# Minimum recorded fill-rate samples before the learned model overrides the conservative default (one or two live
# fills are noise; we only move the assumption on a real, repeated signal).
_MIN_FILL_SAMPLES = 20
# Clamp the learned fill_rate to a sane band so a degenerate sample can never produce an absurd assumption.
_FILL_RATE_FLOOR = 0.05
_FILL_RATE_CAP = 1.0


def record_outcome(
    store: Store,
    *,
    kind: str,
    strategy_version_id: str | None = None,
    payload: dict | None = None,
) -> None:
    """Record one authoring/execution OUTCOME on the audited event ledger — the learning-loop's write side. `kind`
    names the observation (e.g. 'maker_fill_observed' with payload {'fill_rate': 0.31}); `payload` carries the
    structured datum. Offline-safe: any store error is swallowed (the loop is advisory, never load-bearing). This
    moves no money and is not the Gate."""
    try:
        store.append_event(
            actor="master",
            kind="playbook_outcome",
            ref_type="strategy_version",
            ref_id=strategy_version_id,
            payload={"kind": kind, **(payload or {})},
        )
    except Exception:  # noqa: BLE001 — the learning loop must never break an authoring/exec path
        pass


def learned_maker_fill(store: Store | None = None) -> MakerFillModel:
    """The CURRENT recommended maker fill model — the learning-loop's read side. With no store, or fewer than
    `_MIN_FILL_SAMPLES` recorded 'maker_fill_observed' outcomes, it returns the conservative DEFAULT_MAKER_FILL
    (the floor — the loop tightens, never loosens, from evidence). With enough samples it sets `fill_rate` to the
    observed mean (clamped), keeping the adverse-selection + queue assumptions at their conservative defaults
    until there is a principled reason to move them too. Read-only + offline-safe (any error → the default)."""
    if store is None:
        return DEFAULT_MAKER_FILL
    rates = _observed_fill_rates(store)
    if len(rates) < _MIN_FILL_SAMPLES:
        return DEFAULT_MAKER_FILL
    mean_rate = sum(rates) / len(rates)
    fill_rate = max(_FILL_RATE_FLOOR, min(_FILL_RATE_CAP, mean_rate))
    return MakerFillModel(
        fill_rate=fill_rate,
        adverse_selection_frac=DEFAULT_MAKER_FILL.adverse_selection_frac,
        queue_position_frac=DEFAULT_MAKER_FILL.queue_position_frac,
    )


def _observed_fill_rates(store: Store) -> list[float]:
    """Every recorded maker_fill_observed fill_rate, oldest-first. Best-effort: a missing table / malformed row
    degrades to []. JSON payloads are read whether the store hands them back as a dict or a raw string."""
    import json

    try:
        rows = store.rows(
            "SELECT payload FROM events WHERE kind = 'playbook_outcome' ORDER BY id ASC",
        )
    except Exception:  # noqa: BLE001 — no usable ledger → no learned override
        return []
    out: list[float] = []
    for r in rows:
        payload = r.get("payload") if isinstance(r, dict) else None
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (ValueError, TypeError):
                continue
        if not isinstance(payload, dict) or payload.get("kind") != "maker_fill_observed":
            continue
        rate = payload.get("fill_rate")
        try:
            out.append(float(rate))
        except (TypeError, ValueError):
            continue
    return out
