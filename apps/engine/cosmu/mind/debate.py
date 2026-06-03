# intent: the debate — combine the analyst panel's stances into ONE standardized market read (consensus ·
# conviction · agreement) plus the bull/bear case split, the way TradingAgents has a researcher team argue a
# position. inputs: a list[Stance]; outputs: a MindSnapshot. invariants: deterministic (weighted vote with a
# stable tie-break), honest (when every market analyst abstains the consensus is neutral with zero conviction),
# and RAILGUARDED — the snapshot is a reasoning record only; it never funds or fires. The deterministic gate
# alone disposes of money. An LLM may later narrate the snapshot, but never in any scoring/gate/money path.

from __future__ import annotations

from dataclasses import dataclass, field

from cosmu.mind.analysts import Stance

# The hard rule, surfaced everywhere the Mind is shown: reasoning is not authority over money.
RAILGUARD = "The Mind reasons; it never funds or fires an order. The deterministic gate alone disposes."


@dataclass(frozen=True)
class MindSnapshot:
    """The panel's combined read. `consensus` is the weighted directional vote of the MARKET analysts;
    `conviction` is how strongly the agreeing analysts feel; `agreement` is how dominant the consensus is over
    the whole panel (low agreement = a contested read). `contested` is true when both a bull and a bear case
    exist. `narrative` is a deterministic plain-language summary (an LLM may replace it later, off the gate path)."""

    stances: list[Stance]
    consensus: str  # bullish | bearish | neutral
    conviction: float  # 0..1
    agreement: float  # 0..1
    contested: bool
    bull_case: list[str] = field(default_factory=list)
    bear_case: list[str] = field(default_factory=list)
    narrative: str = ""
    as_of: str | None = None


def debate(stances: list[Stance]) -> MindSnapshot:
    """Aggregate the panel into a standardized read. Market analysts vote (weighted by conviction × source
    weight); process analysts (ML, memory) inform the narrative but never the directional vote."""
    market = [s for s in stances if s.kind == "market" and s.lean != "abstain"]
    tally: dict[str, float] = {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0}
    for s in market:
        tally[s.lean] += s.weight * s.conviction
    total = sum(tally.values())

    if total <= 0.0:
        # Every market analyst abstained (or zero conviction) — say so honestly rather than invent a lean.
        return MindSnapshot(
            stances=stances,
            consensus="neutral",
            conviction=0.0,
            agreement=0.0,
            contested=False,
            narrative=_no_signal_narrative(stances),
            as_of=_latest_asof(stances),
        )

    # Deterministic argmax: highest weighted vote, ties broken by a fixed lean order.
    order = {"bullish": 0, "neutral": 1, "bearish": 2}
    consensus = max(tally, key=lambda k: (tally[k], -order[k]))
    agreement = round(tally[consensus] / total, 3)
    agreeing = [s for s in market if s.lean == consensus]
    conviction = round(sum(s.conviction for s in agreeing) / len(agreeing), 3) if agreeing else 0.0

    bull_case = [s.perspective for s in market if s.lean == "bullish"]
    bear_case = [s.perspective for s in market if s.lean == "bearish"]
    contested = bool(bull_case and bear_case)

    return MindSnapshot(
        stances=stances,
        consensus=consensus,
        conviction=conviction,
        agreement=agreement,
        contested=contested,
        bull_case=bull_case,
        bear_case=bear_case,
        narrative=_narrative(consensus, conviction, agreement, contested, bull_case, bear_case, stances),
        as_of=_latest_asof(stances),
    )


# --------------------------------------------------------------------------- narrative (deterministic)


def _narrative(
    consensus: str,
    conviction: float,
    agreement: float,
    contested: bool,
    bull: list[str],
    bear: list[str],
    stances: list[Stance],
) -> str:
    strength = "high" if conviction >= 0.66 else "moderate" if conviction >= 0.4 else "low"
    align = "broad agreement" if agreement >= 0.66 else "a split panel" if agreement < 0.5 else "a working majority"
    lead = f"The panel leans {consensus} on {align} ({strength} conviction)."
    cases: list[str] = []
    if bull:
        cases.append(f"Bull case: {', '.join(bull)}.")
    if bear:
        cases.append(f"Bear case: {', '.join(bear)}.")
    if contested:
        cases.append("The read is contested — size accordingly.")
    process = [s for s in stances if s.kind == "process"]
    tail = " ".join(f"{s.perspective}: {s.headline}." for s in process)
    return " ".join([lead, *cases, tail]).strip()


def _no_signal_narrative(stances: list[Stance]) -> str:
    process = [s for s in stances if s.kind == "process"]
    tail = " ".join(f"{s.perspective}: {s.headline}." for s in process)
    base = "No live market signals are ingested yet, so the panel abstains rather than fabricate a read."
    return f"{base} {tail}".strip()


def _latest_asof(stances: list[Stance]) -> str | None:
    asof: str | None = None
    for s in stances:
        if s.as_of and (asof is None or s.as_of > asof):
            asof = s.as_of
    return asof
