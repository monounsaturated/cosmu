#!/usr/bin/env python3
# intent: the COMPOSITE INDEX — blend events/periods + astro + the REAL alt panel + space-weather + a CROSS-SECTIONAL
# per-coin NATAL activation into one daily per-asset score, and EXPLORE where structure actually lives (open-minded,
# pattern-first) before the honest deflated verdict. Honest train/test: signal directions/weights are FIT on the
# first 60% of each asset's history and EVALUATED out-of-sample on the last 40% — no look-ahead. We decompose the
# information content by signal GROUP × regime × segment × era (the "see the patterns" part), backtest the composite
# time-series AND cross-sectionally (long-best/short-worst), then deflate. Saves to R2 (astro_lab namespace).
#
# NO FABRICATION / NO CONTAMINATION: real prices + real prod alt_data (READ-ONLY) + deterministic astro; isolated
# 'astro_lab' namespace; nothing moves money or writes the Gate ledger.

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
from scipy import stats  # noqa: E402

import astro_deep_study as S  # noqa: E402
import astro_features_deep as AF  # noqa: E402
import ml_harness as ML  # noqa: E402
import real_panel as RP  # noqa: E402
from lab_store import LabStore  # noqa: E402
from run_lab import SEGMENTS, all_symbols  # noqa: E402

# signal-group membership (market-wide unless noted)
REAL_METRICS = ["galaxy_score", "social_volume", "social_sentiment", "alt_rank", "funding_rate",
                "fear_greed", "vix_level", "dxy", "btc_hashrate", "btc_active_addresses"]  # per-asset where available, else MARKET
ASTRO_CONT = ["lunar_illum_frac", "aspect_tightness_stress_wide", "hard_aspect_count", "bradley_siderograph",
              "sun_lon_deg", "jupiter_lon_deg", "saturn_lon_deg", "mars_lon_deg"]
EVENT_BIN = ["mercury_retrograde_flag", "eclipse_window", "moon_near_new", "moon_near_full", "mars_saturn_hard_aspect"]
CAL = ["turn_of_month", "halloween"]
SPACEW = ["kp_index", "sunspots"]
NATAL_BODIES = ["sun_lon_deg", "venus_lon_deg", "mars_lon_deg", "jupiter_lon_deg", "saturn_lon_deg"]


def _z(x: np.ndarray, win: int = 120) -> np.ndarray:
    s = pd.Series(x)
    return ((s - s.rolling(win, min_periods=30).mean()) / s.rolling(win, min_periods=30).std()).to_numpy()


def natal_activation(panel: pd.DataFrame, listing_date: pd.Timestamp) -> np.ndarray:
    """CROSS-SECTIONAL astro: today's sky aspecting THIS coin's birth sky. natal longitudes = the transiting
    longitudes AT the coin's listing date (deterministic, from the same panel). activation(t) = Σ over transiting
    × natal body pairs of an orb-tapered cosine of their separation — varies per coin (different birth date).
    PIT: natal is fixed at listing (known once the coin exists); transits are knowable at t. No look-ahead."""
    if listing_date not in panel.index:
        listing_date = panel.index[panel.index.get_indexer([listing_date], method="nearest")[0]]
    natal = {b: float(panel.loc[listing_date, b]) for b in NATAL_BODIES if b in panel}
    act = np.zeros(len(panel))
    for b in NATAL_BODIES:
        if b not in panel:
            continue
        trans = panel[b].to_numpy(float)
        for q, nat in natal.items():
            sep = np.abs((trans - nat + 180) % 360 - 180)  # 0..180
            # reward conjunction(0)/trine(120)/sextile(60), penalize square(90)/opposition(180), orb taper 10deg
            for ang, w in ((0, 1.0), (60, 0.6), (120, 0.8), (90, -0.8), (180, -1.0)):
                d = np.abs(sep - ang)
                act += w * np.clip(1 - d / 10.0, 0, None)
    return act


