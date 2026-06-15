# intent: WAVE-1 hierarchical_bayes — ECONOMIC companion to hier_bayes_meta.
#
# The IC meta-analysis pools a rank correlation; practitioners actually trade BINARY astro EVENTS
# ("buy the new moon", "avoid mercury retrograde", "eclipse windows"). For each binary astro event
# we compute, PER ASSET, the difference in mean next-day log return on event days vs non-event days
# (an economic effect in bps, with its standard error), then POOL across assets with DerSimonian-
# Laird random effects. Question: is the pooled event premium distinguishable from 0 for ANY event,
# beyond a circular-shift null that preserves each asset's autocorrelation — AND is it bigger than a
# ~10bps round-trip cost so it's actually tradeable?
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "astro_strategy_lab"))

import astro_features_deep as AF  # noqa: E402
import hier_bayes_meta as HM  # noqa: E402  (reuse loaders + DL)


def event_effect_per_asset(event: np.ndarray, ret_next: np.ndarray) -> tuple[float, float, int, int]:
    """Mean(ret on event days) - mean(ret on non-event days), with Welch SE. Effect in RAW log-ret.

    event/ret_next aligned (event_t -> ret_{t+1}). Returns (diff, se, n_event, n_total)."""
    mask = np.isfinite(event) & np.isfinite(ret_next)
    ev = event[mask].astype(bool)
    r = ret_next[mask]
    n1 = int(ev.sum())
    n0 = int((~ev).sum())
    if n1 < 20 or n0 < 50:
        return np.nan, np.nan, n1, n1 + n0
    a = r[ev]
    b = r[~ev]
    diff = float(a.mean() - b.mean())
    se = float(np.sqrt(a.var(ddof=1) / n1 + b.var(ddof=1) / n0))
    if not np.isfinite(se) or se <= 0:
        return np.nan, np.nan, n1, n1 + n0
    return diff, se, n1, n1 + n0


def pooled_event(event_lag: np.ndarray, ret_next: list[np.ndarray]) -> dict | None:
    ys, vs, ns = [], [], []
    for rr in ret_next:
        diff, se, n1, _ = event_effect_per_asset(event_lag, rr)
        if not np.isfinite(diff) or not np.isfinite(se):
            continue
        ys.append(diff)
        vs.append(se**2)
        ns.append(n1)
    if len(ys) < 8:
        return None
    dl = HM.dersimonian_laird_raw(np.asarray(ys), np.asarray(vs))
    dl["mean_n_event"] = float(np.mean(ns))
    return dl


def main(n_surr: int = 600, seed: int = 7) -> None:
    rng = np.random.default_rng(seed)
    print("Loading real price panel ...", flush=True)
    wide = HM.load_returns(min_days=800)
    print(f"  assets: {wide.shape[1]}  range {wide.index.min().date()}..{wide.index.max().date()}",
          flush=True)
    raw = AF.deep_astro_features(wide.index)

    # binary events that actually fire in-window (skip degenerate)
    events = [c for c in AF.BINARY_COLS if raw[c].astype(float).nunique(dropna=True) > 1]
    print(f"  binary astro events tested: {len(events)} -> {events}", flush=True)

    rets = {s: wide[s].to_numpy(dtype=float) for s in wide.columns}
    syms = list(rets)
    ev_lag = {c: raw[c].to_numpy(dtype=float)[:-1] for c in events}

    def ret_next_for(rr): return [rr[s][1:] for s in syms]

    obs = {}
    for c in events:
        res = pooled_event(ev_lag[c], ret_next_for(rets))
        if res is not None:
            obs[c] = res
    print(f"  events with a valid pooled estimate: {len(obs)}", flush=True)

    obs_absz = {c: abs(obs[c]["z_stat"]) for c in obs}
    ge = {c: 0 for c in obs}
    null_max = np.empty(n_surr)
    print(f"Running {n_surr} circular-shift surrogates (autocorr-preserving null) ...", flush=True)
    for s in range(n_surr):
        shifted = HM.circular_shift_returns(rets, rng)
        rn = ret_next_for(shifted)
        cmax = 0.0
        for c in obs:
            res = pooled_event(ev_lag[c], rn)
            az = abs(res["z_stat"]) if res is not None else 0.0
            if az >= obs_absz[c]:
                ge[c] += 1
            cmax = max(cmax, az)
        null_max[s] = cmax
        if (s + 1) % 100 == 0:
            print(f"  surrogate {s + 1}/{n_surr}", flush=True)

    rows = []
    for c in obs:
        r = obs[c]
        bps = r["mu"] * 1e4  # log-ret -> ~bps
        rows.append({
            "event": c, "k_assets": r["k"], "premium_bps": bps,
            "ci_lo_bps": r["ci_lo"] * 1e4, "ci_hi_bps": r["ci_hi"] * 1e4,
            "mean_n_event": r["mean_n_event"], "tau2": r["tau2"], "z_pool": r["z_stat"],
            "p_perm": (ge[c] + 1) / (n_surr + 1),
            "p_fwe": (np.sum(null_max >= obs_absz[c]) + 1) / (n_surr + 1),
        })
    df = pd.DataFrame(rows).sort_values("p_perm").reset_index(drop=True)
    m = len(df)
    df["rank"] = np.arange(1, m + 1)
    df["bh_thresh"] = df["rank"] / m * 0.05
    passes = df.loc[df["p_perm"] <= df["bh_thresh"], "rank"]
    maxp = int(passes.max()) if len(passes) else 0
    df["bh_survive"] = df["rank"] <= maxp

    pd.set_option("display.width", 220, "display.float_format", lambda v: f"{v:.4f}")
    print("\n=== Pooled binary-event premiums (economic, bps) ===")
    print(df[["event", "k_assets", "premium_bps", "ci_lo_bps", "ci_hi_bps", "mean_n_event",
              "z_pool", "p_perm", "p_fwe", "bh_survive"]].to_string(index=False))
    print(f"\nEvents tested: {m}  | BH-FDR survivors: {int(df['bh_survive'].sum())} "
          f"| FWE p<=0.05: {int((df['p_fwe'] <= 0.05).sum())} "
          f"| perm-p floor: {1/(n_surr+1):.4f}")
    print("TRADEABILITY: a pooled premium must clear ~10bps round-trip net AND survive the null.")
    df.to_csv(HERE / "_hier_bayes_events_results.csv", index=False)
    print(f"full results -> {HERE / '_hier_bayes_events_results.csv'}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--surr", type=int, default=600)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    main(n_surr=a.surr, seed=a.seed)
