# intent: HONEST test of PHYSICS-grounded solar-system features (SIM / angular momentum / real heliocentric
# J-S / true tides) vs crypto+equity returns AND volatility, under PROPER autocorrelation-preserving nulls.
#
# The cardinal trap (documented in MEMORY): a lunar-vol effect "survived" an i.i.d. fake-date null and DIED
# under phase-shuffle (p=0.33). Both the astro features (smooth planetary cycles) AND the targets (returns
# with vol clustering) are strongly autocorrelated, so an i.i.d. null is far too lenient. We use TWO proper
# nulls that preserve the targets' autocorrelation and only destroy the ALIGNMENT to the astro signal:
#
#   NULL A — IAAFT / Fourier phase-randomized surrogate of the TARGET. Preserves the target's power spectrum
#            (hence its autocorrelation and vol-clustering spectrum) exactly, randomizes phases → destroys any
#            real phase-locking to the fixed astro cycle. This is the gold-standard surrogate for "is the
#            coupling to this deterministic signal real, or just two autocorrelated series lining up by luck".
#   NULL B — CIRCULAR BLOCK SHIFT of the astro feature relative to the target (all non-trivial shifts).
#            Preserves BOTH series' full autocorrelation structure; destroys only their relative alignment.
#            A real fixed-phase coupling beats this; a spurious slow-trend overlap does not.
#
# Statistic: Spearman IC (rank corr) of feature_t vs forward target over horizon h, AND a vol-regime
# contrast (top-tercile vs bottom-tercile of the feature → next-h realized vol) for the vol channel. We test
# returns (sign/magnitude) and realized vol. Multiple-testing: BH-FDR across the full (feature × asset ×
# horizon × channel) grid, plus a per-candidate two-sided surrogate p. Economic gate: any "survivor" must
# also clear a fees-aware tradeable check (long/short on feature sign, 10bps round-trip).
#
# Nothing is allowed to pass on statistics alone. "Nothing survives" is the expected, valuable result.

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "astro_strategy_lab"))

import physics_features as PF  # noqa: E402
import real_panel as RP  # noqa: E402

RNG = np.random.default_rng(20260615)
N_SURR = 1000  # surrogates per test
FEE_RT = 0.0010  # 10 bps round-trip economic gate


# ── proper nulls ────────────────────────────────────────────────────────────────────────────────

def iaaft_surrogate(x: np.ndarray, n_iter: int = 12, rng: np.random.Generator = RNG) -> np.ndarray:
    """IAAFT surrogate: preserves the amplitude DISTRIBUTION and the power SPECTRUM (autocorrelation) of x,
    randomizes phase. The proper null for 'does this autocorrelated series phase-lock to a fixed signal'."""
    x = np.asarray(x, float)
    n = len(x)
    amp = np.abs(np.fft.rfft(x))            # target power spectrum
    sorted_x = np.sort(x)                    # target amplitude distribution
    # start from a random shuffle
    s = rng.permutation(x)
    for _ in range(n_iter):
        # impose spectrum
        S = np.fft.rfft(s)
        phases = np.angle(S)
        s = np.fft.irfft(amp * np.exp(1j * phases), n=n)
        # impose amplitude distribution (rank-remap)
        ranks = np.argsort(np.argsort(s))
        s = sorted_x[ranks]
    return s


def phase_randomize(x: np.ndarray, rng: np.random.Generator = RNG) -> np.ndarray:
    """Pure Fourier phase randomization (FT surrogate): exact power spectrum, Gaussianized amplitude."""
    x = np.asarray(x, float)
    n = len(x)
    X = np.fft.rfft(x)
    amp = np.abs(X)
    rand_phase = rng.uniform(0, 2 * np.pi, size=amp.shape)
    rand_phase[0] = 0.0
    if n % 2 == 0:
        rand_phase[-1] = 0.0
    surr = np.fft.irfft(amp * np.exp(1j * rand_phase), n=n)
    return surr


def spearman_ic(feat: np.ndarray, tgt: np.ndarray) -> float:
    m = np.isfinite(feat) & np.isfinite(tgt)
    if m.sum() < 30:
        return np.nan
    return stats.spearmanr(feat[m], tgt[m]).correlation