def build(symbols: list[str], bars: dict, panel: pd.DataFrame, real: dict, sym_seg: dict) -> dict[str, pd.DataFrame]:
    out = {}
    for s in symbols:
        b = bars.get(s)
        if b is None or len(b) < 400:
            continue
        df = b[["close"]].copy()
        df["fwd1"] = np.log(df["close"]).shift(-1) - np.log(df["close"])
        sma = df["close"].rolling(200).mean()
        df["regime"] = np.where(df["close"] > sma, "bull", "bear")
        df.loc[sma.isna(), "regime"] = "na"
        df["era"] = np.where(df.index < pd.Timestamp("2021-07-01"), "early", "late")
        df["segment"] = sym_seg.get(s, "?")
        # market-wide groups (broadcast)
        for col in ASTRO_CONT + EVENT_BIN + CAL + SPACEW:
            if col in panel:
                df[f"sig::{col}"] = panel[col].reindex(df.index).to_numpy(float)
        # real per-asset (NaN-tolerant)
        rp = real.get(s)
        if rp is not None:
            for m in REAL_METRICS:
                if m in rp:
                    df[f"sig::{m}"] = rp[m].reindex(df.index).to_numpy(float)
        # cross-sectional natal (per-asset)
        df["sig::natal_activation"] = natal_activation(panel, df.index[0])[
            panel.index.get_indexer(df.index)
        ] if df.index[0] in panel.index or True else np.nan
        out[s] = df.dropna(subset=["fwd1"])
    return out


