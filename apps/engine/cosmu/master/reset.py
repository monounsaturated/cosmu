# intent: CLEAN SIM-STATE CUTOVER — purge the synthetic-era discovery + sim state so the honest real-data
# loop starts from a clean $100k forward test, while PRESERVING config (venues/instruments/live toggle/caps),
# real ingested alt-data, and source registrations. inputs: a Store; outputs: deleted rows (audited). invariants:
# never touches live_toggle/live_caps (the money interlocks stay exactly as set), never deletes real alt_data or
# venue/instrument config, atomic (one transaction), and a no-op dry-run unless --confirm is passed.

from __future__ import annotations

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store, utcnow

# Discovery + sim state written by the (formerly synthetic) loop. Ordered children→parents so FK constraints
# hold on Postgres. NOT listed = preserved: venues, instruments, live_toggle, live_caps, sources, costs,
# llm_calls, alt_data (real ingested data), asset_class_gates.
_PURGE_TABLES: tuple[str, ...] = (
    "backtests",
    "tracks",
    "positions",
    "portfolio_snapshots",
    "executions",
    "holdout_ledger",
    "gate_verdicts",
    "trials",
    "recommendations",
    "policies",
    "research_notes",
    "skills",
    "runs",
    "strategy_versions",
    "strategies",
    "events",
)


def sim_state_counts(store: Store) -> dict[str, int]:
    """Row counts for every table the reset would purge — the dry-run view."""
    counts: dict[str, int] = {}
    for table in _PURGE_TABLES:
        try:
            row = store.row(f"SELECT COUNT(*) AS n FROM {table}")  # noqa: S608 — table names are a fixed constant
            counts[table] = int(row["n"]) if row else 0
        except Exception:  # noqa: BLE001 — a table absent on this backend just counts 0
            counts[table] = 0
    return counts


def reset_sim_state(store: Store) -> dict[str, int]:
    """Purge synthetic-era discovery + sim state in one transaction, preserving config + real alt-data + the
    live interlocks. Returns the per-table row counts that were deleted. Live toggle/caps are never touched."""
    counts = sim_state_counts(store)
    with store.batch() as b:
        for table in _PURGE_TABLES:
            b.execute(f"DELETE FROM {table}")  # noqa: S608 — fixed constant table list
        b.append_event(
            actor="human",
            kind="sim_state_reset",
            ref_type="portfolio",
            ref_id="global",
            payload={"purged": counts, "at": utcnow()},
        )
    return counts


def _main(argv: list[str] | None = None) -> int:
    """CLI: dry-run by default (prints what WOULD be purged); `--confirm` executes against the store the env
    points at (Settings()/DATABASE_URL). Run at the real-data cutover so the displayed overview/funnel is honest."""
    import argparse

    parser = argparse.ArgumentParser(description="Reset the sim state + discovery state for a clean real-data cutover (config + real data preserved).")
    parser.add_argument("--confirm", action="store_true", help="actually delete (without this it is a dry-run)")
    args = parser.parse_args(argv)

    store = Store(Settings())
    if not args.confirm:
        counts = sim_state_counts(store)
        total = sum(counts.values())
        print(f"DRY RUN — would purge {total} rows across {len(counts)} tables (config + live toggle/caps + real alt_data preserved):")
        for table, n in counts.items():
            if n:
                print(f"  {table}: {n}")
        print("Re-run with --confirm to execute.")
        return 0
    counts = reset_sim_state(store)
    print(f"RESET DONE — purged {sum(counts.values())} rows; sim state starts clean at the configured bankroll. Live toggle/caps untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
