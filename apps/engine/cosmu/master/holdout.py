# intent: enforce one-shot holdout evaluation so an autonomous loop cannot silently overfit the untouched set; inputs: a version id + a compute callback; outputs: the (recorded) holdout verdict; invariants: each version is evaluated against the holdout exactly once — re-requests return the stored verdict and never recompute.

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from cosmu.knowledge.store import Store, utcnow


class HoldoutLedger:
    """A held-out set is only valid the first time it is seen. This ledger makes that a hard
    invariant: the first evaluation is logged and locked; every later request for the same version
    returns the recorded verdict without touching the holdout again."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def consumed(self, version_id: str) -> bool:
        return self.store.row("SELECT 1 FROM holdout_ledger WHERE version_id = ?", (version_id,)) is not None

    def verdict(self, version_id: str) -> dict[str, Any] | None:
        row = self.store.row("SELECT verdict FROM holdout_ledger WHERE version_id = ?", (version_id,))
        return json.loads(row["verdict"]) if row else None

    def evaluate_once(self, version_id: str, compute: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        existing = self.verdict(version_id)
        if existing is not None:
            return existing  # refuse to recompute — the holdout is already spent for this version
        verdict = compute()
        self.store.rows(
            "INSERT INTO holdout_ledger(version_id, verdict, evaluated_at) VALUES (?, ?, ?)",
            (version_id, json.dumps(verdict, sort_keys=True), utcnow()),
        )
        self.store.append_event(actor="master", kind="holdout_consumed", ref_type="strategy_version", ref_id=version_id, payload={"verdict": verdict})
        return verdict

    def invalidate(self, version_id: str) -> bool:
        """Re-arm the one-shot exam: drop this version's spent verdict so the holdout may be read ONCE more. The
        ONLY caller is a blinding RE-BLIND (cosmu/master/blinding) — the recipe changed after the box was opened,
        so the verdict on the books belongs to a different recipe and must be re-earned. Never called from the
        ordinary loop (that would defeat the one-shot invariant). Returns True iff a stored verdict was cleared."""
        if not self.consumed(version_id):
            return False
        self.store.rows("DELETE FROM holdout_ledger WHERE version_id = ?", (version_id,))
        self.store.append_event(actor="master", kind="holdout_rearmed", ref_type="strategy_version", ref_id=version_id, payload={})
        return True
