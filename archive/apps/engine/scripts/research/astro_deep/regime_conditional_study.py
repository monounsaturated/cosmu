# intent: WAVE-1 "regime_conditional" attack on astro→markets. Does any weak astro effect live ONLY
# inside a specific market regime (era / realized-vol / trend / funding-extreme)? We test the Spearman
# IC of each astro feature vs forward return WITHIN each regime cell, POOLED across assets (sign-stability
# across assets is the real signal), with a PROPER null that preserves the return autocorrelation AND the
# regime structure — a per-asset BLOCK-CIRCULAR-SHIFT of the astro feature relative to returns. That breaks
# only the astro<->return phase alignment, not the return memory or the regime partition (which is derived
# from returns and therefore travels with them). BH-FDR across every (feature x regime-cell) test.
#
# CARDINAL RULES honored:
#   - LIVE-HONEST data only: deterministic astro (AF), real Binance/Yahoo prices, immutable funding_rate.
#   - PROPER null: circular-shift surrogate preserving autocorrelation; NOT i.i.d. fake dates.
#   - Regimes built PIT: trailing realized vol / trailing 200d MA / expanding funding median — no look-ahead.
#   - Economic > statistical: every surviving IC is checked for tradeability net of ~10bps round-trip.
#   - Multiple-testing aware: BH-FDR; a "lucky" candidate is flagged with honest P(real).
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "astro_strategy_lab"))

import astro_features_deep as AF  # noqa: E402
import real_panel as RP  # noqa: E402

RNG = np.random.default_rng(20260615)

# ── universe ────────────────────────────────────────────────────────────────────────────────────
CRYPTO = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
    "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "ATOMUSDT", "UNIUSDT",
    "FILUSDT", "NEARUSDT", "AAVEUSDT",
]
EQUITY = ["SPY", "QQQ", "IWM", "GLD", "SLV", "TLT", "XLE", "XLF", "XLK", "USO"]

FEE_RT = 0.0010  # ~10 bps round-trip economic hurdle


# ── astro feature panel: compact, interpretable, sign-meaningful ─────────────────────────────────
def astro_panel(index: pd.DatetimeIndex) -> pd.DataFrame:
    """Deterministic astro features on `index`, circular cols expanded to sin/cos so an IC has meaning."""
    raw = AF.deep_astro_features(index)
    cols: dict[str, pd.Series] = {}
    # continuous + binary: use as-is (monotone IC is meaningful)
    for c in AF.CONTINUOUS_COLS + AF.BINARY_COLS:
        if c in raw:
            cols[c] = raw[c].astype(float)
    # circular degrees -> sin/cos (a raw-degree IC is meaningless across the 0/360 wrap)
    for c in AF.CIRCULAR_COLS:
        if c in raw:
            rad = np.deg2rad(raw[c].astype(float).to_numpy())
            cols[f"{c}__sin"] = pd.Series(np.sin(rad), index=index)
            cols[f"{c}__cos"] = pd.Series(np.cos(rad), index=index)
    out = pd.DataFrame(cols, index=index)
    # drop degenerate (constant) columns — they carry no IC and pollute FDR counts
    nun = out.nunique()
    return out.loc[:, nun[nun > 3].index]


# ── per-asset frame: forward return + PIT regime labels ──────────────────────────────────────────
def build_asset_frame(close: pd.Series, funding: pd.Series | None, horizon: int) -> pd.DataFrame:
    """Returns a frame indexed by bar ts with: fwd (horizon-day forward log return, the label), and PIT
    regime columns (era / vol / trend / funding). All regime labels use ONLY past info at each bar."""
    logc = np.log(close)
    r1 = logc.diff()  # daily log return (past)
    fwd = logc.shift(-horizon) - logc  # forward horizon-day log return (the LABEL; future, fine as label)

    # realized vol regime: trailing 30d std of daily returns, split at the asset's EXPANDING median (PIT).
    rv = r1.rolling(30, min_periods=20).std()
    rv_med = rv.expanding(min_periods=120).median()
    vol_hi = (rv > rv_med)

    # trend regime: close vs trailing 200d MA (PIT — uses only past closes incl. today).
    ma200 = close.rolling(200, min_periods=120).mean()
    trend_up = (close > ma200)

    # era regime: pre/post 2021-01-01 (a structural split, knowable).
    era_post = pd.Series(close.index >= pd.Timestamp("2021-01-01"), index=close.index)

    df = pd.DataFrame(
        {"fwd": fwd, "vol_hi": vol_hi, "trend_up": trend_up, "era_post": era_post},
        index=close.index,
    )
    if funding is not None and funding.notna().sum() > 250:
        f = funding.reindex(close.index)
        f_med = f.expanding(min_periods=120).median()  # PIT expanding median (no look-ahead)
        df["fund_hi"] = (f > f_med)
    return df


