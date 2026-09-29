# intent: driver for the WAVE-1 nonlinear_ml_purged study. Builds the pooled multi-asset panel,
# runs astro_only / +macro / macro_only / +interactions under CPCV+purge+embargo at h=1,5,20,
# vs a block-label-permutation null, with Bonferroni across the whole grid. Prints a LENS-shaped summary.

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cpcv_harness as C  # noqa: E402

import os

CRYPTO_FULL = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
    "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "ATOMUSDT", "UNIUSDT",
    "FILUSDT", "NEARUSDT", "AAVEUSDT",
]
# longest-history liquid majors (all 2017-2020 listings) — ~24k pooled rows, fits ~2x faster than the
# full 17-asset 43k matrix while keeping genuine cross-sectional breadth. Override with CPCV_CRYPTO=full.
CRYPTO_CORE = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "LTCUSDT", "ADAUSDT",
               "LINKUSDT", "DOGEUSDT", "BCHUSDT", "ATOMUSDT"]
CRYPTO = CRYPTO_FULL if os.environ.get("CPCV_CRYPTO") == "full" else CRYPTO_CORE
EQUITY = ["SPY", "QQQ", "IWM", "GLD", "SLV", "TLT", "XLE", "XLF", "XLK", "USO"]

HORIZONS = tuple(int(x) for x in os.environ.get("CPCV_HORIZONS", "1,5,20").split(","))
N_GROUPS = int(os.environ.get("CPCV_NGROUPS", "6"))
B = int(sys.argv[2]) if len(sys.argv) > 2 else 200


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "crypto_full"
    all_rows = []

    def do(symbols, asset_class, tag, require_macro):
        print(f"\n{'='*92}\n{tag}  ({asset_class}, {len(symbols)} symbols, require_macro={require_macro})\n{'='*92}")
        panel = C.build_panel(symbols, asset_class, HORIZONS, require_macro=require_macro)
        if panel is None:
            print("  PANEL EMPTY"); return
        print(f"  pooled rows={len(panel['t_rank'])}  assets={panel['n_assets']}  "
              f"astro_feats={panel['Xa'].shape[1]}  macro_feats={panel['Xm'].shape[1]}", flush=True)
        rows = C.run_comparison(panel, HORIZONS, n_groups=N_GROUPS, k_test=2, embargo_extra=2, B=B, tag=tag)
        all_rows.extend(rows)

    if which in ("crypto_full", "all"):
        # FULL history: macro absent pre-2022 (median-imputed + isnan flag). astro spans full history.
        do(CRYPTO, "crypto", "crypto_fullhist", require_macro=False)
    if which in ("crypto_macro", "all"):
        # MACRO-OVERLAP window only: apples-to-apples for +macro / interactions (every row has real macro).
        do(CRYPTO, "crypto", "crypto_macrowin", require_macro=True)
    if which in ("equity_full", "all"):
        do(EQUITY, "equity", "equity_fullhist", require_macro=False)
    if which in ("equity_macro", "all"):
        do(EQUITY, "equity", "equity_macrowin", require_macro=True)

    # ── Bonferroni across the whole grid ──
    m = len(all_rows)
    print(f"\n{'='*92}\nSUMMARY  ({m} tests, Bonferroni α=0.05/{m}={0.05/max(m,1):.5f})\n{'='*92}")
    print(f"{'tag':18s} {'model':24s} {'h':>3} {'AUC':>7} {'null_p95':>9} {'p':>8} {'edge_bps':>9} {'survive':>8}")
    survivors = []
    for r in sorted(all_rows, key=lambda x: x["p"]):
        # implied per-trade directional edge in bps: 2*(AUC-0.5) is a rough hit-rate lift proxy.
        edge_bps = 2 * (r["auc"] - 0.5) * 100  # in "bps of hit-rate-advantage" units (illustrative)
        surv = (np.isfinite(r["p"]) and r["p"] < 0.05 / max(m, 1)
                and r["auc"] > r["null_p95"] and r["auc"] > 0.52)
        if surv:
            survivors.append(r)
        print(f"{r['tag']:18s} {r['model']:24s} {r['horizon']:>3} {r['auc']:>7.4f} "
              f"{r['null_p95']:>9.4f} {r['p']:>8.4f} {edge_bps:>9.2f} {'YES' if surv else 'no':>8}")

    print(f"\nSURVIVORS (Bonferroni + AUC>null_p95 + AUC>0.52): {len(survivors)}")
    for r in survivors:
        print("  ", r["tag"], r["model"], "h=", r["horizon"], "AUC=", round(r["auc"], 4), "p=", round(r["p"], 4))

    out = Path(f"/tmp/cpcv_results_{which}.json")
    out.write_text(json.dumps(all_rows, indent=2, default=float))
    print(f"\nwrote {out}")
    print("RUN-COMPLETE", flush=True)


if __name__ == "__main__":
    main()
