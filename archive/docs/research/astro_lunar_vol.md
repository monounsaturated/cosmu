# Lunar realized-volatility effect — rigorous vetting (try to BREAK it)

_The event study found crypto realized-vol elevated around full moons (survived a fake-date placebo + BH-FDR). Here we attack it: per-asset consistency, 8-bin synodic profile vs a PHASE-SHUFFLE null, era stability, outlier-robustness, and tradability. Real crypto bars, deterministic lunar phase. `lunar_vol.py`._

## Test 1 — per-asset consistency (a real effect shows in MANY coins)

- **17 of 23 coins** have higher realized vol in the full-moon bin than the rest (74%). Median full/rest vol ratio: **1.020**

## Test 2 — 8-bin synodic profile + phase-shuffle null (the decisive test)

- Mean realized vol by phase bin (bin 4 = full): [0.0459, 0.0449, 0.0476, 0.0492, 0.0476, 0.049, 0.0459, 0.047]
- Full-bin vs rest contrast = **1.011** (shuffle-null mean 1.000); **phase-shuffle p = 0.3339**.
  - ✗ Dies under phase-shuffle — artifact.

## Test 3 — stability & robustness

- Era contrast: early **1.011** · late **1.013** (STABLE across eras).
- Drop top-2% vol days: contrast **0.981** (driven by outliers).

## Test 4 — is it tradable? (directional vs vol-only)

- Forward return full-bin **-0.00261** vs rest **+0.00067** — a directional edge exists.
- BTC vol-timing (half size around full moon): buy&hold Sharpe 0.45 → vol-timed 0.50 (helps).

## The honest read

A lunar realized-VOLATILITY effect is the ONE thing in this whole investigation that survives a hard placebo. If Test 2's phase-shuffle holds (p<0.05) AND it's consistent across coins AND stable across eras, it is a REAL (weak) lunar-volatility regularity — matching the least-debunked corner of the literature. BUT the event study + Test 4 show it is **vol, not direction**: higher vol around full moons is NOT a spot return edge (it's symmetric). Its only honest use is **risk/vol management or an options/vol-timing overlay**, and only if it then survives Deflated-Sharpe + a forward test as a real strategy. We do NOT promote it; we log it as the one weak-but-real regularity, cleanly separated from the (dead) directional astro search.

