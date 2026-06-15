#!/usr/bin/env python3
# intent: the ASTRO STRATEGY LAB — a LARGE, isolated, labeled, HONEST search. It enumerates THOUSANDS of distinct
# astrology strategy configs (school × body × feature × transform × mechanic × holding-period × polarity), backtests
# each across many assets/segments (crypto big/mid/low-cap + equities + indexes) net of fees, SAVES every trial to R2
# (durable) + local (mirror) so no effort is lost, and reports BOTH the raw best (no gate — "astro's best face") AND
# the Deflated-Sharpe verdict at the TRUE trial count (the honest answer). It writes NOTHING to prod alt_data or the
# Gate ledger — a separate 'astro_lab' namespace, so the deep search cannot contaminate the money path.
#
# Efficiency: deterministic astro features are MARKET-WIDE (same value for every asset at date t), so one config →
# ONE point-in-time position series → applied to each asset's returns. Thousands of configs is a fast vectorized op;
# Modal is reserved for the heavy permutation/deflation stage (run_lab_modal.py).
#
# NO FABRICATION. Real prices (Binance/Yahoo). Deterministic astro geometry. PIT throughout (trade t→t+1 on the
# position known at t; all transforms trailing-only). Expected outcome: the best-of-thousands dies after deflation.

from __future__ import annotations

import argparse
import hashlib
import itertools
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

import astro_deep_study as S  # noqa: E402  (reuse the proven feature panel + loaders)
import astro_features_deep as AF  # noqa: E402
import ml_harness as ML  # noqa: E402
import real_panel as RP  # noqa: E402
from lab_store import LabStore  # noqa: E402