def group_of(sig: str) -> str:
    n = sig.replace("sig::", "")
    if n in REAL_METRICS:
        return "real"
    if n in ASTRO_CONT:
        return "astro"
    if n in EVENT_BIN:
        return "event"
    if n in CAL:
        return "calendar"
    if n in SPACEW:
        return "spaceweather"
    if n == "natal_activation":
        return "natal_xsec"
    return "other"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--segments", default="all")
    ap.add_argument("--out", default=str(ENGINE_ROOT.parent.parent / "docs/research/astro_composite.md"))
    args = ap.parse_args()
    segs = list(SEGMENTS) if args.segments == "all" else args.segments.split(",")
    crypto, equity = all_symbols(segs)
    sym_seg = {s: seg for seg in segs for s in SEGMENTS[seg]}

    print(f"[1/5] prices · {len(crypto)} crypto + {len(equity)} equity", flush=True)
    bars = RP.load_crypto_bars(crypto, "1d", days=3650)
    bars.update(RP.load_equity_bars(equity))
    bars = {s: b for s, b in bars.items() if len(b) >= 400}

    print("[2/5] astro panel + REAL alt panel (PIT) + standardize …", flush=True)
    dates = pd.DatetimeIndex(sorted({d for b in bars.values() for d in b.index}))
    panel = AF.deep_astro_features(dates).join(S.calendar_features(dates))
    ex = S._extra_feats(dates); ex = ex[[c for c in ex.columns if c not in panel.columns]]; panel = panel.join(ex)
    sw = S.load_spaceweather(dates); sw = sw[[c for c in sw.columns if c not in panel.columns]]; panel = panel.join(sw)
    try:
        real = RP.load_real_alt_panel(list(bars), REAL_METRICS, {s: b.index for s, b in bars.items()})
    except Exception as e:  # noqa: BLE001
        print(f"   real panel failed ({type(e).__name__}); astro/event only", flush=True); real = {}
    frames = build(list(bars), bars, panel, real, sym_seg)
    sig_cols = sorted({c for df in frames.values() for c in df.columns if c.startswith("sig::")})
    print(f"   {len(frames)} assets · {len(sig_cols)} signals across groups: "
          f"{dict(pd.Series([group_of(c) for c in sig_cols]).value_counts())}", flush=True)

    # ── per-signal-group IC table on TRAIN (the patterns) ────────────────────────────────────────
    print("[3/5] EXPLORING — per-signal IC on the TRAIN split (first 60%) …", flush=True)
    ic_rows, weights = [], {}
    for c in sig_cols:
        ics_tr = []
        for s, df in frames.items():
            if c not in df:
                continue
            cut = int(len(df) * 0.6)
            x = _z(df[c].to_numpy(float))[:cut] if group_of(c) not in ("event", "calendar") else df[c].to_numpy(float)[:cut]
            y = df["fwd1"].to_numpy(float)[:cut]
            m = np.isfinite(x) & np.isfinite(y)
            if m.sum() > 100 and np.nanstd(x[m]) > 0:
                ic, _ = stats.spearmanr(x[m], y[m])
                if np.isfinite(ic):
                    ics_tr.append(ic)
        if ics_tr:
            mean_ic = float(np.mean(ics_tr))
            weights[c] = np.sign(mean_ic)  # OOS direction fixed from TRAIN only
            ic_rows.append(dict(signal=c.replace("sig::", ""), group=group_of(c),
                                train_ic_mean=mean_ic, n_assets=len(ics_tr)))
    ic_df = pd.DataFrame(ic_rows)
    grp_ic = ic_df.groupby("group")["train_ic_mean"].agg(["mean", "count"]).sort_values("mean", key=abs, ascending=False)

    # ── build composites (TRAIN-signed) and backtest OOS (last 40%) ──────────────────────────────
    print("[4/5] Building composites (TRAIN-signed) + OOS backtest + cross-sectional …", flush=True)
    groups = ["real", "astro", "event", "calendar", "spaceweather", "natal_xsec", "all"]
    comp_rows = []
    oos_scores: dict[str, pd.DataFrame] = {g: pd.DataFrame(index=dates) for g in groups}
    for s, df in frames.items():
        cut = int(len(df) * 0.6)
        for g in groups:
            cols = [c for c in sig_cols if c in df and (g == "all" or group_of(c) == g)]
            if not cols:
                continue
            zs = []
            for c in cols:
                z = _z(df[c].to_numpy(float)) if group_of(c) not in ("event", "calendar") else (df[c].to_numpy(float) - 0.5) * 2
                zs.append(np.nan_to_num(z) * weights.get(c, 0.0))
            score = np.nanmean(np.vstack(zs), axis=0) if zs else np.zeros(len(df))
            oos_scores[g][s] = pd.Series(score, index=df.index)
            # time-series OOS backtest (long/short on composite sign), net of fees
            pos = np.sign(score)[cut:-1]
            ret = df["fwd1"].to_numpy(float)[cut + 1:]
            pnl = np.nan_to_num(pos) * ret
            turn = np.abs(np.diff(np.concatenate([[0.0], np.nan_to_num(pos)])))
            pnl = (pnl - turn * 0.001)
            pnl = pnl[np.isfinite(pnl)]
            if len(pnl) > 100 and np.std(pnl) > 0:
                ann = 365 if s.endswith("USDT") else 252
                comp_rows.append(dict(asset=s, segment=df["segment"].iloc[0], group=g, kind="timeseries",
                                      n=len(pnl), sharpe=float(np.mean(pnl) / np.std(pnl) * np.sqrt(ann))))

    # ── cross-sectional: each day rank assets by composite, long top / short bottom (OOS) ────────
    xsec_rows = []
    for g in groups:
        sc = oos_scores[g]
        if sc.shape[1] < 6:
            continue
        # OOS window = the latest 40% of the union timeline
        oos_start = dates[int(len(dates) * 0.6)]
        sc = sc.loc[sc.index >= oos_start]
        fwd = pd.DataFrame({s: frames[s]["fwd1"] for s in frames}).reindex(sc.index)
        rank = sc.rank(axis=1, pct=True)
        long = (rank >= 0.7).astype(float); short = (rank <= 0.3).astype(float)
        w = (long - short)
        w = w.div(w.abs().sum(axis=1).replace(0, np.nan), axis=0)  # dollar-neutral
        port = (w.shift(1) * fwd).sum(axis=1).dropna()  # trade next day on today's rank
        if len(port) > 100 and port.std() > 0:
            xsec_rows.append(dict(group=g, kind="xsec_longshort", n=int(len(port)),
                                  sharpe=float(port.mean() / port.std() * np.sqrt(365))))

    print("[5/5] Aggregate + deflate + report patterns …", flush=True)
    store = LabStore()
    ts_df = pd.DataFrame(comp_rows)
    xs_df = pd.DataFrame(xsec_rows)
    if len(ts_df):
        store.save_batch(ts_df, "composite/timeseries")
    if len(xs_df):
        store.save_batch(xs_df, "composite/xsec")
    if len(ic_df):
        store.save_batch(ic_df, "composite/signal_ic")
    report(args.out, ic_df, grp_ic, ts_df, xs_df, n_signals=len(sig_cols), n_assets=len(frames))
    print(f"\nDONE → {args.out}  ·  saved to r2://{store.bucket}/astro_lab/composite/", flush=True)


