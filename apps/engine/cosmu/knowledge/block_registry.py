# intent: persistence + queries for the strategy BUILDING-BLOCK registry (lineage, dedup, observational
# block-level stats); inputs: a Store/Writer + StrategySpecs; outputs: strategy_blocks / version_blocks /
# version_combos rows, duplicate lookups, a block leaderboard; invariants: FAIL-OPEN everywhere (a prod DB
# whose 2026-06-11 migration hasn't run yet must no-op cleanly, never break a cohort), observational ONLY —
# nothing here funds, kills, or feeds the scorer/Gate/FDR.

from __future__ import annotations

import json
from typing import Any

from cosmu.knowledge.store import Store, Writer, utcnow
from cosmu.strategy.blocks import combo_hash, decompose
from cosmu.strategy.spec import StrategySpec

# Stage values that mean "the Gate funded it" (legacy forward_test tolerated until the prod migration runs).
_FUNDED = ("paper", "forward_test", "live")


def blocks_available(store: Store) -> bool:
    """True when the registry tables exist on this store. Probed OUTSIDE any write transaction (a failed
    statement would abort a Postgres tx), cached by callers per run — never per row."""
    try:
        store.row("SELECT block_hash FROM strategy_blocks LIMIT 1")
        store.row("SELECT combo_hash FROM version_combos LIMIT 1")
        return True
    except Exception:  # noqa: BLE001 — table absent / migration not applied: the registry is simply off
        return False


def record_version_blocks(b: Writer, version_id: str, spec: StrategySpec) -> None:
    """Within the cohort's write transaction: content-address the spec's blocks and link them to the version.
    ON CONFLICT DO NOTHING keeps re-seen blocks idempotent (same SQL on SQLite ≥3.24 and Postgres)."""
    now = utcnow()
    for blk in decompose(spec):
        b.execute(
            "INSERT INTO strategy_blocks (block_hash, kind, label, payload, first_seen) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT (block_hash) DO NOTHING",
            (blk.block_hash, blk.kind, blk.label, json.dumps(blk.payload, sort_keys=True), now),
        )
        b.execute(
            "INSERT INTO version_blocks (strategy_version_id, block_hash, kind) "
            "VALUES (?, ?, ?) ON CONFLICT (strategy_version_id, block_hash) DO NOTHING",
            (version_id, blk.block_hash, blk.kind),
        )
    b.execute(
        "INSERT INTO version_combos (strategy_version_id, combo_hash, created_at) "
        "VALUES (?, ?, ?) ON CONFLICT (strategy_version_id) DO NOTHING",
        (version_id, combo_hash(spec), now),
    )


def find_duplicate(store: Store, combo: str) -> dict[str, Any] | None:
    """The earliest version already registered with this combo_hash (any status — a hypothesis the Gate
    KILLED is still a tested hypothesis; re-screening it would re-spend the multiple-testing budget)."""
    return store.row(
        "SELECT vc.strategy_version_id AS version_id, sv.status, s.name "
        "FROM version_combos vc "
        "JOIN strategy_versions sv ON sv.id = vc.strategy_version_id "
        "JOIN strategies s ON s.id = sv.strategy_id "
        "WHERE vc.combo_hash = ? ORDER BY vc.created_at ASC LIMIT 1",
        (combo,),
    )


def block_leaderboard(store: Store, *, min_n: int = 2, limit: int = 80) -> list[dict[str, Any]]:
    """Observational block-level stats: how often each block appears and how often its host version was
    funded by the Gate. Survival rates here NEVER fund anything — the per-cohort FDR gate remains the only
    judge; this is the 'which ingredients keep showing up in survivors' read-out."""
    placeholders = ", ".join("?" for _ in _FUNDED)
    rows = store.rows(
        "SELECT vb.block_hash, sb.kind, sb.label, "
        "COUNT(DISTINCT vb.strategy_version_id) AS n_versions, "
        f"COUNT(DISTINCT CASE WHEN sv.status IN ({placeholders}) THEN vb.strategy_version_id END) AS n_funded "
        "FROM version_blocks vb "
        "JOIN strategy_blocks sb ON sb.block_hash = vb.block_hash "
        "JOIN strategy_versions sv ON sv.id = vb.strategy_version_id "
        "GROUP BY vb.block_hash, sb.kind, sb.label "
        "HAVING COUNT(DISTINCT vb.strategy_version_id) >= ? "
        "ORDER BY n_funded DESC, n_versions DESC LIMIT ?",
        (*_FUNDED, min_n, limit),
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        n = int(r["n_versions"])
        funded = int(r["n_funded"] or 0)
        out.append(
            {
                "block_hash": r["block_hash"],
                "kind": r["kind"],
                "label": r["label"],
                "n_versions": n,
                "n_funded": funded,
                "funded_rate": round(funded / n, 4) if n else 0.0,
            }
        )
    return out


def versions_sharing_blocks(store: Store, version_id: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """Versions that share at least one block with `version_id`, ranked by how many blocks they share —
    the 'similar strategies' panel on the strategy detail surface."""
    return store.rows(
        "SELECT other.strategy_version_id AS version_id, s.name, sv.status, "
        "COUNT(*) AS shared_blocks "
        "FROM version_blocks mine "
        "JOIN version_blocks other ON other.block_hash = mine.block_hash "
        "  AND other.strategy_version_id != mine.strategy_version_id "
        "JOIN strategy_versions sv ON sv.id = other.strategy_version_id "
        "JOIN strategies s ON s.id = sv.strategy_id "
        "WHERE mine.strategy_version_id = ? "
        "GROUP BY other.strategy_version_id, s.name, sv.status "
        "ORDER BY shared_blocks DESC, s.name ASC LIMIT ?",
        (version_id, limit),
    )


def partner_rank(store: Store, specs: list[StrategySpec]) -> dict[str, float]:
    """For evolve's recombination: rank sibling survivors by the observed funded-rate of their EXIT + SIZING
    blocks (the part a recombination borrows). Returns {spec.name: strength in [0,1]}. Fail-open: an
    unavailable registry (or any error) returns {} and the caller keeps its deterministic name order. The
    rank only re-ORDERS partners the caller already chose — the Gate still judges every output."""
    try:
        if not blocks_available(store):
            return {}
        stats = {r["block_hash"]: r for r in block_leaderboard(store, min_n=1, limit=10_000)}
        out: dict[str, float] = {}
        for spec in specs:
            rates = [
                float(stats[blk.block_hash]["funded_rate"])
                for blk in decompose(spec)
                if blk.kind in ("exit", "sizing") and blk.block_hash in stats
            ]
            out[spec.name] = round(sum(rates) / len(rates), 6) if rates else 0.0
        return out
    except Exception:  # noqa: BLE001 — observational helper: never let it break evolution
        return {}