def surrogate_p_phase(feat: np.ndarray, tgt: np.ndarray, stat_fn, n: int = N_SURR) -> tuple[float, float, float]:
    """Two-sided surrogate p: observe stat, then recompute against N IAAFT surrogates of the TARGET.
    Returns (observed, p_two_sided, null_std)."""
    obs = stat_fn(feat, tgt)
    if not np.isfinite(obs):
        return obs, np.nan, np.nan
    null = np.empty(n)
    for i in range(n):
        null[i] = stat_fn(feat, iaaft_surrogate(tgt))
    null = null[np.isfinite(null)]
    if len(null) < n * 0.5:
        return obs, np.nan, np.nan
    # two-sided: fraction of |null| >= |obs|
    p = (1 + np.sum(np.abs(null) >= abs(obs))) / (len(null) + 1)
    return obs, p, float(np.std(null))


def surrogate_p_shift(feat: np.ndarray, tgt: np.ndarray, stat_fn, n: int = 500) -> float:
    """Two-sided circular-shift p: shift the FEATURE by random non-trivial lags, recompute stat. Preserves
    both series' autocorrelation; destroys only alignment."""
    obs = stat_fn(feat, tgt)
    if not np.isfinite(obs):
        return np.nan
    L = len(feat)
    shifts = RNG.integers(L // 20, L - L // 20, size=n)  # avoid near-zero shifts
    null = np.array([stat_fn(np.roll(feat, int(s)), tgt) for s in shifts])
    null = null[np.isfinite(null)]
    if len(null) < n * 0.5:
        return np.nan
    return (1 + np.sum(np.abs(null) >= abs(obs))) / (len(null) + 1)


# ── data ────────────────────────────────────────────────────────────────────────────────────────

CRYPTO = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT",
          "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT", "ATOMUSDT"]
EQUITY = ["SPY", "QQQ", "IWM", "GLD", "SLV", "TLT", "XLE", "XLF", "XLK", "USO"]
HORIZONS = [1, 5, 10, 21]  # daily forward horizons


def build_panel() -> dict[str, pd.DataFrame]:
    """Load real bars, attach physics features + forward returns + forward realized vol per asset."""
    out: dict[str, pd.DataFrame] = {}
    cb = RP.load_crypto_bars(CRYPTO, "1d", days=3650)
    eb = RP.load_equity_bars(EQUITY, limit=2600)
    bars = {**cb, **eb}
    for sym, df in bars.items():
        if len(df) < 400:
            continue
        df = df.copy()
        df["ret1"] = np.log(df["close"]).diff()
        feats = PF.physics_features(df.index)
        panel = df[["close", "ret1"]].join(feats)
        # forward targets per horizon
        for h in HORIZONS:
            panel[f"fwd_ret_{h}"] = np.log(df["close"]).shift(-h) - np.log(df["close"])
            # forward realized vol: std of daily log-rets over the next h days
            panel[f"fwd_vol_{h}"] = df["ret1"].rolling(h).std().shift(-h)
        out[sym] = panel.dropna(subset=["ret1"])
    return out


# ── main grid ─────────────────────────────────────────────────────────────────────────────────

