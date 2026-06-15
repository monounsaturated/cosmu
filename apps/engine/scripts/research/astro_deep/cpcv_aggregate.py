# intent: aggregate the per-tag CPCV result JSONs into the final LENS verdict. Loads
# /tmp/cpcv_results_<tag>.json, applies Bonferroni across the WHOLE grid, and flags candidates that
# beat their proper (block-permutation) null AND clear an economic floor. Pure read/print — no fitting.

from __future__ import annotations

import glob
import json
from pathlib import Path

import numpy as np


def load_all() -> list[dict]:
    rows = []
    for f in sorted(glob.glob("/tmp/cpcv_results_*.json")):
        try:
            rows.extend(json.loads(Path(f).read_text()))
        except Exception:  # noqa: BLE001
            pass
    return rows


def main():
    rows = [r for r in load_all() if np.isfinite(r.get("auc", float("nan")))]
    m = len(rows)
    if not m:
        print("NO RESULTS YET"); return
    bonf = 0.05 / m
    print(f"{'='*100}\nCPCV nonlinear_ml_purged — {m} tests · Bonferroni α=0.05/{m}={bonf:.5f}\n{'='*100}")
    print(f"{'tag':18s} {'model':22s} {'h':>3} {'n':>6} {'AUC':>7} {'nullμ':>7} {'p95':>7} "
          f"{'p':>7} {'edge%':>6} {'verdict':>10}")
    # for each test: directional accuracy lift over base-rate ~ (AUC-0.5); "edge%" is 2*(AUC-0.5)*100.
    survivors, lucky = [], []
    for r in sorted(rows, key=lambda x: (x["tag"], x["horizon"], x["model"])):
        auc, p, p95 = r["auc"], r.get("p", float("nan")), r.get("null_p95", float("nan"))
        edge = 2 * (auc - 0.5) * 100
        beats_p95 = np.isfinite(p95) and auc > p95
        strong = np.isfinite(p) and p < bonf and beats_p95 and auc > 0.52
        weak = np.isfinite(p) and p < 0.05 and beats_p95 and auc > 0.51
        verdict = "SURVIVOR" if strong else ("lucky?" if weak else "—")
        if strong:
            survivors.append(r)
        elif weak:
            lucky.append(r)
        print(f"{r['tag']:18s} {r['model']:22s} {r['horizon']:>3} {r['n']:>6} {auc:>7.4f} "
              f"{r.get('null_mean',float('nan')):>7.4f} {p95:>7.4f} {p:>7.4f} {edge:>6.2f} {verdict:>10}")

    print(f"\nSTRONG SURVIVORS (Bonferroni p<{bonf:.5f} AND AUC>null_p95 AND AUC>0.52): {len(survivors)}")
    for r in survivors:
        print(f"   {r['tag']} {r['model']} h={r['horizon']} AUC={r['auc']:.4f} p={r['p']:.4f}")
    print(f"\nWEAK/LUCKY (p<0.05 but NOT Bonferroni; flag, don't trust): {len(lucky)}")
    for r in lucky:
        print(f"   {r['tag']} {r['model']} h={r['horizon']} AUC={r['auc']:.4f} p={r['p']:.4f} "
              f"(edge {2*(r['auc']-0.5)*100:.2f}% — below ~{10}bps tradeable floor unless AUC≫0.52)")

    # incremental view: does +macro or +interact ADD over astro_only / does astro ADD over macro_only?
    print(f"\n{'='*100}\nINCREMENTAL (per tag×horizon: AUC by model — does astro add anything?)\n{'='*100}")
    by = {}
    for r in rows:
        by.setdefault((r["tag"], r["horizon"]), {})[r["model"]] = r["auc"]
    for (tag, h), d in sorted(by.items()):
        a = d.get("astro_only", float("nan")); mo = d.get("macro_only", float("nan"))
        am = d.get("astro+macro", float("nan")); ai = d.get("astro+macro+interact", float("nan"))
        print(f"{tag:18s} h={h:>2}  astro={a:.4f}  macro={mo:.4f}  astro+macro={am:.4f} "
              f"(Δastro_over_macro={am-mo:+.4f})  +interact={ai:.4f} (Δ={ai-am:+.4f})")


if __name__ == "__main__":
    main()
