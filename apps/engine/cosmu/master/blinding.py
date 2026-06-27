# intent: the hidden-box BLINDING discipline (particle-physics) that makes the holdout blind by CONSTRUCTION, not
# convention. A version's RECIPE hash is COMMITTED before its untouched holdout/forward set is first read; the
# deterministic Gate then REFUSES to score that version if its recipe drifted past its latest commit AFTER the box
# was opened — until a FRESH commit re-blinds it (which invalidates the now-stale holdout, so a re-blind forces a
# re-exam). inputs: a Store + a strategy_version_id; outputs: blinding_commits rows + a scoreability verdict.
# invariants: deterministic + keyless (no LLM, no network, no clock beyond utcnow for the audit stamp); recipe_hash
# covers the SCIENTIFIC spec (entry/exit/universe/horizon/param_space/setup/direction/funding/meta_label/risk/...)
# plus the fitted numeric params, NOT routing labels (name/rationale/lane/kind) — so a relabel is never a recipe
# change but ANY entry/exit-rule or fitted-value edit is; fail-OPEN when there is nothing to protect (no version,
# no commit, box never opened) so the pre-blinding backlog is unaffected.

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from cosmu.knowledge.store import Store, utcnow
from cosmu.master.holdout import HoldoutLedger

# Administrative / routing labels stripped before hashing: they pick an evaluator path or carry prose, but they do
# NOT change the per-bar P&L the holdout would produce. Stripping them means a routing relabel — e.g. the
# explore→gate graduation that flips `lane` in place (cosmu/master/zero_capital.graduate_explore) — is NOT counted
# as a recipe change, while any edit to an entry/exit rule, the universe, the param space, or a fitted value IS.
_RECIPE_ADMIN_KEYS = frozenset({"name", "rationale", "lane", "kind"})


class BlindingViolation(RuntimeError):
    """Raised when the Gate is asked to score a version whose recipe changed after its holdout/forward box was
    opened, with no fresh blinding commit covering the new recipe. The score is REFUSED — the holdout verdict on
    the books was earned by a DIFFERENT recipe, so using it now would be theater."""


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(value) if isinstance(value, str) else {}
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _canonical_params(params: Mapping[str, Any]) -> dict[str, float]:
    """The numeric fitted knobs, canonicalised exactly like master/promotion.params_hash (sorted keys, floats
    rounded to 8 dp, bools/non-numerics dropped) so the params half of the recipe hash matches the live drift pin."""
    return {
        k: round(float(v), 8)
        for k, v in params.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }


def recipe_hash(spec: Mapping[str, Any], params: Mapping[str, Any]) -> str:
    """sha256 over the SCIENTIFIC recipe: the spec with administrative labels stripped, plus the canonical numeric
    params. This is the hash the blinding commit freezes — a superset of params_hash (which pins only the params):
    editing the exit rule, an entry condition, the universe, or a fitted value all move it; renaming or relabelling
    the lane does not. Deterministic for a fixed (spec, params)."""
    recipe_spec = {k: v for k, v in _loads(spec).items() if k not in _RECIPE_ADMIN_KEYS}
    payload = {"spec": recipe_spec, "params": _canonical_params(_loads(params))}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class BlindingLedger:
    """Append-only ledger of a version's blinding commits. The first holdout/forward read commits the recipe; an
    honest re-blind (the operator/agent acknowledging a post-unblinding edit) appends a new row for the new recipe
    and invalidates the spent holdout so the new recipe re-sits the exam. One row per (version_id, recipe_hash)."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def current_recipe_hash(self, version_id: str) -> str | None:
        """The recipe_hash of the version's CURRENT persisted spec+params. None when the version row is gone."""
        row = self.store.row("SELECT spec, params FROM strategy_versions WHERE id = ?", (version_id,))
        if row is None:
            return None
        return recipe_hash(row["spec"], row["params"])

    def commits(self, version_id: str) -> list[dict[str, Any]]:
        # Ordered by committed_at (microsecond ISO strings sort chronologically) — the id is a uuid, not a sequence.
        return self.store.rows(
            "SELECT recipe_hash, reason, committed_at FROM blinding_commits WHERE version_id = ? "
            "ORDER BY committed_at, recipe_hash",
            (version_id,),
        )

    def latest(self, version_id: str) -> dict[str, Any] | None:
        commits = self.commits(version_id)
        return commits[-1] if commits else None

    def committed_hashes(self, version_id: str) -> set[str]:
        return {r["recipe_hash"] for r in self.commits(version_id)}

    def commit(self, version_id: str, *, reason: str = "holdout_first_read") -> str | None:
        """Freeze the version's CURRENT recipe_hash. Idempotent per (version_id, recipe_hash) — re-committing the
        same recipe is a no-op. A commit onto a recipe NOT already committed for this version, when PRIOR commits
        exist, is an honest RE-BLIND: it re-arms the now-stale holdout (the spent verdict belonged to a different
        recipe), so the new recipe must re-sit the one-shot exam. Order-independent (set membership, not row order).
        Returns the commit id, or None when the version row is gone."""
        rhash = self.current_recipe_hash(version_id)
        if rhash is None:
            return None
        prior_hashes = self.committed_hashes(version_id)
        is_reblind = bool(prior_hashes) and rhash not in prior_hashes
        cid = self.store.insert_or_get(
            "blinding_commits",
            {"version_id": version_id, "recipe_hash": rhash, "reason": reason, "committed_at": utcnow()},
            conflict_cols=["version_id", "recipe_hash"],
        )
        if not prior_hashes:
            self.store.append_event(
                actor="master", kind="blinding_committed", ref_type="strategy_version", ref_id=version_id,
                payload={"recipe_hash": rhash, "reason": reason},
            )
        elif is_reblind:
            # Re-blind onto a changed recipe → the holdout earned under the old recipe is stale; re-arm it so the
            # new recipe genuinely re-sits the one-shot exam (re-blind ⇒ re-exam; never a silent rubber-stamp).
            # invalidate() is a no-op when the holdout was never consumed, so this is safe regardless of read order.
            HoldoutLedger(self.store).invalidate(version_id)
            self.store.append_event(
                actor="master", kind="blinding_recommitted", ref_type="strategy_version", ref_id=version_id,
                payload={"recipe_hash": rhash, "reason": reason},
            )
        return cid


def box_opened(store: Store, version_id: str) -> bool:
    """True once the version's untouched holdout/forward set has actually been READ: the holdout was consumed, OR
    a forward `track_opened` event exists (the paper clock started observing it). Either read is the moment the
    hidden box is opened — after which a recipe change is a peek-then-tune."""
    if HoldoutLedger(store).consumed(version_id):
        return True
    row = store.row(
        "SELECT 1 FROM events WHERE kind = 'track_opened' AND (ref_id = ? OR ref_id LIKE ?) LIMIT 1",
        (version_id, f"{version_id}:%"),
    )
    return row is not None


def assert_scoreable(store: Store, version_id: str) -> None:
    """The Gate PRECONDITION. Raise BlindingViolation if the version's CURRENT recipe drifted past every blinding
    commit AFTER its holdout/forward box was opened. Fail-OPEN when there is nothing to protect:
      - no such version row (nothing to score),
      - no blinding commit at all (never blinded — the pre-migration backlog),
      - the box was never opened (no holdout read, no forward track — no peeking has happened yet),
      - the current recipe matches a committed hash (unchanged since a commit).
    Once a commit exists AND the box is open AND the recipe no longer matches any committed hash, scoring is
    REFUSED until a FRESH commit re-blinds the new recipe (BlindingLedger.commit, which also re-arms the holdout)."""
    ledger = BlindingLedger(store)
    current = ledger.current_recipe_hash(version_id)
    if current is None:
        return
    committed = ledger.committed_hashes(version_id)
    if not committed:
        return
    if current in committed:
        return
    if not box_opened(store, version_id):
        return
    latest = ledger.latest(version_id) or {}
    raise BlindingViolation(
        f"version {version_id}: recipe_hash changed after its first holdout/forward read "
        f"(current {current[:12]}… not among {len(committed)} blinding commit(s); "
        f"latest committed {str(latest.get('recipe_hash', ''))[:12]}…). "
        "Re-blind with a fresh blinding commit (which re-arms the holdout) before the Gate can score it."
    )
