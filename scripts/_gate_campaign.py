"""Gate a BATCH of newly-authored specs through the honest Gate, archive every verdict.

For each new spec: grid-fit params (build_grid), pool the backtest across its universe (crypto majors OR
equity ETFs) with the real PIT alt join, register every variant as a trial (honest deflation), pick the
IN-SAMPLE champion. Then gate ALL champions as ONE cohort (honest cross-batch BH-FDR + champion-only
holdout, net of real fees) and PERSIST the verdicts to gate_verdicts (the durable archive). Reuses the
canonical machinery — never re-implements the Gate. Prints a per-spec results table.

Reads the set of spec names to gate from /tmp/new_spec_names.json (list of names); falls back to the 3
capitulation specs. ZERO LLM on the gate path.
"""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import cosmu.research.matrix_search as ms
from cosmu.lab.finder import build_grid
from cosmu.research.regime_cohort import load_tr_bars
from cosmu.master.verdict_log import durable_persist

CRYPTO = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "ADAUSDT", "AVAXUSDT", "XRPUSDT", "LINKUSDT"]
EQUITY = ["SPY", "QQQ", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLU", "XLI", "XLB"]
TF = "1d"
MAX_VARIANTS = 96

_names_file = Path("/tmp/new_spec_names.json")
if _names_file.exists():
    NEW = set(json.loads(_names_file.read_text()))
else:
    NEW = {
        "Fear & Greed extreme-fear contrarian long (spot)",
        "VIX spike cross-asset capitulation long (spot crypto)",
        "Cross-asset capitulation composite long (Fear&Greed + VIX)",
    }


def _market_for(spec):
    classes = list(spec.universe.asset_classes)
    if "equity" in classes and "crypto" not in classes:
        m = {}
        for s in EQUITY:
            try:
                bars = load_tr_bars(s)
            except Exception:  # noqa: BLE001
                bars = []
            if len(bars) >= 120:
                m[s] = bars
        return m, "equity"
    m = {}
    for s in CRYPTO:
        bars = ms.load_bars(s, TF)
        if len(bars) >= 120:
            m[s] = bars
    return m, "crypto"


def main() -> None:
    specs = [s for s in ms.load_specs() if s.name in NEW]
    print(f"=== gating {len(specs)} new specs (of {len(NEW)} requested) | persist→gate_verdicts ===")
    fee_bps = ms.default_catalog().venue("binance").taker_fee_bps
    alt_store = ms._matrix_alt_store()

    tmp = tempfile.mkdtemp(prefix="cosmu-campaign-")
    store = ms.Store(ms.Settings(database_url=f"sqlite:///{tmp}/m.sqlite3", openrouter_api_key=None))
    champions = []        # one Candidate per spec (its in-sample champion)
    champ_metrics = {}
    rows = []             # (name, universe, traded, is_dsr, holdout, trades, net)
    for spec in specs:
        market, uni = _market_for(spec)
        if not market:
            rows.append((spec.name, uni, 0, 0.0, 0.0, 0, 0.0, "no-bars"))
            continue
        alt = ms.build_alt_by_symbol(alt_store, spec, market) if alt_store is not None else None
        grid = build_grid(spec, max_variants=MAX_VARIANTS)
        best = None  # (in_sample_dsr_proxy=sharpe_per_obs, metrics)
        traded = 0
        for v in grid:
            try:
                res = ms.run_strategy_backtest_detailed(spec, v.params, market, fee_bps=fee_bps, alt_by_symbol=alt)
            except Exception:  # noqa: BLE001
                continue
            m = res.metrics
            if int(m.num_trades) <= 0:
                continue
            traded += 1
            ms.record_trial(store, float(m.sharpe_per_obs), source="campaign", label=f"{spec.name}:{v.config_tag}")
            # champion by IN-SAMPLE evidence (sharpe_per_obs) — never selected on holdout
            if best is None or float(m.sharpe_per_obs) > best[0]:
                best = (float(m.sharpe_per_obs), m)
        if best is None:
            rows.append((spec.name, uni, 0, 0.0, 0.0, 0, 0.0, "0-trades"))
            continue
        m = best[1]
        cid = spec.name
        champions.append(ms.Candidate(id=cid, metrics=m, net_profit=float(m.oos_return), source="campaign", label=cid))
        champ_metrics[cid] = (m, uni, traded)

    if not champions:
        print("no champions traded — nothing to gate.")
        return

    persist = durable_persist(
        run_id="campaign-2026-06-14-hidden-edge",
        hypothesis="hidden-edge campaign: do any web-grounded orthogonal specs survive the honest Gate?",
        source="research/campaign", asset="mixed", timeframe=TF,
    )
    proms = ms.promote_cohort(store, champions, store.settings.gates, register=False,
                              trials=ms.trial_stats(store), persist=persist)
    pby = {p.candidate_id: p for p in proms}
    survivors = [p.candidate_id for p in proms if p.promoted]

    print(f"\n=== COHORT VERDICT: {len(champions)} strategies, {len(survivors)} SURVIVORS (net of real fees) ===\n")
    line = f"{'strategy':52} {'uni':7} {'trad':>4} {'IS_dSR':>7} {'holdout':>8} {'trades':>6} {'net':>7} verdict"
    print(line)
    out = [line]
    for p in sorted(proms, key=lambda p: p.deflated_sharpe_prob, reverse=True):
        m, uni, traded = champ_metrics[p.candidate_id]
        r = (f"{p.candidate_id[:52]:52} {uni:7} {traded:>4} {p.deflated_sharpe_prob:>7.3f} "
             f"{float(m.holdout_deflated_sharpe):>+8.3f} {int(m.num_trades):>6} {float(m.oos_return):>+7.3f} "
             f"{'PROMOTED' if p.promoted else 'killed'}")
        print(r)
        out.append(r)
    for r in rows:  # specs that never traded
        line = f"{r[0][:52]:52} {r[1]:7} {'--':>4} {'--':>7} {'--':>8} {'--':>6} {'--':>7} {r[7]}"
        print(line)
        out.append(line)
    Path("/tmp/campaign_results.txt").write_text("\n".join(out))
    print(f"\narchived {len(champions)} verdicts to gate_verdicts (run_id=campaign-2026-06-14-hidden-edge); table → /tmp/campaign_results.txt")


if __name__ == "__main__":
    main()
