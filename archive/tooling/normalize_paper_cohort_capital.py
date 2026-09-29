#!/usr/bin/env python3
# intent: one-shot, idempotent normalization of the Paper cohort to the canonical per-track size
# (settings.sim_track_capital). inputs: the live `tracks` table; outputs: rescaled tracks/positions/
# executions/portfolio_snapshots + a `track_rebased` audit event per track; invariants: returns are
# PRESERVED (uniform 1/10-style rescale of a flat cohort fabricates no equity), the whole change is one
# atomic transaction, a JSON backup is written BEFORE any write, and a second run is a no-op.
#
# WHY THIS EXISTS
# ---------------
# Several OLDER tracks were seeded at $10,000 before settings.sim_track_capital ($1,000) became the canonical
# standalone track size. Every code path now stamps settings.sim_track_capital (spine/engine.py, lab/finder.py,
# evolution/loop.py, research/*_arm.py), so the inconsistency is pure pre-canonical drift — not a position-
# sizing experiment. The mixed cohort corrupts the honest read-outs: /overview sums starting_capital for the
# Paper hero (a $10k track counts 10x), and the leaderboard/detail $ columns show $10k vs $1k for economically
# identical FLAT paper tracks. This restates the legacy tracks at the canonical notional so the whole cohort is
# consistent.
#
# HONESTY (point-in-time)
# -----------------------
# Every legacy track is FLAT: realized_pnl == 0 on every position, and the latest marked snapshot == its
# starting_capital (mark == basis, no fresh tick). A uniform rescale by factor = canonical/old_start therefore
# PRESERVES the forward return exactly (0% -> 0%; (k*equity)/(k*start) - 1 == equity/start - 1). No equity is
# fabricated: a $0-P&L track is still a $0-P&L track at $1k. The marked snapshot trajectory keeps its shape.
# The append-only executions are synthetic `kickstart_backfill` seed fills (fee=0, slippage=0) whose only role
# is to flip the has_paper_fills gate; rescaling their qty keeps the detail-sheet blotter coherent with the
# rebased position, and the `track_rebased` event records the change (preserving the ledger's audit intent).
#
# USAGE
#   python scripts/normalize_paper_cohort_capital.py            # DRY RUN (default): print plan, write nothing
#   python scripts/normalize_paper_cohort_capital.py --apply    # execute in one transaction (writes a backup first)
# DATABASE_URL selects the backend (Supabase/Postgres in prod, SQLite locally), exactly like the engine.

from __future__ import annotations

import argparse
import json
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

# Allow running from the repo root: the engine package lives under apps/engine.
_ENGINE = Path(__file__).resolve().parents[1] / "apps" / "engine"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from cosmu.config.settings import get_settings  # noqa: E402
from cosmu.knowledge.store import Store, utcnow  # noqa: E402

_MONEY = Decimal("0.01")  # 2dp for capital / equity / positions_value
_QTY = Decimal("0.00000001")  # 8dp for share/contract quantities (matches the positions/executions columns)
_EPS = Decimal("0.000001")  # a track within this of canonical is already normalized -> skipped (idempotent)


def _d(value: object) -> Decimal:
    return Decimal(str(value))


