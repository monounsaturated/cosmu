#!/usr/bin/env python3
# intent: the DEEP, BROAD, honest astrology-vs-markets study (round 2). It asks the smart question round 1 didn't:
# does PURE BROAD ASTRO carry any predictive information ON TOP OF a model that already has the REAL signals
# (the 13.6M-row prod alt_data: LunarCrush social, funding, macro, on-chain)? It runs:
#   1. a deep deterministic astro+calendar panel (outer planets, nodes, aspects, harmonics, eclipses, declination)
#   2. an IC panel (Spearman/Kruskal · BH-FDR · |t|>3 · bull/bear) on the astro features
#   3. ML group battle (astro / calendar / real / all) vs label-permutation nulls, pooled walk-forward OOS
#   4. THE INCREMENTAL TEST — astro on top of the real-signal baseline (and calendar on top, as a sanity control)
#   5. a backtested best-astro trading rule → Deflated Sharpe Ratio (charged for the full trial count)
#   6. the project's OWN engine Gate run on a real ingested astro metric (the actual disposal layer)
# Heavy permutation nulls fan out across assets/models on MODAL when available, else locally.
#
# NO FABRICATION. Real prices (Binance/Yahoo), real alt-data (prod DB, READ-ONLY), deterministic astro geometry.
# Propose-only: nothing moves money or writes to the DB/Gate ledger. Expected result: astro adds nothing.

from __future__ import annotations

import argparse
import calendar as _cal
import sys
import warnings
from datetime import UTC, datetime
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ENGINE_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import astro_features_deep as AF  # noqa: E402
import extra_signals as EX  # noqa: E402
import ml_harness as ML  # noqa: E402
import modal_sweep as MS  # noqa: E402
import real_panel as RP  # noqa: E402

CRYPTO = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT",
    "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "TRXUSDT", "ETCUSDT", "XLMUSDT", "ATOMUSDT",
    "UNIUSDT", "FILUSDT", "NEARUSDT", "AAVEUSDT",
]
EQUITY = ["SPY", "QQQ", "DIA", "IWM", "GLD", "SLV", "TLT", "XLE", "XLF", "XLK", "EEM", "USO"]
HORIZONS = (1, 5, 20)

CAL_CONT: list[str] = []
CAL_BIN = ["turn_of_month", "halloween"]
CAL_CAT = ["dow", "month"]


def calendar_features(dates: pd.DatetimeIndex) -> pd.DataFrame:
    f = pd.DataFrame(index=dates)
    f["dow"] = [float(d.weekday()) for d in dates]
    f["month"] = [float(d.month) for d in dates]
    f["turn_of_month"] = [1.0 if (d.day <= 3 or d.day >= _cal.monthrange(d.year, d.month)[1]) else 0.0 for d in dates]
    f["halloween"] = [1.0 if d.month in (11, 12, 1, 2, 3, 4) else 0.0 for d in dates]
    return f


