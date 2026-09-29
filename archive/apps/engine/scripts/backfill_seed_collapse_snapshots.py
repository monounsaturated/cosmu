#!/usr/bin/env python3
# intent: BACKFILL — delete the FUNDER's historical seed-collapse rows from portfolio_snapshots (scope='track').
# ROOT (fixed at the writer, master/portfolio.mark_to_market): the funder re-marked an already-HELD track with a
# marks-dict carrying only the freshly-funded cells, so the held legs fell back to cost basis → unrealized 0 →
# equity == starting_capital (the SEED) to the cent. Those rows carry NO information (a stale re-mark, not a fresh
# price) and drew the sawtooth/flat-gap on every scope='track' consumer. This one-shot removes them so the stored
# trajectory is the real marks only. inputs: the configured store (DATABASE_URL); outputs: DELETEd collapse rows.
# invariants: uses the SAME canonical filter the consumers use (master/track_equity.real_track_rows), so it deletes
# EXACTLY what they drop; a LEADING run of seed rows (day-0 truth, before any real mark) is PRESERVED; SAFETY-ASSERTs
# every row it deletes is seed-to-the-cent AND follows a real mark before touching anything; idempotent (re-running
# re-derives the remaining collapse rows); dry-run by DEFAULT (pass --apply to write).
#
# SEQUENCE: run this AFTER the writer fix (master/portfolio.mark_to_market) is deployed, otherwise the still-running
# old funder keeps appending fresh collapse rows and they re-accumulate.
#
# PROD: connect via DATABASE_URL from <repo>/.env.local (strip a trailing ` #comment` + `?pgbouncer=true`,
# use port 5432).

from __future__ import annotations

import argparse
from collections import defaultdict

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.track_equity import is_seed_equity, real_track_rows, track_starting_capital

_CHUNK = 200  # ids per DELETE statement


def _collapse_ids(store: Store) -> tuple[list[str], list[tuple], list[tuple]]:
    """Return (ids_to_delete, per_ref_summary, safety_violations). A violation = a row we'd delete that is NOT
    seed-to-the-cent (must be empty, else we ABORT rather than delete a real mark)."""
    rows = store.rows(
        "SELECT id, ref_id, ts, equity FROM portfolio_snapshots WHERE scope = 'track' ORDER BY ref_id, ts ASC"
    )
    by_ref: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_ref[r["ref_id"]].append(r)
    ids: list[str] = []
    per_ref: list[tuple] = []
    violations: list[tuple] = []
    for ref, series in by_ref.items():
        seed = track_starting_capital(store, ref)
        kept = {id(r) for r in real_track_rows(series, seed)}
        drop = [r for r in series if id(r) not in kept]
        for r in drop:
            if seed is None or not is_seed_equity(float(r["equity"]), seed):
                violations.append((ref, r["id"], float(r["equity"]), seed))
        if drop:
            per_ref.append((ref, len(series), len(drop)))
            ids.extend(r["id"] for r in drop)
    return ids, per_ref, violations


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Delete funder seed-collapse rows from portfolio_snapshots (scope='track').")
    p.add_argument("--apply", action="store_true", help="actually delete (default: dry-run).")
    args = p.parse_args(argv)

    store = Store(Settings())
    ids, per_ref, violations = _collapse_ids(store)

    print(f"refs with collapse rows: {len(per_ref)} | rows to delete: {len(ids)}")
    for ref, n, d in sorted(per_ref, key=lambda x: -x[2]):
        print(f"  {d:>5} / {n:>5}  {ref}")
    if violations:
        print(f"\nSAFETY ABORT: {len(violations)} non-seed rows would be deleted (showing 10):")
        for v in violations[:10]:
            print("   ", v)
        return 1
    print("\nSAFETY OK: every row to delete is seed-to-the-cent AND follows a real mark.")

    if not ids:
        print("nothing to delete.")
        return 0
    if not args.apply:
        print("\nDRY-RUN (no changes). Re-run with --apply to delete.")
        return 0

    deleted = 0
    for i in range(0, len(ids), _CHUNK):
        batch = ids[i : i + _CHUNK]
        placeholders = ", ".join("?" for _ in batch)
        store.rows(f"DELETE FROM portfolio_snapshots WHERE id IN ({placeholders})", tuple(batch))
        deleted += len(batch)
    remaining, _, _ = _collapse_ids(store)
    print(f"\nDELETED {deleted} rows. Remaining collapse rows: {len(remaining)} (expected 0 immediately after).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
