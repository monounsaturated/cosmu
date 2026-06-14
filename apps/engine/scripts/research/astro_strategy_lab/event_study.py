#!/usr/bin/env python3
# intent: EVENT STUDY done right — the honest, open-minded test of the one curiosity the composite surfaced
# (the lunar/eclipse/retrograde 'event' group). The memo's key insight: a self-fulfilling ATTENTION effect around
# a NAMED, pre-scheduled date shows up first as a VOLATILITY / TURNOVER bump, not a return — and strongest in
# retail-heavy SMALL-CAP crypto. So for each named astro event we measure the ±k-day window's realized vol, |return|,
# volume-z, AND signed return, and compare to a PERMUTATION NULL of FAKE event dates (same count, random). The fake-
# date placebo is the disconfirmer: if real events look like fake events, it's noise. BH-FDR across every
# (event × segment × metric) test so the scan can't manufacture a coincidence. PIT, real data, no fabrication.

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ENGINE_ROOT))
sys.path.insert(0, str(ENGINE_ROOT / "scripts/research/astro_deep"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import astro_features_deep as AF  # noqa: E402
import real_panel as RP  # noqa: E402
from lab_store import LabStore  # noqa: E402
from run_lab import SEGMENTS, all_symbols  # noqa: E402

# named events → the panel binary flag whose 0→1 ONSET marks the event
EVENTS = {
    "new_moon": "moon_near_new",
    "full_moon": "moon_near_full",
    "eclipse": "eclipse_window",
    "mercury_retro": "mercury_retrograde_flag",
    "mars_saturn_hard": "mars_saturn_hard_aspect",
}
WINDOW = 3  # ±k days around the onset


def onsets(flag: np.ndarray, dates: pd.DatetimeIndex) -> list[int]:
    """Index positions where the flag transitions 0→1 (the event ONSET)."""
    f = np.nan_to_num(flag) > 0.5
    return [i for i in range(1, len(f)) if f[i] and not f[i - 1]]


def window_stats(metric: np.ndarray, idxs: list[int], k: int) -> float:
    """Mean of `metric` over the ±k windows around the given onset indices (NaN-safe)."""
    vals = []
    for i in idxs:
        lo, hi = max(0, i - k), min(len(metric), i + k + 1)
        seg = metric[lo:hi]
        seg = seg[np.isfinite(seg)]
        if len(seg):
            vals.append(np.mean(seg))
    return float(np.mean(vals)) if vals else float("nan")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--segments", default="all")
    ap.add_argument("--perm", type=int, default=2000)
    ap.add_argument("--out", default=str(ENGINE_ROOT.parent.parent / "docs/research/astro_event_study.md"))
    args = ap.parse_args()
    segs = list(SEGMENTS) if args.segments == "all" else args.segments.split(",")
    crypto, equity = all_symbols(segs)
    sym_seg = {s: seg for seg in segs for s in SEGMENTS[seg]}

    print(f"[1/3] prices {len(crypto)}c+{len(equity)}e · astro event flags …", flush=True)
    bars = RP.load_crypto_bars(crypto, "1d", days=3650)
    bars.update(RP.load_equity_bars(equity))
    bars = {s: b for s, b in bars.items() if len(b) >= 500}
    dates = pd.DatetimeIndex(sorted({d for b in bars.values() for d in b.index}))
    panel = AF.deep_astro_features(dates)
    ev_idx = {name: onsets(panel[flag].to_numpy(float), dates) for name, flag in EVENTS.items() if flag in panel}
    print("   event onsets: " + ", ".join(f"{n}={len(ix)}" for n, ix in ev_idx.items()), flush=True)

    # per-asset metric series aligned to the union `dates`, with the SAME onset indices (panel-aligned)
    print("[2/3] window vol/|ret|/volume-z/ret vs FAKE-date permutation null …", flush=True)
    rng = np.random.default_rng(20260614)
    rows = []
    metrics = ["realized_vol", "abs_ret", "volume_z", "ret"]
    # pool by segment (retail-small-cap is the hypothesis), and an all-crypto pool
    pools = {seg: [s for s in bars if sym_seg.get(s) == seg] for seg in segs}
    pools["crypto_all"] = [s for s in bars if s.endswith("USDT")]
    for pool_name, syms in pools.items():
        if not syms:
            continue
        # build pooled, panel-aligned metric matrices (rows=dates, cols=assets)
        ret_m, vol_m, abs_m, volz_m = {}, {}, {}, {}
        for s in syms:
            b = bars[s].reindex(dates)
            r = np.log(b["close"]).diff()
            ret_m[s] = r
            abs_m[s] = r.abs()
            vol_m[s] = r.rolling(5, min_periods=2).std()
            v = np.log(b["volume"].replace(0, np.nan))
            volz_m[s] = (v - v.rolling(60, min_periods=20).mean()) / v.rolling(60, min_periods=20).std()
        M = {"realized_vol": pd.DataFrame(vol_m).mean(axis=1).to_numpy(),
             "abs_ret": pd.DataFrame(abs_m).mean(axis=1).to_numpy(),
             "volume_z": pd.DataFrame(volz_m).mean(axis=1).to_numpy(),
             "ret": pd.DataFrame(ret_m).mean(axis=1).to_numpy()}
        valid = np.where(np.isfinite(M["realized_vol"]))[0]
        if len(valid) < 300:
            continue
        for ename, idxs in ev_idx.items():
            idxs = [i for i in idxs if i in set(valid)]
            if len(idxs) < 8:
                continue
            for met in metrics:
                obs = window_stats(M[met], idxs, WINDOW)
                # permutation null: fake onsets, same count, drawn from valid dates
                null = np.array([window_stats(M[met], list(rng.choice(valid, len(idxs), replace=False)), WINDOW)
                                 for _ in range(args.perm)])
                null = null[np.isfinite(null)]
                if not len(null) or not np.isfinite(obs):
                    continue
                # vol/volume/abs_ret: test for a SPIKE (one-sided high); ret: two-sided
                if met == "ret":
                    p = (1 + np.sum(np.abs(null - np.mean(null)) >= abs(obs - np.mean(null)))) / (1 + len(null))
                else:
                    p = (1 + np.sum(null >= obs)) / (1 + len(null))
                rows.append(dict(pool=pool_name, event=ename, metric=met, n_events=len(idxs),
                                 observed=obs, null_mean=float(np.mean(null)),
                                 effect=float((obs - np.mean(null)) / (np.std(null) + 1e-12)), p=float(p)))

    print("[3/3] BH-FDR across all tests + report …", flush=True)
    from cosmu.master.fdr import benjamini_hochberg

    df = pd.DataFrame(rows)
    if len(df):
        df["survives_fdr"] = benjamini_hochberg(df["p"].tolist(), q=0.05)
    store = LabStore()
    if len(df):
        store.save_batch(df, "event_study/results")
    report(args.out, df, segs=segs, perm=args.perm)
    print(f"\nDONE → {args.out} · saved to r2://{store.bucket}/astro_lab/event_study/", flush=True)


def report(path, df, *, segs, perm) -> None:
    out = Path(path); out.parent.mkdir(parents=True, exist_ok=True)
    if df.empty:
        out.write_text("# Astro event study — no events/data\n"); return
    nsurv = int(df["survives_fdr"].sum())
    surv = df[df["survives_fdr"]]
    L = ["# Astro event study — vol/turnover around named events vs a fake-date placebo\n",
         f"_For each named astro event (new/full moon, eclipse, Mercury-retro station, Mars-Saturn hard aspect), the "
         f"±{WINDOW}-day window's realized-vol / |return| / volume-z / return, pooled by segment, vs a permutation null "
         f"of {perm} FAKE-date sets (same count, random). The fake-date placebo is the disconfirmer. BH-FDR over all "
         f"{len(df)} (event×pool×metric) tests. Real data, PIT. `event_study.py`._\n",
         f"## Verdict — **{nsurv} of {len(df)} tests beat the fake-date placebo after BH-FDR(5%)**\n"]
    if nsurv:
        L.append("⚠️ Some events beat their placebo — candidates for a proper deflated + forward test (NOT yet an edge):\n")
        L.append(surv.sort_values("p")[["pool", "event", "metric", "n_events", "effect", "p"]].to_markdown(index=False))
    else:
        L.append("None. Named astro-event windows are statistically indistinguishable from random dates — the "
                 "'event' curiosity was noise. The honest open-minded test, with a hard placebo, kills it.\n")
    L.append("\n## Strongest raw effects (pre-FDR — read skeptically)\n")
    top = df.reindex(df["effect"].abs().sort_values(ascending=False).index).head(15)
    L.append(top[["pool", "event", "metric", "n_events", "observed", "null_mean", "effect", "p", "survives_fdr"]].to_markdown(index=False))
    L.append("\n_`effect` = (observed − fake-date mean) / fake-date std. |effect|≳3 with a low p AND FDR-survival is "
             "the only thing worth a follow-up; an isolated big effect at small n_events is the usual mirage._\n")
    out.write_text("\n".join(str(x) for x in L) + "\n")


if __name__ == "__main__":
    main()