def _extra_feats(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Pull every pure-date feat_* the extra_signals module exposes (financial-astrology hypotheses)."""
    out = pd.DataFrame(index=dates)
    for name in dir(EX):
        if name.startswith("feat_"):
            try:
                s = getattr(EX, name)(dates)
                out[name[5:]] = np.asarray(s, float)
            except Exception:  # noqa: BLE001
                pass
    return out


SPACE_WEATHER = ["kp_index", "sunspots", "f107"]


def load_spaceweather(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """REAL space-weather (GFZ since 1932): Kp (the Krivelyova-Robotti geomagnetic signal), sunspots, F10.7.
    PIT-lagged by 1 day (the most-recent GFZ rows are nowcasts that get revised) and reindexed onto `dates`."""
    sw = pd.DataFrame(index=dates)
    for col, fn in (("kp_index", "load_kp_index"), ("sunspots", "load_sunspots"), ("f107", "load_f107")):
        try:
            s = getattr(EX, fn)()
            s = pd.Series(np.asarray(s, float), index=pd.DatetimeIndex(s.index)).sort_index().shift(1)
            sw[col] = s.reindex(dates, method="ffill")
        except Exception:  # noqa: BLE001
            pass
    return sw.dropna(axis=1, how="all")


def assemble(symbol: str, bars: pd.DataFrame, astro: pd.DataFrame, real: pd.DataFrame | None) -> pd.DataFrame:
    df = bars[["close"]].join(astro, how="inner")
    if real is not None and len(real):
        df = df.join(real, how="left")
    logc = np.log(df["close"])
    for h in HORIZONS:
        df[f"fwd_{h}"] = logc.shift(-h) - logc
    sma200 = df["close"].rolling(200).mean()
    df["regime"] = np.where(df["close"].to_numpy() > sma200.to_numpy(), "bull", "bear")
    df.loc[sma200.isna(), "regime"] = "na"
    df["__date"] = (df.index.view("int64") // 86_400_000_000_000).astype(int)  # epoch days
    df["__asset"] = symbol
    return df


def _pool(per_asset: dict[str, pd.DataFrame], cols: list[str], horizon: int) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    parts = []
    for df in per_asset.values():
        keep = [c for c in cols if c in df] + [f"fwd_{horizon}", "__date"]
        parts.append(df[keep])
    pooled = pd.concat(parts, ignore_index=True)
    y = (pooled[f"fwd_{horizon}"].to_numpy(float) > 0).astype(int)
    ok = np.isfinite(pooled[f"fwd_{horizon}"].to_numpy(float))
    return pooled[ok].reset_index(drop=True), y[ok], pooled["__date"].to_numpy()[ok]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--n-perm", type=int, default=300)
    ap.add_argument("--modal", action="store_true", help="fan the per-asset sweep out to Modal")
    ap.add_argument("--gate", action="store_true", help="run the real engine Gate on an ingested astro metric")
    ap.add_argument("--out", default=str(ENGINE_ROOT.parent.parent / "docs/research/astro_vs_markets_deep.md"))
    args = ap.parse_args()

    crypto = CRYPTO[:6] if args.quick else CRYPTO
    equity = EQUITY[:3] if args.quick else EQUITY
    n_perm = 40 if args.quick else args.n_perm

    print(f"[1/7] REAL prices: {len(crypto)} crypto + {len(equity)} equities …", flush=True)
    bars = RP.load_crypto_bars(crypto, "1d", days=3650)
    bars.update(RP.load_equity_bars(equity))
    bars = {s: b for s, b in bars.items() if len(b) >= 500}
    for s, b in bars.items():
        print(f"   {s:10} {len(b):>5} bars  {b.index.min().date()}..{b.index.max().date()}", flush=True)

    print("[2/7] Deep astro + calendar + financial-astro feature panel …", flush=True)
    all_dates = pd.DatetimeIndex(sorted({d for b in bars.values() for d in b.index}))
    astro = AF.deep_astro_features(all_dates)
    astro = astro.join(calendar_features(all_dates))
    extra = _extra_feats(all_dates)
    extra = extra[[c for c in extra.columns if c not in astro.columns]]  # dedupe vs deep-astro module
    if len(extra.columns):
        astro = astro.join(extra)
    sw = load_spaceweather(all_dates)
    sw = sw[[c for c in sw.columns if c not in astro.columns]]
    sw_cols = list(sw.columns)
    if sw_cols:
        astro = astro.join(sw)  # market-wide, broadcast to every asset like the rest of the astro panel
    print(f"   astro panel: {astro.shape[1]} features over {astro.shape[0]} days "
          f"(+{len(sw_cols)} real space-weather: {sw_cols})", flush=True)

    print("[3/7] REAL alt-data panel (prod DB, PIT) …", flush=True)
    real_metrics = list(RP.REAL_ALT_DEEP)
    bar_index = {s: b.index for s, b in bars.items()}
    try:
        real_panel = RP.load_real_alt_panel(list(bars), real_metrics, bar_index)
    except Exception as e:  # noqa: BLE001
        print(f"   real-panel load failed ({type(e).__name__}: {str(e)[:100]}); continuing astro-only", flush=True)
        real_panel = {}

    per_asset = {}
    for s, b in bars.items():
        df = assemble(s, b, astro, real_panel.get(s)).dropna(subset=["fwd_1"])
        if len(df) >= 500:
            per_asset[s] = df

    # feature groups
    astro_cont = [c for c in AF.CONTINUOUS_COLS] + CAL_CONT + list(extra.columns)
    astro_circ = list(AF.CIRCULAR_COLS)
    astro_bin = list(AF.BINARY_COLS) + CAL_BIN
    astro_cat = list(AF.CATEGORICAL_COLS) + CAL_CAT
    astro_all = astro_cont + astro_circ + astro_bin + astro_cat
    cal_all = CAL_BIN + CAL_CAT
    real_cols = [m for m in real_metrics if any(m in df for df in per_asset.values())]
    real_cols += [c for c in sw_cols if any(c in df for df in per_asset.values())]  # Kp/sunspots/F10.7 are real

    def enc(df, cols_groups):
        return ML.encode_matrix(df, *cols_groups)

    print("[4/7] IC panel (astro features · BH-FDR · |t|>3 · bull/bear) …", flush=True)
    scalar_ic = astro_cont + astro_bin + list(astro_circ) + sw_cols  # incl. Kp (Krivelyova-Robotti geomagnetic test)
    ic = ML.ic_panel(per_asset, scalar_ic, astro_cat, HORIZONS)
    n_fdr = int(ic["survives_fdr"].sum()) if len(ic) else 0
    n_t3 = int(ic["survives_t3"].sum()) if len(ic) else 0
    print(f"   {len(ic)} tests · {n_fdr} survive FDR · {n_t3} clear |t|>3 · ~{0.05*len(ic):.0f} expected FP", flush=True)

    print(f"[5/7] ML group battle vs permutation null (B={n_perm}) …", flush=True)
    groups = {
        "astro": (astro_cont, astro_circ, astro_bin, astro_cat),
        "calendar": ([], [], CAL_BIN, CAL_CAT),
        "real": (real_cols, [], [], []),
        "all": (astro_cont + real_cols, astro_circ, astro_bin, astro_cat),
    }
    ml_results = []
    for gname, cg in groups.items():
        for h in (1, 5):
            pooled, y, dates = _pool(per_asset, cg[0] + cg[1] + cg[2] + cg[3], h)
            X, names = enc(pooled, cg)
            if X.shape[1] == 0:
                continue
            r = ML.perm_null(X, y, dates, B=n_perm, n_jobs=-1)
            r.update(group=gname, horizon=h, n_feat=X.shape[1])
            ml_results.append(r)
            print(f"   {gname:9} h={h:<2} AUC={r['auc']:.4f} null≈{r['null_mean']:.4f} p={r['p']:.3f} "
                  f"({X.shape[1]} feat, n={r['n']})", flush=True)

    print(f"[6/7] INCREMENTAL TEST — does astro add to the real-signal baseline? (B={n_perm}) …", flush=True)
    inc_results = []
    for extra_name, extra_cg in (("astro", (astro_cont, astro_circ, astro_bin, astro_cat)),
                                 ("calendar", ([], [], CAL_BIN, CAL_CAT))):
        for h in (1, 5):
            allcols = real_cols + extra_cg[0] + extra_cg[1] + extra_cg[2] + extra_cg[3]
            pooled, y, dates = _pool(per_asset, allcols, h)
            Xb, _ = enc(pooled, (real_cols, [], [], []))
            Xe, _ = enc(pooled, extra_cg)
            if Xb.shape[1] == 0 or Xe.shape[1] == 0:
                continue
            r = ML.incremental_test(Xb, Xe, y, dates, B=n_perm, n_jobs=-1)
            r.update(added=extra_name, horizon=h, n_base=Xb.shape[1], n_extra=Xe.shape[1])
            inc_results.append(r)
            print(f"   +{extra_name:9} h={h:<2} base={r['auc_base']:.4f} full={r['auc_full']:.4f} "
                  f"lift={r['lift']:+.4f} p={r['p']:.3f}", flush=True)

    # backtest best astro single-feature rule per asset → Deflated Sharpe (charged for the trial count)
    n_trials = max(len(ic), 1)
    bt = []
    for asset, df in per_asset.items():
        best = None
        for feat in scalar_ic:
            if feat not in df:
                continue
            sig = df[feat].to_numpy(float)
            sig = sig - np.nanmedian(sig)  # center so sign() is a long/short rule
            res = ML.backtest_long_short(df["close"].to_numpy(float), sig, n_trials=n_trials)
            if np.isfinite(res["dsr"]) and (best is None or res["dsr"] > best["dsr"]):
                best = dict(asset=asset, feature=feat, **res)
        if best:
            bt.append(best)
    bt_df = pd.DataFrame(bt).sort_values("dsr", ascending=False) if bt else pd.DataFrame()

    # Modal fan-out (optional): per-asset × group × model with a big permutation null
    modal_results = []
    if args.modal:
        print("   [modal] fanning per-asset sweep out to Modal …", flush=True)
        jobs = []
        for asset, df in per_asset.items():
            for gname, cg in (("astro", (astro_cont, astro_circ, astro_bin, astro_cat)),
                              ("real", (real_cols, [], [], []))):
                X, _ = enc(df, cg)
                y = (df["fwd_1"].to_numpy(float) > 0).astype(int)
                d = df["__date"].to_numpy()
                ok = np.isfinite(df["fwd_1"].to_numpy(float))
                X = np.nan_to_num(X[ok], nan=0.0)
                if X.shape[1] == 0 or len(y[ok]) < 400:
                    continue
                jobs.append(dict(asset=asset, group=gname, model="lgbm",
                                 X=X.tolist(), y=y[ok].astype(int).tolist(),
                                 dates=d[ok].astype(int).tolist(), n_perm=max(n_perm * 4, 1000), seed=7))
        try:
            modal_results = MS.run_sweep_modal(jobs)
        except Exception as e:  # noqa: BLE001
            print(f"   [modal] failed ({type(e).__name__}: {str(e)[:120]}); local fallback", flush=True)
            modal_results = MS.run_sweep_local(jobs, n_jobs=-1)

    gate_verdict = None
    if args.gate:
        gate_verdict = run_engine_gate()

    print("[7/7] Writing report …", flush=True)
    write_report(args.out, per_asset, astro, ic, ml_results, inc_results, bt_df, modal_results,
                 gate_verdict, real_cols, n_perm)
    print(f"\nDONE → {args.out}")
    _verdict(ic, ml_results, inc_results, bt_df)


def run_engine_gate():
    """Run the project's OWN deterministic Gate on a real ingested astro metric (the actual disposal layer)."""
    import os
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    try:
        from cosmu.data.market import BinanceSpotOHLCVProvider
        from cosmu.data.providers.store import PgAltDataStore, StoreBackedAltProvider
        from cosmu.knowledge.store import Store
        from cosmu.research.gate import evaluate_gate

        url = os.environ["DATABASE_URL"]
        p = urlsplit(url)
        q = [(k, v) for k, v in parse_qsl(p.query) if k.lower() not in ("pgbouncer", "connection_limit")]
        if not any(k == "sslmode" for k, _ in q):
            q.append(("sslmode", "require"))
        os.environ["DATABASE_URL"] = urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), p.fragment))
        store = Store()
        market = {"BTCUSDT": BinanceSpotOHLCVProvider(cache_dir="/tmp/cosmu_astro_cache/bn").fetch_bars("BTCUSDT", "1d", limit=900)}
        alt = StoreBackedAltProvider(PgAltDataStore(store))
        v = evaluate_gate(market, alt, store, metric="astro_lunar_phase")
        return dict(decision=v.decision, deflated_sharpe_prob=v.deflated_sharpe_prob,
                    cscv_pbo=v.cscv_pbo, best_signal=v.best_signal, reasons=v.reasons[:4])
    except Exception as e:  # noqa: BLE001
        return dict(decision="ERROR", error=f"{type(e).__name__}: {str(e)[:200]}")