def _q(value: Decimal, exp: Decimal) -> Decimal:
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def main() -> int:
    ap = argparse.ArgumentParser(description="Normalize the Paper cohort to settings.sim_track_capital.")
    ap.add_argument("--apply", action="store_true", help="execute the writes (default is a dry run)")
    args = ap.parse_args()

    settings = get_settings()
    store = Store(settings)
    canonical = _d(settings.sim_track_capital)
    host = settings.database_url.split("@")[-1].split("/")[0]
    print(f"DB host={host}  canonical sim_track_capital={canonical}")
    print(f"mode={'APPLY' if args.apply else 'DRY-RUN'}")
    print("=" * 100)

    # Targets: every track whose starting_capital differs from the canonical size (idempotent — a normalized
    # cohort yields zero targets and this is a no-op).
    targets = [
        r for r in store.rows("SELECT strategy_version_id AS vid, starting_capital, equity, return_pct FROM tracks")
        if abs(_d(r["starting_capital"]) - canonical) > _EPS
    ]
    if not targets:
        print("No non-canonical tracks. Cohort already consistent — nothing to do.")
        return 0

    # ---- Read the full affected set (for the backup AND the per-vid scaling) ----
    plan: list[dict] = []
    for t in targets:
        vid = t["vid"]
        old_start = _d(t["starting_capital"])
        factor = (canonical / old_start)  # exact ratio; e.g. 1000/10000 = 0.1
        name = (store.row("SELECT s.name FROM strategies s JOIN strategy_versions sv ON sv.strategy_id = s.id WHERE sv.id = ?", (vid,)) or {}).get("name")
        positions = store.rows("SELECT * FROM positions WHERE strategy_version_id = ?", (vid,))
        executions = store.rows("SELECT id, qty FROM executions WHERE strategy_version_id = ?", (vid,))
        snaps = store.rows("SELECT id, equity, positions_value FROM portfolio_snapshots WHERE scope = 'track' AND ref_id = ?", (vid,))
        # Honesty guard: this rescale is only equity-preserving for a FLAT track. Refuse to touch any track that
        # carries realized P&L — a non-flat track must be re-based by hand (scaling realized $ would distort it).
        realized = sum((_d(p["realized_pnl"]) for p in positions), Decimal("0"))
        plan.append({
            "vid": vid, "name": name, "old_start": old_start, "factor": factor,
            "old_equity": _d(t["equity"]), "return_pct": t["return_pct"],
            "positions": positions, "executions": executions, "snaps": snaps, "realized": realized,
        })

    non_flat = [p for p in plan if p["realized"] != 0]
    if non_flat:
        print("ABORT: non-flat track(s) carry realized P&L — refuse to rescale (would distort realized $):")
        for p in non_flat:
            print(f"  {p['name']} ({p['vid']}) realized={p['realized']}")
        return 2

    # ---- Report the plan ----
    for p in plan:
        new_equity = _q(p["old_equity"] * p["factor"], _MONEY)
        print(f"\n{p['name']}  [{p['vid']}]")
        print(f"  starting_capital: {p['old_start']} -> {canonical}   (factor {p['factor']})")
        print(f"  tracks.equity:    {p['old_equity']} -> {new_equity}   return_pct stays {p['return_pct']}")
        print(f"  positions: {len(p['positions'])} legs rescaled (qty, realized_pnl)")
        print(f"  executions: {len(p['executions'])} fills rescaled (qty)")
        print(f"  scope='track' snapshots: {len(p['snaps'])} rescaled (equity, positions_value)")

    if not args.apply:
        print("\n" + "=" * 100)
        print("DRY-RUN complete. Re-run with --apply to execute (a JSON backup is written before any write).")
        return 0

    # ---- Backup BEFORE any write (local rollback artifact) ----
    backup = {"canonical": str(canonical), "host": host, "ts": utcnow(), "tracks": []}
    for p in plan:
        backup["tracks"].append({
            "vid": p["vid"], "name": p["name"], "old_start": str(p["old_start"]), "old_equity": str(p["old_equity"]),
            "return_pct": str(p["return_pct"]), "factor": str(p["factor"]),
            "positions": [{k: str(v) for k, v in dict(r).items()} for r in p["positions"]],
            "executions": [{k: str(v) for k, v in dict(r).items()} for r in p["executions"]],
            "snaps": [{k: str(v) for k, v in dict(r).items()} for r in p["snaps"]],
        })
    # Backup lands in the gitignored `.cosmu/` dir (carries track ids + equity — never commit it).
    backup_dir = _ENGINE.parent.parent / ".cosmu"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"paper_cohort_capital_backup_{utcnow().replace(':', '-')}.json"
    backup_path.write_text(json.dumps(backup, indent=2))
    print(f"\nBackup written: {backup_path}")

    # ---- Apply: ONE atomic transaction ----
    now = utcnow()  # one rebase timestamp across the whole cohort (cleaner forensics than per-row utcnow())
    with store.batch() as w:
        for p in plan:
            vid, factor = p["vid"], p["factor"]
            new_equity = _q(p["old_equity"] * factor, _MONEY)
            w.execute(
                "UPDATE tracks SET starting_capital = ?, equity = ?, updated_at = ? WHERE strategy_version_id = ?",
                (str(canonical), str(new_equity), now, vid),
            )
            for pos in p["positions"]:
                w.execute(
                    "UPDATE positions SET qty = ?, realized_pnl = ?, updated_at = ? WHERE id = ?",
                    (str(_q(_d(pos["qty"]) * factor, _QTY)), str(_q(_d(pos["realized_pnl"]) * factor, _QTY)), now, pos["id"]),
                )
            for ex in p["executions"]:
                w.execute(
                    "UPDATE executions SET qty = ? WHERE id = ?",
                    (str(_q(_d(ex["qty"]) * factor, _QTY)), ex["id"]),
                )
            for sn in p["snaps"]:
                w.execute(
                    "UPDATE portfolio_snapshots SET equity = ?, positions_value = ? WHERE id = ?",
                    (str(_q(_d(sn["equity"]) * factor, _MONEY)), str(_q(_d(sn["positions_value"]) * factor, _MONEY)), sn["id"]),
                )
            w.append_event(
                actor="ops",
                kind="track_rebased",
                ref_type="strategy_version",
                ref_id=vid,
                payload={
                    "reason": "normalize pre-canonical seed to settings.sim_track_capital",
                    "old_starting_capital": str(p["old_start"]),
                    "new_starting_capital": str(canonical),
                    "factor": str(factor),
                    "positions_rescaled": len(p["positions"]),
                    "executions_rescaled": len(p["executions"]),
                    "track_snapshots_rescaled": len(p["snaps"]),
                    "flat_at_rebase": True,
                },
            )
    print("\nApplied in one transaction.")
    print("=" * 100)

    # ---- Verify ----
    hist = {}
    for r in store.rows("SELECT starting_capital FROM tracks"):
        hist[str(r["starting_capital"])] = hist.get(str(r["starting_capital"]), 0) + 1
    print("starting_capital histogram after:", hist)
    bad = [r for r in store.rows("SELECT strategy_version_id AS vid, starting_capital FROM tracks") if abs(_d(r["starting_capital"]) - canonical) > _EPS]
    if bad:
        print("WARNING: non-canonical tracks remain:", bad)
        return 1
    print("All tracks now at canonical. Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
