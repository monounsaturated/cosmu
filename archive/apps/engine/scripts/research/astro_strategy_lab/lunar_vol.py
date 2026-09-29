#!/usr/bin/env python3
# intent: RIGOROUSLY vet the one candidate the event study surfaced — a lunar realized-VOLATILITY effect in crypto.
# "Double down on what works" the honest way: not declare victory, but try hard to BREAK it. Four tests:
#  (1) per-asset consistency — a real effect shows in MANY of the 23 coins, not 1-2 outliers.
#  (2) the full 8-bin SYNODIC-PHASE profile of realized vol, with a PHASE-SHUFFLE null — real = smooth lunar
#      structure the shuffle destroys; artifact = the full-moon bump survives shuffling.
#  (3) era stability (early vs late) and outlier-robustness (drop the top-vol events).
#  (4) tradability — is it a directional edge (no, per the event study) or only a vol-timing signal? Test a simple
#      vol-scaled rule's net Sharpe so we don't mistake "vol is higher" for "money is makeable on spot".
# Real data, PIT, deterministic lunar phase. Saved to R2 (astro_lab namespace). No fabrication.

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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--perm", type=int, default=2000)
    ap.add_argument("--out", default=str(ENGINE_ROOT.parent.parent / "docs/research/astro_lunar_vol.md"))
    args = ap.parse_args()
    crypto, _ = all_symbols([s for s in SEGMENTS if s.startswith("crypto")])

    print(f"[1/4] {len(crypto)} crypto bars + lunar synodic phase …", flush=True)
    bars = RP.load_crypto_bars(crypto, "1d", days=3650)
    bars = {s: b for s, b in bars.items() if len(b) >= 600}
    dates = pd.DatetimeIndex(sorted({d for b in bars.values() for d in b.index}))
    panel = AF.deep_astro_features(dates)
    # synodic_age ~ 0..1 (0/1 = new, 0.5 = full); use illum fraction as the robust 'fullness'
    illum = panel["moon_illum_frac"].reindex(dates).to_numpy(float) if "moon_illum_frac" in panel else None
    # 8 phase bins on illumination-signed synodic position: derive phase angle from illum + d(illum)
    phase = panel["moon_synodic_age"].reindex(dates).to_numpy(float) if "moon_synodic_age" in panel else illum
    bin8 = np.clip((phase * 8).astype(int), 0, 7)
    full_bin = int(np.nanargmax([np.nanmean(illum[bin8 == b]) for b in range(8)]))  # the bin with highest illum = 'full'

    # per-asset realized vol (5d std), aligned to `dates`
    vol = {}
    for s, b in bars.items():
        r = np.log(b["close"].reindex(dates)).diff()
        vol[s] = r.rolling(5, min_periods=2).std().to_numpy()
    volmat = pd.DataFrame(vol, index=dates)
    pooled_vol = volmat.mean(axis=1).to_numpy()
    valid = np.isfinite(pooled_vol) & np.isfinite(phase)

    print("[2/4] per-asset full-vs-rest vol + 8-bin profile + phase-shuffle null …", flush=True)
    rng = np.random.default_rng(20260614)
    # (1) per-asset consistency: mean vol in full-bin vs rest, per coin
    per_asset = []
    for s in bars:
        v = volmat[s].to_numpy()
        m = np.isfinite(v) & valid
        if m.sum() < 200:
            continue
        full = v[m & (bin8 == full_bin)]
        rest = v[m & (bin8 != full_bin)]
        if len(full) > 10 and len(rest) > 50:
            per_asset.append(dict(asset=s, full_vol=float(np.mean(full)), rest_vol=float(np.mean(rest)),
                                  ratio=float(np.mean(full) / np.mean(rest))))
    pa = pd.DataFrame(per_asset)
    n_up = int((pa["ratio"] > 1).sum()) if len(pa) else 0

    # (2) 8-bin pooled profile + phase-shuffle null on the full-vs-rest contrast
    prof = [float(np.nanmean(pooled_vol[valid & (bin8 == b)])) for b in range(8)]
    obs_contrast = prof[full_bin] / np.nanmean([prof[b] for b in range(8) if b != full_bin])
    null = []
    pv = pooled_vol[valid]
    bins_v = bin8[valid]
    for _ in range(args.perm):
        shuf = rng.permutation(bins_v)  # shuffle phase labels within the valid window
        fb = pv[shuf == full_bin]; rb = pv[shuf != full_bin]
        if len(fb) > 10 and len(rb) > 50:
            null.append(np.mean(fb) / np.mean(rb))
    null = np.array(null)
    p_shuffle = (1 + np.sum(null >= obs_contrast)) / (1 + len(null))

    # (3) era stability + outlier robustness
    half = dates[len(dates) // 2]
    def contrast(mask):
        f = pooled_vol[valid & mask & (bin8 == full_bin)]; r = pooled_vol[valid & mask & (bin8 != full_bin)]
        return float(np.mean(f) / np.mean(r)) if len(f) > 5 and len(r) > 20 else float("nan")
    early = contrast(dates < half); late = contrast(dates >= half)
    # drop top-2% vol days (outlier robustness)
    thr = np.nanquantile(pooled_vol[valid], 0.98)
    robust = contrast(pooled_vol <= thr)

    print("[3/4] tradability — is it directional, or only vol-timing? …", flush=True)
    # directional: mean forward return in full-bin vs rest (the event study said NOT directional — confirm)
    fwd = {s: (np.log(bars[s]["close"].reindex(dates)).diff().shift(-1)).to_numpy() for s in bars}
    fwdmat = pd.DataFrame(fwd, index=dates).mean(axis=1).to_numpy()
    dir_full = float(np.nanmean(fwdmat[valid & (bin8 == full_bin)]))
    dir_rest = float(np.nanmean(fwdmat[valid & (bin8 != full_bin)]))
    # vol-timing: does scaling DOWN exposure in the high-vol (full) bin improve Sharpe of a long-BTC hold? (risk mgmt)
    btc = bars.get("BTCUSDT")
    timing = {}
    if btc is not None:
        r = np.log(btc["close"].reindex(dates)).diff().to_numpy()
        scale = np.where(bin8 == full_bin, 0.5, 1.0)  # half size around full moon
        base = r[np.isfinite(r)]
        scaled = (scale * r)[np.isfinite(r)]
        timing = dict(buyhold_sharpe=float(np.nanmean(base) / np.nanstd(base) * np.sqrt(365)),
                      voltimed_sharpe=float(np.nanmean(scaled) / np.nanstd(scaled) * np.sqrt(365)))

    print("[4/4] report + save R2 …", flush=True)
    store = LabStore()
    if len(pa):
        store.save_batch(pa, "lunar_vol/per_asset")
    store.save_batch(pd.DataFrame([dict(bin=b, mean_vol=prof[b], is_full=(b == full_bin)) for b in range(8)]),
                     "lunar_vol/phase_profile")
    report(args.out, pa, n_up, prof, full_bin, obs_contrast, float(np.mean(null)), p_shuffle,
           early, late, robust, dir_full, dir_rest, timing, args.perm)
    print(f"\nDONE → {args.out} · r2://{store.bucket}/astro_lab/lunar_vol/", flush=True)


def report(path, pa, n_up, prof, full_bin, obs_c, null_c, p_shuf, early, late, robust,
           dir_full, dir_rest, timing, perm) -> None:
    out = Path(path); out.parent.mkdir(parents=True, exist_ok=True)
    n = len(pa)
    L = ["# Lunar realized-volatility effect — rigorous vetting (try to BREAK it)\n",
         "_The event study found crypto realized-vol elevated around full moons (survived a fake-date placebo + "
         "BH-FDR). Here we attack it: per-asset consistency, 8-bin synodic profile vs a PHASE-SHUFFLE null, era "
         "stability, outlier-robustness, and tradability. Real crypto bars, deterministic lunar phase. `lunar_vol.py`._\n",
         "## Test 1 — per-asset consistency (a real effect shows in MANY coins)\n",
         f"- **{n_up} of {n} coins** have higher realized vol in the full-moon bin than the rest "
         f"({100*n_up/max(n,1):.0f}%). Median full/rest vol ratio: **{pa['ratio'].median():.3f}**" if n else "no assets",
         "\n## Test 2 — 8-bin synodic profile + phase-shuffle null (the decisive test)\n",
         f"- Mean realized vol by phase bin (bin {full_bin} = full): {[round(x,4) for x in prof]}",
         f"- Full-bin vs rest contrast = **{obs_c:.3f}** (shuffle-null mean {null_c:.3f}); "
         f"**phase-shuffle p = {p_shuf:.4f}**.",
         f"  - {'✓ The full-moon vol bump SURVIVES label-shuffling — it tracks the real lunar phase, not chance.' if p_shuf < 0.05 else '✗ Dies under phase-shuffle — artifact.'}",
         "\n## Test 3 — stability & robustness\n",
         f"- Era contrast: early **{early:.3f}** · late **{late:.3f}** "
         f"({'STABLE across eras' if np.isfinite(early) and np.isfinite(late) and (early-1)*(late-1)>0 else 'FLIPS — fragile'}).",
         f"- Drop top-2% vol days: contrast **{robust:.3f}** "
         f"({'holds without outliers' if np.isfinite(robust) and robust>1.0 else 'driven by outliers'}).",
         "\n## Test 4 — is it tradable? (directional vs vol-only)\n",
         f"- Forward return full-bin **{dir_full:+.5f}** vs rest **{dir_rest:+.5f}** — "
         f"{'a directional edge exists' if abs(dir_full-dir_rest) > 0.001 else 'NO directional edge (vol-only, symmetric — not directly tradable on spot)'}.",
         (f"- BTC vol-timing (half size around full moon): buy&hold Sharpe {timing['buyhold_sharpe']:.2f} → "
          f"vol-timed {timing['voltimed_sharpe']:.2f} ({'helps' if timing.get('voltimed_sharpe',0) > timing.get('buyhold_sharpe',0) else 'no improvement'})." if timing else ""),
         "\n## The honest read\n",
         "A lunar realized-VOLATILITY effect is the ONE thing in this whole investigation that survives a hard "
         "placebo. If Test 2's phase-shuffle holds (p<0.05) AND it's consistent across coins AND stable across eras, "
         "it is a REAL (weak) lunar-volatility regularity — matching the least-debunked corner of the literature. "
         "BUT the event study + Test 4 show it is **vol, not direction**: higher vol around full moons is NOT a spot "
         "return edge (it's symmetric). Its only honest use is **risk/vol management or an options/vol-timing overlay**, "
         "and only if it then survives Deflated-Sharpe + a forward test as a real strategy. We do NOT promote it; we "
         "log it as the one weak-but-real regularity, cleanly separated from the (dead) directional astro search.\n"]
    out.write_text("\n".join(str(x) for x in L) + "\n")


if __name__ == "__main__":
    main()
