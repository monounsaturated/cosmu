#!/usr/bin/env python3
# intent: BACKFILL — reprice the kickstart_paper_fills-backfilled PAPER executions that were written with a hardcoded
# fee=0, the paper↔backtest fee-parity break for the documented IBKR-equity TAA arms (DAA/VAA/PAA/GTAA/TSMOM/Risk-
# Parity/Sector-Momentum/GEM/ADM/…). ROOT (fixed at the writer, orchestrator.loop.kickstart_paper_fills): the boot-time
# ledger backfill hardcoded "fee":"0" instead of the asset-aware per-venue taker fee the money path charges, so every
# backfilled IBKR-equity leg read fee=0.00 (fees-always-today is a locked invariant). This one-shot recomputes each
# affected row's fee via the SAME chokepoint the fix uses (orchestrator.loop._kickstart_leg_fee ->
# master.execution._pit_fee_for_order == build_cost_context's resolver), so the historical blotter/accounting matches.
# inputs: the configured store (DATABASE_URL); outputs: UPDATEd fee + one audited `paper_fee_repriced` event per row
# (the reversal source). invariants: touches ONLY is_paper=1 kickstart_backfill rows with fee==0 (idempotent — a
# repriced row is fee>0 and no longer matched); can only EQUAL-or-RAISE the fee (SAFETY-ABORTs if any new fee < old,
# which for an all-zero baseline means a negative — impossible, but asserted); paper display/accounting ONLY (never
# positions / realized P&L / the money path); reversible via --revert (restores each row from its audit event);
# dry-run by DEFAULT (pass --apply to write). SEQUENCE: run AFTER the writer fix is deployed.
#
# PROD: connects via DATABASE_URL from /Users/device/cosmu/.env.local (Store(Settings()) handles pgbouncer / #comment).

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.execution import _pit_fee_for_order
from cosmu.spine.venue import default_catalog

_REPRICE_EVENT = "paper_fee_repriced"
_MATCH = "%kickstart_backfill%"


def _targets(store: Store) -> list[dict]:
    """The kickstart-backfilled paper executions still at fee=0, joined to `positions` for the symbol (executions
    stores instrument_id, not symbol — the fee resolver keys on the symbol/instrument's asset class)."""
    return store.rows(
        "SELECT e.id, e.venue_id, e.instrument_id, e.qty, e.price, s.name AS strat, p.symbol AS symbol "
        "FROM executions e "
        "JOIN strategy_versions sv ON sv.id = e.strategy_version_id "
        "JOIN strategies s ON s.id = sv.strategy_id "
        "LEFT JOIN positions p ON p.strategy_version_id = e.strategy_version_id "
        "  AND p.instrument_id = e.instrument_id AND p.venue = e.venue_id "
        "WHERE CAST(e.is_paper AS INTEGER) = 1 AND CAST(e.fee AS REAL) = 0 AND e.fill_log LIKE ?",
        (_MATCH,),
    )


def _new_fee(store: Store, catalog, row: dict) -> Decimal:
    """The parity fee for one row via the SAME money-path chokepoint (_pit_fee_for_order) the writer fix uses —
    MIRRORS orchestrator.loop._kickstart_leg_fee EXACTLY (venue+instrument resolution → per-share/per-category or
    catalog/PIT bps), inlined here so this one-shot depends only on symbols present in the deployed tree. Never
    raises: unknown venue → 0, unknown symbol → the resolver's flat-bps fallback, any failure → 0."""
    venue_id = row["venue_id"]
    symbol = row["symbol"] or row["instrument_id"]
    try:
        venue = catalog.venue(venue_id)
    except KeyError:
        return Decimal("0")
    try:
        instrument = catalog.instrument(symbol, venue_id)
    except KeyError:
        instrument = None
    try:
        qty = abs(Decimal(str(row["qty"])))
        price = Decimal(str(row["price"]))
        return _pit_fee_for_order(store, venue, symbol, qty, price, instrument=instrument)
    except Exception:  # noqa: BLE001 — a fee-calc failure must never abort the backfill
        return Decimal("0")


def _revert(store: Store, *, apply: bool) -> int:
    """Restore every repriced row to its pre-backfill fee from the audit trail. Latest event per exec id wins."""
    events = store.rows(
        "SELECT ref_id, payload FROM events WHERE kind = ? ORDER BY id ASC", (_REPRICE_EVENT,)
    )
    old_by_id: dict[str, str] = {}
    for ev in events:
        payload = ev["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        old_by_id[str(ev["ref_id"])] = str(payload.get("old_fee", "0"))
    print(f"repriced rows on record: {len(old_by_id)}")
    if not apply:
        print("DRY-RUN (no changes). Re-run with --revert --apply to restore.")
        return 0
    for exec_id, old_fee in old_by_id.items():
        store.rows("UPDATE executions SET fee = ? WHERE id = ?", (old_fee, exec_id))
    print(f"REVERTED {len(old_by_id)} rows to their pre-backfill fee.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Reprice hardcoded-0 kickstart_backfill paper executions to the parity fee.")
    p.add_argument("--apply", action="store_true", help="actually write (default: dry-run).")
    p.add_argument("--revert", action="store_true", help="restore repriced rows from the audit events instead.")
    args = p.parse_args(argv)

    store = Store(Settings())
    catalog = default_catalog()

    if args.revert:
        return _revert(store, apply=args.apply)

    rows = _targets(store)
    per_strat: dict[str, tuple[int, Decimal]] = defaultdict(lambda: (0, Decimal("0")))
    plan: list[tuple[str, Decimal]] = []  # (exec_id, new_fee)
    violations: list[tuple] = []
    for r in rows:
        fee = _new_fee(store, catalog, r)
        if fee < Decimal("0"):  # can only equal-or-raise a 0 baseline
            violations.append((r["id"], r["strat"], str(fee)))
        n, tot = per_strat[r["strat"]]
        per_strat[r["strat"]] = (n + 1, tot + fee)
        plan.append((r["id"], fee))

    print(f"kickstart_backfill paper rows still at fee=0: {len(rows)}")
    for strat, (n, tot) in sorted(per_strat.items(), key=lambda kv: kv[1][1]):
        flag = "" if tot > 0 else "   <-- STILL 0 (unresolved venue?)"
        print(f"  {float(tot):>10.4f}  n={n:<3} {strat}{flag}")
    print(f"  {'-' * 10}\n  {float(sum(t for _, t in per_strat.values())):>10.4f}  TOTAL (was 0.0000)")

    if violations:
        print(f"\nSAFETY ABORT: {len(violations)} row(s) computed a fee < 0 (would lower, not raise):")
        for v in violations[:10]:
            print("   ", v)
        return 1
    print("\nSAFETY OK: every new fee >= the 0 baseline (equal-or-raise invariant holds).")

    if not rows:
        print("nothing to reprice.")
        return 0
    if not args.apply:
        print("\nDRY-RUN (no changes). Re-run with --apply to write.")
        return 0

    for exec_id, fee in plan:
        store.rows("UPDATE executions SET fee = ? WHERE id = ?", (str(fee), exec_id))
        store.append_event(
            actor="ops",
            kind=_REPRICE_EVENT,
            ref_type="execution",
            ref_id=exec_id,
            payload={"old_fee": "0", "new_fee": str(fee), "reason": "kickstart_backfill_fee_parity"},
        )
    remaining = _targets(store)
    print(f"\nREPRICED {len(plan)} rows. Remaining fee=0 kickstart rows: {len(remaining)} (expected 0 immediately after).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