# ── asset segments (class × cap/liquidity bucket) ────────────────────────────────────────────────
SEGMENTS: dict[str, list[str]] = {
    "crypto_large": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"],
    "crypto_mid": ["ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "ATOMUSDT", "UNIUSDT"],
    "crypto_small": ["FILUSDT", "NEARUSDT", "AAVEUSDT", "INJUSDT", "SUIUSDT", "SEIUSDT", "TIAUSDT", "GALAUSDT", "RUNEUSDT", "ICPUSDT"],
    "equity_index": ["SPY", "QQQ", "DIA", "IWM"],
    "equity_sector": ["XLE", "XLF", "XLK"],
    "commodity_fx": ["GLD", "SLV", "USO", "TLT", "EEM"],
}


def all_symbols(segments: list[str]) -> tuple[list[str], list[str]]:
    crypto, equity = [], []
    for seg in segments:
        for s in SEGMENTS[seg]:
            (crypto if s.endswith("USDT") else equity).append(s)
    return crypto, equity


# ── PIT signal transforms (trailing-only; trade t→t+1) ───────────────────────────────────────────
def _trailing_z(x: np.ndarray, win: int = 90) -> np.ndarray:
    s = pd.Series(x)
    return ((s - s.rolling(win, min_periods=20).mean()) / s.rolling(win, min_periods=20).std()).to_numpy()


def _trailing_median_demean(x: np.ndarray, win: int = 252) -> np.ndarray:
    return x - pd.Series(x).rolling(win, min_periods=60).median().to_numpy()


def _hold(pos: np.ndarray, h: int) -> np.ndarray:
    """Persist a triggered position for h bars (forward-fill the last nonzero up to h bars)."""
    if h <= 1:
        return pos
    out = pos.astype(float).copy()
    last_i, last_v = -10**9, 0.0
    for i in range(len(out)):
        if out[i] != 0 and not np.isnan(out[i]):
            last_i, last_v = i, out[i]
        elif i - last_i < h:
            out[i] = last_v
    return out


def position_series(cfg: dict, panel: pd.DataFrame) -> np.ndarray:
    """Map a config → a PIT market-wide position in {-1,0,+1} per date (NaN where undefined)."""
    f = panel[cfg["feature"]].to_numpy(float)
    pol = cfg["polarity"]
    t = cfg["transform"]
    if t == "z_sign":
        pos = np.sign(_trailing_z(f, cfg.get("win", 90)))
    elif t == "median_sign":
        pos = np.sign(_trailing_median_demean(f, cfg.get("win", 252)))
    elif t == "sin":
        pos = np.sign(np.sin(np.radians(f)))
    elif t == "cos":
        pos = np.sign(np.cos(np.radians(f)))
    elif t == "change_sign":
        pos = np.sign(np.concatenate([[0.0], np.diff(f)]))
    elif t == "z_thresh":  # long only above +q std, short below -q
        z = _trailing_z(f, cfg.get("win", 90)); q = cfg.get("q", 1.0)
        pos = np.where(z > q, 1.0, np.where(z < -q, -1.0, 0.0))
    elif t == "flag_event":  # binary flag → take a position for `hold` bars on each firing
        pos = np.where(f > 0.5, 1.0, 0.0)
    elif t == "cat_level":  # categorical: position when feature == a specific level (e.g. Mars in Scorpio)
        pos = np.where(np.round(f) == cfg["level"], 1.0, 0.0)
    else:
        pos = np.zeros_like(f)
    pos = pol * _hold(pos, cfg.get("hold", 1))
    return pos


# ── config enumeration (thousands, named + labeled by school/type) ───────────────────────────────
def enumerate_configs(panel: pd.DataFrame, *, cap: int | None = None) -> list[dict]:
    cont = [c for c in AF.CONTINUOUS_COLS if c in panel]
    circ = [c for c in AF.CIRCULAR_COLS if c in panel]
    binr = [c for c in AF.BINARY_COLS if c in panel] + S.CAL_BIN
    catg = [c for c in AF.CATEGORICAL_COLS if c in panel] + S.CAL_CAT
    extra = [c for c in panel.columns if c in {n[5:] for n in dir(__import__("extra_signals")) if n.startswith("feat_")}]
    sw = [c for c in S.SPACE_WEATHER if c in panel]
    cfgs: list[dict] = []

    def add(school, feature, transform, **kw):
        base = dict(school=school, feature=feature, transform=transform, **kw)
        base["config_id"] = hashlib.md5(repr(sorted(base.items())).encode()).hexdigest()[:12]
        cfgs.append(base)

    HOLDS = (1, 3, 5, 10, 20)
    POL = (1, -1)
    # continuous longitudes/speeds/declination/aspect-counts/harmonics/lunar mechanics + space weather + financial-astro
    for feat in cont + extra + sw:
        for tr in ("z_sign", "median_sign", "change_sign"):
            for h in HOLDS:
                for p in POL:
                    add("western_continuous", feat, tr, hold=h, polarity=p)
        for q in (0.5, 1.0, 1.5):
            for h in (3, 5, 10):
                for p in POL:
                    add("western_threshold", feat, "z_thresh", q=q, hold=h, polarity=p)
    # circular longitudes via sin/cos harmonics (the classic "planet at degree" cyclical)
    for feat in circ:
        for tr in ("sin", "cos"):
            for h in HOLDS:
                for p in POL:
                    add("harmonic_cyclical", feat, tr, hold=h, polarity=p)
    # binary EVENTS (retrograde/OOB/eclipse-window/near-new/near-full/ingress/mars-saturn) → event-window trades
    for feat in binr:
        for h in (1, 3, 5, 10, 20):
            for p in POL:
                add("event_window", feat, "flag_event", hold=h, polarity=p)
    # categorical "planet in sign/phase/element/modality == specific level" (the deep per-setting test)
    for feat in catg:
        vals = np.unique(np.round(panel[feat].to_numpy(float)))
        vals = vals[np.isfinite(vals)]
        for lvl in vals:
            for h in (3, 5, 10):
                for p in POL:
                    add("sign_placement", feat, "cat_level", level=int(lvl), hold=h, polarity=p)
    # de-dup by config_id, optional cap (stable order)
    seen, uniq = set(), []
    for c in cfgs:
        if c["config_id"] not in seen:
            seen.add(c["config_id"]); uniq.append(c)
    return uniq[:cap] if cap else uniq


# ── vectorized backtest of one config across all assets ──────────────────────────────────────────
def backtest_config(cfg: dict, panel: pd.DataFrame, ret_panel: pd.DataFrame, *, fee_bps: float = 10.0) -> list[dict]:
    pos = position_series(cfg, panel)  # market-wide position over panel.index
    pos = pd.Series(pos, index=panel.index)
    rows = []
    for asset in ret_panel.columns:
        r = ret_panel[asset]
        idx = r.dropna().index
        if len(idx) < 250:
            continue
        p = pos.reindex(idx).to_numpy(float)
        rr = r.reindex(idx).to_numpy(float)
        p_act = p[:-1]  # act on signal known at t, earn t→t+1
        pnl = np.nan_to_num(p_act) * rr[1:]
        turn = np.abs(np.diff(np.concatenate([[0.0], np.nan_to_num(p_act)])))
        pnl = pnl - turn * (fee_bps / 1e4)
        pnl = pnl[np.isfinite(pnl)]
        if len(pnl) < 200 or np.std(pnl) == 0:
            continue
        sr_bar = float(np.mean(pnl) / np.std(pnl))
        ann = "365" if asset.endswith("USDT") else "252"
        sharpe = sr_bar * np.sqrt(int(ann))
        rows.append(dict(
            config_id=cfg["config_id"], school=cfg["school"], feature=cfg["feature"], transform=cfg["transform"],
            hold=cfg.get("hold", 1), polarity=cfg.get("polarity", 1), level=cfg.get("level", -1), q=cfg.get("q", -1),
            asset=asset, n=int(len(pnl)), n_trades=int((turn > 0).sum()), sharpe=sharpe,
            net_return=float(np.exp(np.sum(pnl)) - 1), avg_pos=float(np.nanmean(np.abs(p_act))),
        ))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--segments", default="all", help="comma list of segment keys, or 'all'")
    ap.add_argument("--cap-configs", type=int, default=4000)
    ap.add_argument("--batch", type=int, default=500, help="configs per saved batch (checkpoint granularity)")
    ap.add_argument("--out", default=str(ENGINE_ROOT.parent.parent / "docs/research/astro_strategy_lab.md"))
    args = ap.parse_args()

    segs = list(SEGMENTS) if args.segments == "all" else args.segments.split(",")
    crypto, equity = all_symbols(segs)
    print(f"[1/5] REAL prices · segments={segs} · {len(crypto)} crypto + {len(equity)} equity", flush=True)
    bars = RP.load_crypto_bars(crypto, "1d", days=3650)
    bars.update(RP.load_equity_bars(equity))
    bars = {s: b for s, b in bars.items() if len(b) >= 500}
    sym_seg = {s: seg for seg in segs for s in SEGMENTS[seg] if s in bars}

    print("[2/5] Deterministic astro feature panel (market-wide) …", flush=True)
    dates = pd.DatetimeIndex(sorted({d for b in bars.values() for d in b.index}))
    panel = AF.deep_astro_features(dates).join(S.calendar_features(dates))
    ex = S._extra_feats(dates); ex = ex[[c for c in ex.columns if c not in panel.columns]]
    panel = panel.join(ex)
    sw = S.load_spaceweather(dates); sw = sw[[c for c in sw.columns if c not in panel.columns]]
    panel = panel.join(sw)
    ret_panel = pd.DataFrame({s: np.log(b["close"]).diff() for s, b in bars.items()}).reindex(dates)
    print(f"   panel {panel.shape} · returns {ret_panel.shape}", flush=True)

    print(f"[3/5] Enumerating configs (cap {args.cap_configs}) …", flush=True)
    configs = enumerate_configs(panel, cap=args.cap_configs)
    print(f"   {len(configs)} distinct labeled configs across schools: "
          f"{dict(pd.Series([c['school'] for c in configs]).value_counts())}", flush=True)

    import time
    import uuid
    run_id = f"run_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    store = LabStore()
    print(f"[4/5] Backtesting {len(configs)} configs × {len(bars)} assets · run_id={run_id} · "
          f"r2_ready={store.r2_ready} · checkpointing …", flush=True)
    batch_rows: list[dict] = []
    bnum = total = 0
    for i, cfg in enumerate(configs):
        rows = backtest_config(cfg, panel, ret_panel)
        for r in rows:
            r["segment"] = sym_seg.get(r["asset"], "?")
        batch_rows.extend(rows)
        if len(batch_rows) >= args.batch * 8 or i == len(configs) - 1:
            if batch_rows:
                df = pd.DataFrame(batch_rows)
                store.save_batch(df, f"{run_id}/batch_{bnum:04d}")
                total += len(df)
                print(f"   checkpoint {run_id}/batch_{bnum:04d}: {len(df)} rows (total {total}) → R2+local", flush=True)
                bnum += 1
                batch_rows = []

    print(f"[5/5] Aggregating {total} trials from the durable store (RAM-bounded) + DEFLATING …", flush=True)
    df_all = store.read_run(run_id)
    report(args.out, df_all, n_trials=len(configs), segs=segs, n_assets=len(bars))
    print(f"\nDONE → {args.out}  ·  {total} trials saved to r2://{store.bucket}/astro_lab/{run_id}/", flush=True)


def report(path, df: pd.DataFrame, *, n_trials: int, segs, n_assets) -> None:
    out = Path(path); out.parent.mkdir(parents=True, exist_ok=True)
    if df.empty:
        out.write_text("# Astro strategy lab — no trials produced\n"); return
    # Deflated Sharpe charges for ALL (config × asset) trials run — the honest denominator
    N = int(len(df))
    df = df.copy()
    df["dsr"] = [ML.deflated_sharpe(s / np.sqrt(252 if not a.endswith("USDT") else 365), N,
                                    int(n), 0.0, 3.0) for s, n, a in zip(df["sharpe"], df["n"], df["asset"])]
    best_raw = df.sort_values("sharpe", ascending=False).head(20)
    survivors = df[(df["dsr"] > 0.95)]
    L = ["# Astro strategy lab — large honest search\n",
         f"_Isolated, labeled `astro_lab` namespace (never touches prod alt_data / Gate). {n_trials} distinct configs × "
         f"{n_assets} assets = **{N} backtested trials**, all saved to R2 `cosmu-lake/astro_lab/` + local mirror. "
         f"Real prices, deterministic astro, PIT. Generated by `scripts/research/astro_strategy_lab/run_lab.py`._\n",
         f"## Verdict\n",
         f"- **Raw best (NO gate — astro's best face):** Sharpe **{best_raw['sharpe'].iloc[0]:.2f}** "
         f"({best_raw['feature'].iloc[0]}/{best_raw['transform'].iloc[0]} on {best_raw['asset'].iloc[0]}).",
         f"- **After Deflated Sharpe at the true {N:,}-trial count:** **{len(survivors)} survive DSR>0.95.** "
         f"{'⚠️ INVESTIGATE — paper required.' if len(survivors) else 'None — the search is noise (the gate working).'}",
         f"- Trials by segment: {dict(df['segment'].value_counts())}\n",
         "## Raw best 20 (pre-deflation — read skeptically; this is what p-hacking would 'find')\n",
         best_raw[["school", "feature", "transform", "hold", "polarity", "asset", "segment", "n", "n_trades", "sharpe", "net_return", "dsr"]].to_markdown(index=False),
         "\n## Best by school (raw Sharpe) — every school's strongest, with its deflated probability\n",
         df.sort_values("sharpe", ascending=False).groupby("school").head(1)[["school", "feature", "transform", "asset", "sharpe", "dsr"]].to_markdown(index=False),
         "\n## Honest note\n",
         "With N trials, the expected best raw Sharpe under PURE NOISE is ~`sqrt(2·ln N)/sqrt(T)` annualized — a large "
         "number by construction. The Deflated Sharpe charges for exactly that selection; a config only matters if "
         "DSR>0.95 AND it then survives a forward (out-of-sample) test. Raw Sharpe alone is the false-positive machine.\n"]
    out.write_text("\n".join(str(x) for x in L) + "\n")


if __name__ == "__main__":
    main()
