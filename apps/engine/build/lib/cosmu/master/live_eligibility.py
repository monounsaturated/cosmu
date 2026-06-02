# intent: the deterministic LIVE-ELIGIBILITY regime gate — a strategy may go live ONLY in a market regime it
# proved itself in. inputs: the store (for a version's proven-regime passport, written by the evolution loop on
# sleeve_opened) + a reference close series for the CURRENT regime; outputs: a yes/no eligibility with a reason.
# invariants: this gate only BLOCKS (it never promotes), it is fully deterministic + out of any LLM path, and an
# unknown/empty proven set fails safe (blocked). It composes ml/regime (current_regime + regime_eligible) — the
# scorer/gate decide survival; THIS decides only whether a survivor may trade live right now.

from __future__ import annotations

import json
from dataclasses import dataclass

from cosmu.knowledge.store import Store
from cosmu.ml.regime import Regime, current_regime, regime_eligible


@dataclass(frozen=True)
class LiveRegimeVerdict:
    version_id: str
    eligible: bool
    current_regime: Regime
    proven_regimes: list[str]
    reason: str


def proven_regimes_for(store: Store, version_id: str) -> set[str]:
    """Read a strategy version's proven-regime passport from its most recent sleeve_opened event (written by
    the evolution loop when the deterministic gate opened the sleeve). Empty if the version never opened a
    sleeve — which the gate then treats as 'never proven anywhere' (blocked)."""
    row = store.row(
        "SELECT payload FROM events WHERE kind = 'sleeve_opened' AND ref_id = ? ORDER BY id DESC LIMIT 1",
        (version_id,),
    )
    if not row:
        return set()
    payload = row["payload"]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return set()
    return set(payload.get("proven_regimes") or [])


def live_regime_verdict(store: Store, version_id: str, reference_bars) -> LiveRegimeVerdict:
    """Decide whether `version_id` may trade live RIGHT NOW: True only if the current regime (from the
    reference series) is one the strategy proved positive PnL in. Never promotes — only blocks; an empty
    proven set is never eligible (fail-safe)."""
    proven = proven_regimes_for(store, version_id)
    now = current_regime(reference_bars)
    eligible = regime_eligible(now, proven)
    if not proven:
        reason = "no proven regime on record"
    elif eligible:
        reason = f"current regime '{now.label}' is in the proven set"
    else:
        reason = f"current regime '{now.label}' not in proven set {sorted(proven)}"
    return LiveRegimeVerdict(
        version_id=version_id,
        eligible=eligible,
        current_regime=now,
        proven_regimes=sorted(proven),
        reason=reason,
    )