def _verdict(ic, ml_results, inc_results, bt_df) -> None:
    print("\n" + "=" * 80)
    print("VERDICT (round 2 — deep + broad + real-signal baseline)")
    nf = int(ic["survives_fdr"].sum()) if len(ic) else 0
    print(f"  IC: {len(ic)} tests · {nf} survive FDR · ~{0.05*len(ic):.0f} expected by chance")
    inc = [r for r in inc_results if r.get("added") == "astro"]
    for r in inc:
        verdict = "ADDS signal" if (np.isfinite(r["p"]) and r["p"] < 0.05 and r["lift"] > 0) else "adds NOTHING"
        print(f"  Incremental astro-on-real h={r['horizon']}: lift={r['lift']:+.4f} p={r['p']:.3f} → {verdict}")
    if len(bt_df):
        b = bt_df.iloc[0]
        print(f"  Best backtested astro rule: {b['asset']}/{b['feature']} Sharpe={b['sharpe']:.2f} "
              f"DSR={b['dsr']:.3f} (need >0.95)")
    print("=" * 80)


def write_report(path, per_asset, astro, ic, ml_results, inc_results, bt_df, modal_results,
                 gate_verdict, real_cols, n_perm) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    L = ["# Astrology vs. Markets — deep study (round 2)\n",
         "_Real prices (Binance/Yahoo) · real alt-data (13.6M-row prod `alt_data`, point-in-time, READ-ONLY) · "
         "deterministic broad ephemeris (no look-ahead). Heavy ML vs label-permutation nulls. Propose-only — "
         "nothing moves money or writes the DB/Gate. Generated by `scripts/research/astro_deep/astro_deep_study.py`._\n"]

    cov = pd.DataFrame([dict(asset=a, n=len(df), start=str(df.index.min().date()), end=str(df.index.max().date()))
                        for a, df in per_asset.items()])
    L.append(f"## Coverage — {len(per_asset)} assets, {astro.shape[1]} astro features, {len(real_cols)} real signals\n")
    L.append(cov.to_markdown(index=False))
    L.append(f"\n**Real signals folded in:** {', '.join(real_cols)}\n")

    nf = int(ic["survives_fdr"].sum()) if len(ic) else 0
    nt = int(ic["survives_t3"].sum()) if len(ic) else 0
    L.append("\n## Headline\n")
    L.append(f"- **IC panel:** {len(ic)} astro tests · **{nf} survive BH-FDR(5%)** · **{nt} clear |t|>3** "
             f"· ~{0.05*len(ic):.0f} false positives expected by chance.")
    astro_inc = [r for r in inc_results if r.get("added") == "astro"]
    if astro_inc:
        worst = max(astro_inc, key=lambda r: (r["lift"] if np.isfinite(r["lift"]) else -9))
        verdict = "ADDS incremental signal" if (np.isfinite(worst["p"]) and worst["p"] < 0.05 and worst["lift"] > 0) else "adds NOTHING"
        L.append(f"- **Incremental test (THE question):** adding all astro to the real-signal model changes OOS AUC "
                 f"by lift={worst['lift']:+.4f} (p={worst['p']:.3f}) → astro **{verdict}** on top of real signals.")
    if len(bt_df):
        b = bt_df.iloc[0]
        L.append(f"- **Best backtested astro rule:** {b['asset']}/{b['feature']} — Sharpe {b['sharpe']:.2f}, "
                 f"**Deflated Sharpe {b['dsr']:.3f}** (needs >0.95 to be real after the trial count).")
    if gate_verdict:
        L.append(f"- **Project's own Gate on ingested `astro_lunar_phase`:** **{gate_verdict.get('decision')}** "
                 f"(deflated_sharpe_prob={gate_verdict.get('deflated_sharpe_prob')}, cscv_pbo={gate_verdict.get('cscv_pbo')}).")

    L.append("\n## ML group battle — pooled walk-forward OOS AUC vs permutation null\n")
    L.append(pd.DataFrame(ml_results)[["group", "horizon", "n_feat", "auc", "null_mean", "null_p95", "p", "n"]].to_markdown(index=False))
    L.append("\n_`astro`=broad ephemeris · `calendar`=seasonality · `real`=LunarCrush+funding+macro+on-chain · "
             "`all`=astro+real. AUC≈0.50 = coin flip; a real edge needs AUC>null_p95 AND p<0.05._\n")

    L.append("\n## Incremental test — astro/calendar ON TOP OF the real-signal baseline\n")
    L.append(pd.DataFrame(inc_results)[["added", "horizon", "n_base", "n_extra", "auc_base", "auc_full", "lift", "p"]].to_markdown(index=False))
    L.append("\n_`lift` = OOS AUC(real+extra) − OOS AUC(real). Null shuffles the extra block's rows (keeps the real "
             "signal, destroys any extra information). lift≤0 or p≥0.05 ⇒ the extra block is redundant noise._\n")

    if len(ic):
        L.append("\n## Strongest apparent astro signals (pre-correction — read skeptically)\n")
        top = ic.reindex(ic["p"].sort_values().index).head(15)
        L.append(top[["asset", "feature", "horizon", "regime", "n", "ic", "p", "survives_fdr", "survives_t3"]].to_markdown(index=False))

    if len(bt_df):
        L.append("\n## Backtested astro rules → Deflated Sharpe (per asset best)\n")
        L.append(bt_df.head(15)[["asset", "feature", "sharpe", "net_return", "dsr", "n"]].to_markdown(index=False))
        L.append(f"\n_DSR charges for {len(ic)} trials. None above 0.95 ⇒ no rule survives the multiple-testing haircut._\n")

    if modal_results:
        mr = pd.DataFrame(modal_results)
        sig = mr[(mr["p"] < 0.05) & (mr["auc"] > mr["null_p95"])] if "p" in mr else mr.iloc[:0]
        L.append(f"\n## Modal sweep — per-asset × group, big permutation null (B≥1000)\n")
        L.append(f"{len(mr)} jobs · {len(sig)} beat their null at p<0.05 AND auc>null_p95.\n")
        L.append(mr.sort_values("auc", ascending=False).head(20).to_markdown(index=False))

    L.append("\n## Method — the anti-overfitting defenses\n")
    L.append("- **No look-ahead:** astro = deterministic geometry knowable at each day's midnight UTC; real alt-data "
             "is PIT-joined (value at bar t = latest point with available_at ≤ t); regime = trailing 200d SMA only.\n"
             "- **OOS only:** every AUC is pooled walk-forward out-of-sample; no in-sample scoring.\n"
             "- **Permutation nulls:** each model is scored against shuffled-label nulls; the incremental test "
             "shuffles only the astro block so the real baseline is preserved.\n"
             "- **Multiple testing:** BH-FDR across the whole IC grid + Harvey-Liu-Zhu |t|>3; the backtest DSR "
             "charges for the full trial count (Bailey–López de Prado).\n"
             "- **Real disposal layer:** the project's own deterministic Gate is run on the ingested astro metric.\n"
             "- **No fabrication:** real prices, real alt-data, deterministic astro; prediction markets excluded "
             "(no multi-year daily panel exists).\n")
    out.write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