def run() -> pd.DataFrame:
    panel = build_panel()
    feat_cols = PF.CONTINUOUS_COLS
    records = []
    for sym, df in panel.items():
        for feat in feat_cols:
            f = df[feat].to_numpy()
            if not np.isfinite(f).any() or np.nanstd(f) == 0:
                continue
            for h in HORIZONS:
                for chan in ("ret", "vol"):
                    tgt = df[f"fwd_{chan}_{h}"].to_numpy()
                    m = np.isfinite(f) & np.isfinite(tgt)
                    if m.sum() < 200:
                        continue
                    fm, tm = f[m], tgt[m]
                    ic = spearman_ic(fm, tm)
                    if not np.isfinite(ic):
                        continue
                    records.append({
                        "symbol": sym, "feature": feat, "h": h, "chan": chan,
                        "n": int(m.sum()), "ic": ic, "abs_ic": abs(ic),
                        "_fm": fm, "_tm": tm,  # carry arrays for the surrogate stage on top candidates only
                    })
    grid = pd.DataFrame(records)
    if grid.empty:
        return grid
    # Stage-1 ranking by |IC|; only the strongest get the expensive surrogate test (FDR-aware: we still
    # report the full grid count for BH). Naive p from a t-approx for the BH stage across ALL cells.
    grid["naive_p"] = grid.apply(
        lambda r: 2 * stats.t.sf(abs(r["ic"]) * np.sqrt((r["n"] - 2) / max(1e-9, 1 - r["ic"] ** 2)), r["n"] - 2),
        axis=1,
    )
    # BH-FDR across the entire grid
    grid = grid.sort_values("naive_p").reset_index(drop=True)
    M = len(grid)
    grid["bh_thresh"] = (np.arange(1, M + 1) / M) * 0.05
    grid["bh_pass"] = grid["naive_p"] <= grid["bh_thresh"]
    # find BH cutoff
    passed = grid[grid["bh_pass"]]
    bh_cut_p = passed["naive_p"].max() if len(passed) else 0.0
    grid["bh_survivor"] = grid["naive_p"] <= bh_cut_p if bh_cut_p > 0 else False

    print(f"GRID: {M} cells tested ({len(panel)} assets × {len(feat_cols)} feats × {len(HORIZONS)} h × 2 chan)")
    print(f"BH-FDR(0.05) cutoff p = {bh_cut_p:.2e} ; cells passing BH (naive p) = {int(grid['bh_survivor'].sum())}")

    # Stage-2: the SURROGATE gauntlet on the top |IC| candidates (the only ones that could matter). We test
    # the top 40 by |IC| under BOTH proper nulls. A real edge must beat IAAFT AND circular-shift.
    top = grid.sort_values("abs_ic", ascending=False).head(40).copy()
    print(f"\nSurrogate gauntlet on top-{len(top)} |IC| candidates (IAAFT + circular-shift):")
    surr_rows = []
    for _, r in top.iterrows():
        fm, tm = r["_fm"], r["_tm"]
        _, p_iaaft, nstd = surrogate_p_phase(fm, tm, spearman_ic, n=N_SURR)
        p_shift = surrogate_p_shift(fm, tm, spearman_ic, n=500)
        surr_rows.append({
            "symbol": r["symbol"], "feature": r["feature"], "h": int(r["h"]), "chan": r["chan"],
            "n": int(r["n"]), "ic": round(float(r["ic"]), 4), "naive_p": float(r["naive_p"]),
            "p_iaaft": p_iaaft, "p_shift": p_shift,
        })
    surr = pd.DataFrame(surr_rows).sort_values("p_iaaft")
    # Bonferroni across the 40 surrogate tests
    bonf = 0.05 / len(surr)
    surr["beats_both_nulls"] = (surr["p_iaaft"] < bonf) & (surr["p_shift"] < bonf)
    pd.set_option("display.width", 200, "display.max_columns", 30)
    print(surr.to_string(index=False))
    print(f"\nBonferroni alpha (40 tests) = {bonf:.2e}")
    print(f"Candidates beating BOTH proper nulls at Bonferroni: {int(surr['beats_both_nulls'].sum())}")

    # economic gate on any that beat both nulls
    survivors = surr[surr["beats_both_nulls"]]
    if len(survivors):
        print("\n=== ECONOMIC GATE (fees-aware) on null-survivors ===")
        for _, r in survivors.iterrows():
            df = panel[r["symbol"]]
            f = df[r["feature"]].to_numpy()
            fwd = df[f"fwd_ret_{r['h']}"].to_numpy() if r["chan"] == "ret" else None
            if fwd is None:
                print(f"  {r['symbol']} {r['feature']} h{r['h']} {r['chan']}: vol channel — not directly tradeable as a return signal")
                continue
            m = np.isfinite(f) & np.isfinite(fwd)
            sig = np.sign(f[m] - np.median(f[m]))
            gross = np.nanmean(sig * fwd[m]) * (252 / r["h"])
            turn = np.mean(np.abs(np.diff(sig))) / 2 * (252 / r["h"])
            net = gross - turn * FEE_RT
            print(f"  {r['symbol']} {r['feature']} h{r['h']}: gross_ann={gross:.4f} net_ann={net:.4f} turn/yr={turn:.0f}")
    else:
        print("\nNo candidate beats both proper nulls — NOTHING SURVIVES (expected). Physics features do not couple to markets above an autocorrelation-preserving null.")
    return grid, surr


if __name__ == "__main__":
    grid, surr = run()
    surr.to_csv(HERE / "physics_study_results.csv", index=False)
    print(f"\nsaved -> {HERE / 'physics_study_results.csv'}")
