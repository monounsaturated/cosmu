# intent: the lean DISCONFIRMER — the skeptic's hook BEFORE a call becomes a proposal. Two checks: (1)
# ACTIONABILITY — the call is a real, confident directional bet, not a neutral/flat observation or sarcasm; and
# (2) ECHO — the move isn't already over. A call is an echo if it's reacting to a known event (lead_lag == 'echo')
# or merely repeating an earlier identical call (not primary), OR if the asset has ALREADY moved strongly in the
# call's direction since the call (entering now chases a move that's played out). PURE + deterministic. A proposal
# is emitted ONLY when the call is actionable AND not an echo — so we never chase a stale or non-committal call.

from __future__ import annotations

from dataclasses import dataclass

from cosmu.conviction.authority_source import AssetCall

# How far the asset can have already moved in the call's direction (since the call) before we treat the move as
# "already over" — chasing. A fractional return; 5% is a meaningful crypto-scale move. Policy constant.
_ECHO_MOVE_THRESHOLD = 0.05

# Lean, deterministic sarcasm / non-committal markers. The LLM extractor already drops jokes/questions upstream;
# this is a cheap second net for a call whose verbatim quote still reads as sarcasm or an explicit non-call.
_SARCASM_MARKERS = (
    "/s",            # the canonical sarcasm tag
    " jk",
    "just kidding",
    "kidding",
    "sarcasm",
    "lmao",
    "not financial advice",  # an explicit disclaimer of a call — treat as non-actionable
    "this is not a call",
    "no idea",
    "who knows",
)


@dataclass(frozen=True)
class DisconfirmResult:
    """The verdict. `actionable` = a confident, non-sarcastic directional call. `echo` = the move is already over
    (reacting / not-primary / already-ran). `reasons` names every failing check (honest — the UI shows WHY a call
    did not become a proposal). A call PASSES only when actionable AND not echo."""

    actionable: bool
    echo: bool
    reasons: tuple[str, ...]

    @property
    def passes(self) -> bool:
        return self.actionable and not self.echo


def _looks_sarcastic(text: str) -> bool:
    low = (text or "").lower()
    return any(marker in low for marker in _SARCASM_MARKERS)


def _is_actionable(call: AssetCall, *, min_conviction: float) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if call.direction not in ("up", "down"):
        reasons.append("not_directional")          # flat / neutral — nothing to bet on
    if call.conviction < min_conviction:
        reasons.append(f"low_conviction({call.conviction:.2f}<{min_conviction:.2f})")
    if _looks_sarcastic(call.quote):
        reasons.append("sarcasm_or_disclaimer")
    return (not reasons, reasons)


def _is_echo(call: AssetCall, *, recent_return: float | None) -> tuple[bool, list[str]]:
    """The move is already over if the call reacts to a known event, merely repeats an earlier call, or the asset
    has already run in the call's direction. `recent_return` is the asset's signed move since the call (None =
    unknown → that arm is skipped, the primacy/lead-lag arms still apply)."""
    reasons: list[str] = []
    if call.lead_lag == "echo":
        reasons.append("reacting_to_event")        # followed an event — echo, not foresight
    if not call.is_primary:
        reasons.append("not_primary")              # echo of an earlier identical call
    if recent_return is not None:
        signed = recent_return if call.direction == "up" else -recent_return
        if signed >= _ECHO_MOVE_THRESHOLD:
            reasons.append(f"move_already_played_out({signed:.3f}>={_ECHO_MOVE_THRESHOLD})")
    return (bool(reasons), reasons)


def disconfirm(
    call: AssetCall,
    *,
    recent_return: float | None = None,
    min_conviction: float = 0.4,
) -> DisconfirmResult:
    """Run both disconfirmer checks on a call. `recent_return`: the asset's signed return since the call (the
    'has it already moved?' signal) — pass None when unknown (the echo check then relies on primacy/lead-lag only)."""
    actionable, a_reasons = _is_actionable(call, min_conviction=min_conviction)
    echo, e_reasons = _is_echo(call, recent_return=recent_return)
    return DisconfirmResult(actionable=actionable, echo=echo, reasons=tuple(a_reasons + e_reasons))