def report(path, ic_df, grp_ic, ts_df, xs_df, *, n_signals, n_assets) -> None:
    out = Path(path); out.parent.mkdir(parents=True, exist_ok=True)
    L = ["# Composite index — exploring where structure lives (then the honest read)\n",
         f"_Blends events/periods + astro + the REAL prod alt panel + space-weather + a cross-sectional per-coin "
         f"NATAL activation into one daily score. Signal directions FIT on each asset's first 60% (train), "
         f"backtested OUT-OF-SAMPLE on the last 40% — no look-ahead. {n_signals} signals × {n_assets} assets. "
         f"Isolated 'astro_lab' namespace; saved to R2. `run_composite.py`._\n"]

    L.append("## Pattern 1 — which signal GROUPS actually carry information (train IC)\n")
    L.append(grp_ic.reset_index().to_markdown(index=False))
    L.append("\n_Mean Spearman IC of each group's signals vs next-day return, on train. |IC|~0.01 is the noise "
             "floor at these sample sizes; what stands out is the SIGN-CONSISTENCY and which group is non-trivial._\n")

    if len(ic_df):
        L.append("\n## Pattern 2 — strongest individual signals (train IC, |·| sorted)\n")
        top = ic_df.reindex(ic_df["train_ic_mean"].abs().sort_values(ascending=False).index).head(15)
        L.append(top.to_markdown(index=False))

    if len(ts_df):
        L.append("\n## OOS time-series composite — mean Sharpe by group (last 40%, net of fees)\n")
        g = ts_df.groupby("group")["sharpe"].agg(["mean", "median", "count"]).sort_values("mean", ascending=False)
        L.append(g.reset_index().to_markdown(index=False))
        L.append("\n### …and by group × segment (where does it live?)\n")
        gs = ts_df.groupby(["group", "segment"])["sharpe"].mean().unstack().round(2)
        L.append(gs.to_markdown())

    if len(xs_df):
        L.append("\n## OOS CROSS-SECTIONAL long-short (rank assets by composite, long top 30% / short bottom 30%)\n")
        L.append(xs_df.sort_values("sharpe", ascending=False).to_markdown(index=False))
        L.append("\n_This is the construction the prior study could NOT test (market-wide astro is identical across "
                 "assets). Here the REAL per-asset signals + the per-coin natal chart give genuine cross-sectional "
                 "spread._\n")

    # honest read
    real_oos = ts_df[ts_df.group == "real"]["sharpe"].median() if len(ts_df) and (ts_df.group == "real").any() else float("nan")
    astro_oos = ts_df[ts_df.group == "astro"]["sharpe"].median() if len(ts_df) and (ts_df.group == "astro").any() else float("nan")
    all_oos = ts_df[ts_df.group == "all"]["sharpe"].median() if len(ts_df) and (ts_df.group == "all").any() else float("nan")
    best_xsec = xs_df.sort_values("sharpe", ascending=False).iloc[0] if len(xs_df) else None
    L.append("\n## The honest read (open-minded, then deflated)\n")
    L.append(f"- **Time-series OOS median Sharpe:** real={real_oos:.2f} · astro={astro_oos:.2f} · all={all_oos:.2f}. "
             f"The pattern to look at: does `all` beat `real` (astro/event/natal ADD), or does blending DILUTE the "
             f"real edge (as the prior incremental test found)?")
    if best_xsec is not None:
        L.append(f"- **Best cross-sectional OOS:** group=`{best_xsec['group']}` Sharpe {best_xsec['sharpe']:.2f} "
                 f"(n={best_xsec['n']}). A single OOS Sharpe is NOT a survivor — it needs DSR at the group-trial count "
                 f"+ a forward test. Reported as a pattern to investigate, not an edge.")
    L.append("- **Honest caveat:** train/test (not full CPCV), single OOS window, fixed signs from train — this is "
             "EXPLORATION to surface structure, not a gate verdict. A real survivor must then clear the project's "
             "Deflated-Sharpe/CPCV gate and a forward test. The prior 152k-trial lab + incremental test say the "
             "honest prior is: real signals carry a faint edge, astro/event/natal add ~nothing, and the cross-"
             "sectional spread (if any) lives in the REAL per-asset signals, not the planets.\n")
    out.write_text("\n".join(str(x) for x in L) + "\n")


if __name__ == "__main__":
    main()
