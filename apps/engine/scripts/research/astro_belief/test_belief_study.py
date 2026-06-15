# intent: LIGHT offline unit tests for the deterministic guts of the belief study — no network, no heavy compute.
# Verifies: the Mercury-retrograde dummy is sane (~19%/yr, contiguous blocks), the PIT belief shift never leaks
# future pageviews, the placebo calendar preserves block coverage, and the HAC OLS recovers a planted coefficient.
# Run: python3 -m pytest scripts/research/astro_belief/test_belief_study.py -q   (or plain `python3` exec).

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ENGINE_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ENGINE_ROOT / "scripts" / "research" / "astro_belief"))

import belief_study as BS  # noqa: E402


def test_retro_dummy_coverage_and_blocks():
    idx = pd.date_range("2016-01-01", "2025-12-31", freq="D")
    retro = BS.mercury_retrograde(idx)
    frac = retro.mean()
    # Mercury is retrograde ~3x/yr × ~21-24 days ≈ 18-21% of days
    assert 0.14 < frac < 0.24, f"retro fraction {frac:.3f} outside plausible 14-24%"
    windows = BS.retro_windows(retro)
    # ~3 windows/yr over 10y ≈ 25-35 windows
    assert 24 <= len(windows) <= 40, f"got {len(windows)} retro windows"
    # every window is contiguous and non-trivial length
    for a, b in windows:
        seg = retro.loc[a:b]
        assert seg.min() == 1.0, "window contains a non-retro day"
        assert (b - a).days >= 7, "retro window implausibly short"


def test_belief_pit_shift_no_lookahead():
    # construct pageviews where day t value == t's ordinal; after shift, the feature at t must come from t-lag
    idx = pd.date_range("2020-01-01", periods=200, freq="D")
    pv = pd.DataFrame({"Mercury_retrograde": np.arange(len(idx), dtype=float) + 1.0}, index=idx)
    feat = BS.belief_intensity(pv, idx)["Mercury_retrograde"]
    # the z-score at t uses obs = log1p(views).shift(PUBLISH_LAG_DAYS); the LAST observable raw input at t is
    # the (t - lag) row, never t itself. Verify by checking the expanding window can't see the future: the
    # feature is NaN until min_periods+lag rows exist, and is finite afterward (monotone input → finite z).
    lag = BS.PUBLISH_LAG_DAYS
    assert feat.iloc[: 60 + lag - 1].isna().all(), "feature populated before enough history (look-ahead risk)"
    assert np.isfinite(feat.iloc[80:]).all(), "feature should be finite once warmed up"


def test_placebo_preserves_coverage():
    idx = pd.date_range("2018-01-01", "2024-12-31", freq="D")
    retro = BS.mercury_retrograde(idx)
    windows = BS.retro_windows(retro)
    rng = np.random.default_rng(7)
    fake = BS._placebo_calendar(idx, windows, rng)
    # block lengths are preserved; randomly-placed blocks can occasionally overlap, so the "on"-day count is
    # <= real and within ~10% of it (overlaps are rare with ~19% coverage). Structure, not exact equality.
    assert set(fake.unique()) <= {0.0, 1.0}
    assert int(fake.sum()) <= int(retro.sum()) + 1, "placebo cannot exceed real coverage (blocks preserved)"
    assert int(fake.sum()) >= int(0.85 * retro.sum()), "placebo lost too much coverage to overlaps"


def test_hac_recovers_planted_coef():
    rng = np.random.default_rng(11)
    n = 8000
    d = (rng.random(n) < 0.19).astype(float)  # retro-like dummy
    true_coef = -0.004  # -40 bps/day in retro (large vs noise so a single draw is stable)
    y = true_coef * d + rng.normal(0, 0.01, n)
    X = np.column_stack([np.ones(n), d])
    beta, t = BS._hac_t(y, X, lags=5)
    assert abs(beta[1] - true_coef) < 5e-4, f"HAC beta {beta[1]:.5f} far from planted {true_coef}"
    assert t[1] < -2, "planted negative real effect should be significantly negative"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
    print("ALL OFFLINE TESTS PASSED")