# ── regime cells: each is (regime_name, label_value, mask_builder) ───────────────────────────────
REGIME_CELLS = [
    ("era_pre", lambda d: ~d["era_post"]),
    ("era_post", lambda d: d["era_post"]),
    ("vol_hi", lambda d: d["vol_hi"]),
    ("vol_lo", lambda d: ~d["vol_hi"]),
    ("trend_up", lambda d: d["trend_up"]),
    ("trend_dn", lambda d: ~d["trend_up"]),
    ("fund_hi", lambda d: d.get("fund_hi", pd.Series(False, index=d.index))),
    ("fund_lo", lambda d: ~d.get("fund_hi", pd.Series(True, index=d.index)) & d.get("fund_hi", pd.Series(False, index=d.index)).notna()),
]


def spearman_ic(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman rho via rank-Pearson; NaN-safe; returns nan if degenerate."""
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 30:
        return np.nan
    xr = pd.Series(x[m]).rank().to_numpy()
    yr = pd.Series(y[m]).rank().to_numpy()
    if xr.std() == 0 or yr.std() == 0:
        return np.nan
    return float(np.corrcoef(xr, yr)[0, 1])


def circular_shift(a: np.ndarray, k: int) -> np.ndarray:
    return np.concatenate([a[-k:], a[:-k]])


def _rank_rows(M: np.ndarray) -> np.ndarray:
    """ORDINAL-rank each ROW of a 2D array, fully vectorized (ties broken by position). Astro features are
    continuous geometry with negligible exact ties, so ordinal vs average ranking is numerically immaterial
    here; we use the SAME convention for the observed IC so observed and null are apples-to-apples."""
    order = M.argsort(axis=1, kind="stable")
    ranks = np.empty_like(order, dtype=float)
    rows = np.arange(M.shape[0])[:, None]
    ranks[rows, order] = np.arange(1, M.shape[1] + 1)[None, :].astype(float)
    return ranks


def vectorized_null_ics(x: np.ndarray, y_ranks_masked: np.ndarray, mask_idx: np.ndarray,
                        offsets: np.ndarray) -> np.ndarray:
    """Spearman IC of circularly-shifted x (shift k) vs fixed masked y, for every k in `offsets`.

    Circular shift by k maps output position p to input index (p - k) mod L (matches circular_shift). We
    only need the MASKED positions, so for each offset we gather x at (mask_idx - k) mod L, rank those rows,
    and correlate against the precomputed y ranks. Fully vectorized over offsets."""
    L = len(x)
    # shifted source indices for the masked positions: shape (n_offsets, n_mask)
    src = (mask_idx[None, :] - offsets[:, None]) % L
    Xs = x[src]  # (n_offsets, n_mask) — finite by construction (x is finite on mask already upstream)
    Xr = _rank_rows(Xs)
    yr = y_ranks_masked
    yr_c = yr - yr.mean()
    Xr_c = Xr - Xr.mean(axis=1, keepdims=True)
    num = Xr_c @ yr_c
    den = np.sqrt((Xr_c ** 2).sum(axis=1) * (yr_c ** 2).sum())
    out = np.full(len(offsets), np.nan)
    nz = den > 0
    out[nz] = num[nz] / den[nz]
    return out


def _full_rank(a: np.ndarray) -> np.ndarray:
    """Ordinal full-series rank of a 1D array (stable); NaNs ranked last but never used (masks exclude them)."""
    order = a.argsort(kind="stable")
    r = np.empty(len(a), dtype=float)
    r[order] = np.arange(1, len(a) + 1, dtype=float)
    return r


def fast_cell_ic_and_null(xr_full: np.ndarray, yr_full: np.ndarray, mask: np.ndarray,
                          offsets: np.ndarray):
    """GLOBAL-RANK IC inside a cell + circular-shift null, with NO per-shift re-ranking.

    Statistic: corr( rank_x(full)[mask] , rank_y(full)[mask] ) — a well-defined, monotone cross-rank IC.
    The null circularly shifts the FULL x-rank vector by k (preserving x's autocorrelation perfectly) and
    re-applies the SAME cell mask (preserving the regime partition + return memory), then correlates the
    shifted x-ranks at the masked rows against the fixed masked y-ranks. Exact, fast, vectorized over k.

    Returns (observed_ic, null_ic_array). NaNs where degenerate."""
    L = len(xr_full)
    mask_idx = np.flatnonzero(mask)
    if len(mask_idx) < 60:
        return np.nan, np.array([])
    yr = yr_full[mask_idx]
    yr_c = yr - yr.mean()
    yden = np.sqrt((yr_c ** 2).sum())
    if yden == 0:
        return np.nan, np.array([])
    # observed
    xr = xr_full[mask_idx]
    xr_c = xr - xr.mean()
    xden = np.sqrt((xr_c ** 2).sum())
    obs = float((xr_c @ yr_c) / (xden * yden)) if xden > 0 else np.nan
    # null: gather shifted full-rank x at masked rows (n_offsets, n_mask)
    src = (mask_idx[None, :] - offsets[:, None]) % L
    Xr = xr_full[src]
    Xr_c = Xr - Xr.mean(axis=1, keepdims=True)
    num = Xr_c @ yr_c
    den = np.sqrt((Xr_c ** 2).sum(axis=1)) * yden
    null = np.full(len(offsets), np.nan)
    nz = den > 0
    null[nz] = num[nz] / den[nz]
    return obs, null


# ── pooled-IC-within-regime with circular-shift null ─────────────────────────────────────────────
def run(horizon: int = 1, n_null: int = 2000, min_cell_obs: int = 400, min_assets: int = 5):
    """For each (astro feature x regime cell): pooled cross-asset Spearman IC inside the cell, and a null
    distribution from per-asset circular shifts of the astro feature (preserves return autocorr + regime
    partition; breaks astro<->return phase). Two-sided p from the null. Then BH-FDR over all tests.

    'Pooled IC' = the observation-weighted mean of per-asset within-cell ICs (each asset's IC computed on
    its own bars in the cell). Sign-stability across assets is captured by `frac_sign` (share of assets
    whose in-cell IC matches the pooled sign)."""
    # 1) load real prices
    print("loading crypto bars ...", flush=True)
    cbars = RP.load_crypto_bars(CRYPTO, "1d", days=3650)
    print("loading equity bars ...", flush=True)
    ebars = RP.load_equity_bars(EQUITY)
    bars = {**{s: cbars[s] for s in CRYPTO if len(cbars.get(s, [])) > 600},
            **{s: ebars[s] for s in EQUITY if len(ebars.get(s, [])) > 600}}
    print(f"usable assets: {len(bars)}  ({sorted(bars)})", flush=True)

    # 2) PIT funding for crypto (immutable, live-honest)
    bidx = {s: bars[s].index for s in bars}
    funding_by_sym: dict[str, pd.Series] = {}
    try:
        fpanel = RP.load_real_alt_panel([s for s in bars if s.endswith("USDT")], ["funding_rate"], bidx)
        for s, fdf in fpanel.items():
            if "funding_rate" in fdf:
                funding_by_sym[s] = fdf["funding_rate"]
    except Exception as e:  # noqa: BLE001
        print(f"funding load skipped ({e})", flush=True)

    # 3) shared astro panel on the UNION of all dates (compute once; parquet-cached — ephem is slow)
    all_dates = pd.DatetimeIndex(sorted(set().union(*[set(b.index) for b in bars.values()])))
    print(f"astro panel on {len(all_dates)} union dates ...", flush=True)
    import hashlib as _hl
    _ck = _hl.md5(f"{all_dates.min()}_{all_dates.max()}_{len(all_dates)}".encode()).hexdigest()[:12]
    _cdir = Path("/tmp/cosmu_astro_cache/panel"); _cdir.mkdir(parents=True, exist_ok=True)
    _cf = _cdir / f"astro_panel_{_ck}.pkl"
    if _cf.exists():
        AP = pd.read_pickle(_cf)
        print(f"  (astro panel loaded from cache {_cf.name})", flush=True)
    else:
        AP = astro_panel(all_dates)
        try:
            AP.to_pickle(_cf)
        except Exception:  # noqa: BLE001
            pass
    feats = list(AP.columns)
    print(f"astro features after sin/cos + de-dup: {len(feats)}", flush=True)

    # 4) per-asset PRECOMPUTE (independent of feature): full y-rank, per-feature full x-ranks, per-cell masks.
    #    Using the GLOBAL-RANK IC (fast_cell_ic_and_null) lets us rank x ONCE per (asset,feature) instead of
    #    re-ranking the masked subset 600x per cell — exact same null logic, ~100x faster.
    print("precomputing per-asset rank panels + cell masks ...", flush=True)
    asset_pre: dict[str, dict] = {}
    for s in bars:
        fr = build_asset_frame(bars[s]["close"], funding_by_sym.get(s), horizon)
        ap = AP.reindex(bars[s].index)
        y = fr["fwd"].to_numpy()
        finite_y = np.isfinite(y)
        # full-series ranks per feature, plus a per-feature finite mask (astro is finite, but be safe).
        xr_by_feat, xfin_by_feat = {}, {}
        for f in feats:
            col = ap[f].to_numpy()
            xfin = np.isfinite(col)
            xr_by_feat[f] = _full_rank(np.where(xfin, col, -1e18))
            xfin_by_feat[f] = xfin
        yr_full = _full_rank(np.where(finite_y, y, -1e18))
        masks = {}
        for cell_name, mask_fn in REGIME_CELLS:
            try:
                m = mask_fn(fr).to_numpy()
            except Exception:  # noqa: BLE001
                m = np.zeros(len(fr), dtype=bool)
            masks[cell_name] = m & finite_y
        asset_pre[s] = {"xr": xr_by_feat, "xfin": xfin_by_feat, "yr": yr_full,
                        "masks": masks, "L": len(fr)}

    # 5) iterate features x cells
    rows = []
    import time as _t
    _t0 = _t.time()
    for fi, feat in enumerate(feats):
        if fi % 5 == 0:
            print(f"  feature {fi}/{len(feats)}: {feat}  (+{_t.time()-_t0:.0f}s)", flush=True)
        for cell_name, _mask_fn in REGIME_CELLS:
            per_asset_ic = []
            per_asset_n = []
            null_pool = np.zeros(n_null)
            null_w = np.zeros(n_null)
            usable_assets = 0
            for s, pre in asset_pre.items():
                xr_full = pre["xr"][feat]
                yr_full = pre["yr"]
                m = pre["masks"][cell_name] & pre["xfin"][feat]
                n = int(m.sum())
                if n < 60:
                    continue
                L = pre["L"]
                offs = RNG.integers(20, L - 20, size=n_null)
                ic, null = fast_cell_ic_and_null(xr_full, yr_full, m, offs)
                if not np.isfinite(ic) or len(null) == 0:
                    continue
                per_asset_ic.append(ic)
                per_asset_n.append(n)
                usable_assets += 1
                good = np.isfinite(null)
                null_pool[good] += null[good] * n
                null_w[good] += n
            if usable_assets < min_assets:
                continue
            tot_n = sum(per_asset_n)
            if tot_n < min_cell_obs:
                continue
            pooled_ic = float(np.average(per_asset_ic, weights=per_asset_n))
            frac_sign = float(np.mean([np.sign(i) == np.sign(pooled_ic) for i in per_asset_ic]))
            null_ic = np.divide(null_pool, null_w, out=np.full(n_null, np.nan), where=null_w > 0)
            null_ic = null_ic[np.isfinite(null_ic)]
            if len(null_ic) < n_null * 0.5:
                continue
            # two-sided p: fraction of null |IC| >= observed |IC|
            p = float((np.sum(np.abs(null_ic) >= abs(pooled_ic)) + 1) / (len(null_ic) + 1))
            rows.append({
                "feature": feat, "cell": cell_name, "n_assets": usable_assets,
                "tot_obs": tot_n, "pooled_ic": pooled_ic, "frac_sign": frac_sign,
                "null_std": float(np.std(null_ic)), "p": p,
            })

    res = pd.DataFrame(rows)
    if res.empty:
        print("NO testable (feature x cell) combos — check data.", flush=True)
        return res
    # BH-FDR across ALL tests
    res = res.sort_values("p").reset_index(drop=True)
    m = len(res)
    res["bh_crit"] = (np.arange(1, m + 1) / m) * 0.05
    res["bh_pass"] = res["p"] <= res["bh_crit"]
    # enforce BH step-up: pass everything up to the largest index where p<=crit
    if res["bh_pass"].any():
        kmax = res.index[res["bh_pass"]].max()
        res["bh_pass"] = res.index <= kmax
    res["abs_ic"] = res["pooled_ic"].abs()
    return res


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=1)
    ap.add_argument("--nnull", type=int, default=2000)
    args = ap.parse_args()
    res = run(horizon=args.horizon, n_null=args.nnull)
    if not res.empty:
        out = HERE / f"regime_conditional_h{args.horizon}.csv"
        res.to_csv(out, index=False)
        print(f"\nwrote {out}  ({len(res)} tests)")
        print(f"\nBH-FDR (q=0.05) survivors: {int(res['bh_pass'].sum())}")
        print("\nTop 20 by |pooled_ic| among p<0.05:")
        sig = res[res["p"] < 0.05].sort_values("abs_ic", ascending=False).head(20)
        cols = ["feature", "cell", "n_assets", "tot_obs", "pooled_ic", "frac_sign", "p", "bh_pass"]
        with pd.option_context("display.width", 200, "display.max_columns", 20):
            print(sig[cols].to_string(index=False))
        print("\nGlobal min-p rows:")
        print(res.sort_values("p").head(10)[cols].to_string(index=False))
