#!/usr/bin/env python3
# intent: the survivor-realness AUDIT — recompute a recent gate survivor's Deflated Sharpe at the TRUE
# decorrelated effective-N from the honest trial-count ledger, and report whether it STILL clears the locked DSR
# gate (0.95). This is the playbook's bridge #2 instrument: it makes N honest without touching a single locked
# Gate constant — only the trial count fed into expected_max_sharpe changes. Read-only; never moves money.
#
# Usage:
#   PYTHONPATH=apps/engine python3 -m scripts.research.recompute_survivor_dsr            # configured store
#   PYTHONPATH=apps/engine python3 apps/engine/scripts/research/recompute_survivor_dsr.py --db sqlite:///path.sqlite3

from __future__ import annotations

import argparse
from decimal import Decimal

from cosmu.config.settings import Settings
from cosmu.knowledge.store import Store
from cosmu.master.scorer import BacktestMetrics
from cosmu.master.trial_ledger import (
    SurvivorRecompute,
    effective_n,
    ledger_count,
    recompute_dsr_at_honest_n,
)


def _latest_survivor(store: Store) -> tuple[BacktestMetrics, str | None, str] | None:
    """The most recent gate survivor as (metrics, family, label).

    A survivor is a backtest row that cleared the gate AND its one-shot holdout (passed_gates=1 AND
    holdout_passed=1). We rebuild the BacktestMetrics the Deflated Sharpe is computed from — the per-observation
    Sharpe + higher moments + observation count + the per-combo trial count it was originally deflated by — from
    the persisted columns. `family` is the strategy name (the key the honest ledger groups looks under)."""
    row = store.row(
        """
        SELECT b.sharpe_per_obs, b.skew, b.kurtosis, b.n_obs, b.num_trades, b.oos_return,
               b.trials_counted, b.deflated_sharpe, b.created_at, s.name AS family, b.strategy_version_id AS vid
        FROM backtests b
        JOIN strategy_versions v ON v.id = b.strategy_version_id
        JOIN strategies s ON s.id = v.strategy_id
        WHERE b.passed_gates = 1 AND b.holdout_passed = 1 AND b.sharpe_per_obs IS NOT NULL AND b.n_obs IS NOT NULL
        ORDER BY b.created_at DESC
        LIMIT 1
        """
    )
    if row is None:
        return None
    metrics = BacktestMetrics(
        oos_return=Decimal(str(row["oos_return"])),
        sharpe=Decimal("0"),
        sortino=Decimal("0"),
        max_drawdown=Decimal("0"),
        win_rate=Decimal("0"),
        num_trades=int(row["num_trades"] or 0),
        sharpe_per_obs=Decimal(str(row["sharpe_per_obs"])),
        skew=Decimal(str(row["skew"] if row["skew"] is not None else "0")),
        kurtosis=Decimal(str(row["kurtosis"] if row["kurtosis"] is not None else "3")),
        n_obs=int(row["n_obs"]),
        trials_counted=int(row["trials_counted"] or 1),
    )
    return metrics, row["family"], str(row["vid"])


def _format(rec: SurvivorRecompute, *, scope: str) -> str:
    flip = "" if rec.clears_naive == rec.clears_honest else "  ⚠️ VERDICT FLIPPED"
    return (
        f"  {scope}:\n"
        f"    N (original, per-combo grid)   : {rec.raw_n}\n"
        f"    N (honest decorrelated effective): {rec.effective_n:.2f}  →  used {rec.honest_n}\n"
        f"    DSR @ original N : {rec.dsr_naive:.4f}  ({'clears' if rec.clears_naive else 'FAILS'} {rec.threshold})\n"
        f"    DSR @ honest   N : {rec.dsr_honest:.4f}  ({'clears' if rec.clears_honest else 'FAILS'} {rec.threshold}){flip}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recompute a recent survivor's DSR at the honest effective-N.")
    parser.add_argument("--db", default=None, help="database_url override (e.g. sqlite:///path.sqlite3)")
    args = parser.parse_args(argv)

    store = Store(Settings(database_url=args.db) if args.db else Settings())
    n_looks = ledger_count(store)
    print("SURVIVOR DSR RECOMPUTE — honest trial-count ledger")
    print(f"  ledger looks recorded: {n_looks}   whole-machine effective-N: {effective_n(store):.2f}")

    survivor = _latest_survivor(store)
    if survivor is None:
        print("  (no gate+holdout survivor in this store — nothing to recompute; honest empty result)")
        return 0
    metrics, family, vid = survivor
    print(f"  survivor: family={family!r}  version={vid}  sharpe_per_obs={float(metrics.sharpe_per_obs):.4f}  n_obs={metrics.n_obs}")

    # PRIMARY verdict: deflate against the survivor's OWN family looks (the direct multiple-testing for THIS edge).
    fam_rec = recompute_dsr_at_honest_n(metrics, store, family=family)
    print(_format(fam_rec, scope=f"family {family!r}"))
    # UPPER BOUND: deflate against EVERY look the machine took (the family-wise look-elsewhere correction).
    all_rec = recompute_dsr_at_honest_n(metrics, store, family=None)
    print(_format(all_rec, scope="whole machine"))

    still = fam_rec.still_clears
    print(f"\n  VERDICT: at the honest family effective-N the survivor {'STILL CLEARS' if still else 'NO LONGER CLEARS'} the locked DSR {fam_rec.threshold} gate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
