"""Gate the newly-authored capitulation specs through a POOLED GRID + honest Gate, per-spec verdict.

Reuses the canonical machinery (build_grid + real PIT alt join + run_strategy_backtest_detailed +
promote_cohort BH-FDR + real holdout, net of real Binance taker fees) — composes, never re-implements
the Gate. For each spec: pool the backtest across the crypto majors (a market-wide capitulation signal
fires on the same dates across the universe → real trade count), grid-fit the params, register EVERY
variant as a trial (honest deflation), and gate the grid as a cohort. Reports the best variant's verdict.
Prod alt-store read + isolated temp trial store (matrix_search's clean split — no prod trial pollution).
"""
from __future__ import annotations

import sys
import tempfile

import cosmu.research.matrix_search as ms
from cosmu.lab.finder import build_grid
from cosmu.strategy.static_check import validate_spec

NEW_SPECS = {
    "Fear & Greed extreme-fear contrarian long (spot)",
    "VIX spike cross-asset capitulation long (spot crypto)",
    "Cross-asset capitulation composite long (Fear&Greed + VIX)",
}
UNIVERSE = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "ADAUSDT", "AVAXUSDT", "XRPUSDT", "LINKUSDT"]
TF = "1d"
MAX_VARIANTS = 96


def _pooled_market() -> dict:
    market = {}
    for sym in UNIVERSE:
        bars = ms.load_bars(sym, TF)
        if len(bars) >= 120:
            market[sym] = bars
    return market


def main() -> None:
    print("=== validating new specs ===")
    specs = [s for s in ms.load_specs() if s.name in NEW_SPECS]
    ok = True
    for s in specs:
        issues = validate_spec(s)
        print(f"  [{s.name[:46]:46}] {'OK' if not issues else issues}")
        ok = ok and not issues
    if not ok:
        sys.exit(1)

    market = _pooled_market()
    fee_bps = ms.default_catalog().venue("binance").taker_fee_bps
    alt_store = ms._matrix_alt_store()
    print(f"\n=== POOLED GRID gate | universe={list(market)} | fee={fee_bps}bps taker ===")

    for spec in specs:
        alt = ms.build_alt_by_symbol(alt_store, spec, market) if alt_store is not None else None
        grid = build_grid(spec, max_variants=MAX_VARIANTS)
        tmp = tempfile.mkdtemp(prefix="cosmu-grid-")
        store = ms.Store(ms.Settings(database_url=f"sqlite:///{tmp}/m.sqlite3", openrouter_api_key=None))
        cands, mby = [], {}
        traded = 0
        for i, v in enumerate(grid):
            try:
                res = ms.run_strategy_backtest_detailed(spec, v.params, market, fee_bps=fee_bps, alt_by_symbol=alt)
            except Exception:  # noqa: BLE001
                continue
            m = res.metrics
            if int(m.num_trades) <= 0:
                continue
            traded += 1
            cid = f"{spec.name}#{i}"
            ms.record_trial(store, float(m.sharpe_per_obs), source="gridnew", label=cid)
            cands.append(ms.Candidate(id=cid, metrics=m, net_profit=float(m.oos_return), source="gridnew", label=cid))
            mby[cid] = m
        if not cands:
            print(f"\n-- {spec.name[:50]}: 0/{len(grid)} variants traded (signal never fires on pooled universe)")
            continue
        proms = ms.promote_cohort(store, cands, store.settings.gates, register=False,
                                  trials=ms.trial_stats(store), persist=None)
        pby = {p.candidate_id: p for p in proms}
        n_prom = sum(1 for p in proms if p.promoted)
        best = max(proms, key=lambda p: p.deflated_sharpe_prob)
        bm = mby[best.candidate_id]
        # the variant with the strongest REAL out-of-sample (holdout) evidence
        best_oos = max(proms, key=lambda p: float(mby[p.candidate_id].holdout_deflated_sharpe))
        bo = mby[best_oos.candidate_id]
        print(f"\n## {spec.name}")
        print(f"   variants traded: {traded}/{len(grid)} | promoted: {n_prom}")
        print(f"   best in-sample dSR : {best.deflated_sharpe_prob:.3f}  (holdoutDSR={float(bm.holdout_deflated_sharpe):+.3f}, "
              f"trades={int(bm.num_trades)}, net={float(bm.oos_return):+.3f})")
        print(f"   best HOLDOUT dSR   : {float(bo.holdout_deflated_sharpe):+.3f}  (in-sample dSR={best_oos.deflated_sharpe_prob:.3f}, "
              f"trades={int(bo.num_trades)}, net={float(bo.oos_return):+.3f})")
        print(f"   VERDICT: {'SURVIVOR' if n_prom else 'no honest edge — killed by the Gate'}")


if __name__ == "__main__":
    main()
