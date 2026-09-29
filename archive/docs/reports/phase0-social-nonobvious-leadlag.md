# Phase-0 Social Signal — the NON-OBVIOUS lead-lag (what's actually in the LunarCrush data)

> The generic social cohort just FAILED the Gate ([phase0-social-signal-verdict.md](phase0-social-signal-verdict.md)),
> but its five specs were obvious ideas (volume spike, sentiment divergence) fitted as **absolute** thresholds on
> a series that grew ~160× over 2020-26 — so four of the five never even bound their nominal signal (that report's
> §4). This pass goes back to the raw data and asks what *non-obvious* structure is actually there, then authors
> three specs grounded in the **measured** signal (not the plausible one), each with a pre-registered disconfirmer,
> and routes them through the **existing, untouched** Gate.

**Data:** 30 assets, real cached Binance daily bars (window **2023-09-10 .. 2026-06-05**, ~1000 bars/asset, all
three regimes present — chop 6995 · bull 10533 · bear 12421) joined to the real backfilled LunarCrush store
(`social_volume`, `social_sentiment`, `galaxy_score`, 2,348 PIT points/symbol back to 2020-01). **Point-in-time:**
every social bucket carries `available_at = ts + 1 day`; the probe only uses a value to predict returns that begin
**after** that stamp, and the engine derivations inherit `available_at` from the latest raw point they consume.

**Reproduce (deterministic, offline, zero LLM):**
```bash
# descriptive probe — raw numbers for (a)-(d) + disconfirmers
COSMU_SOCIAL_DIR=<dir>/.cosmu/altdata COSMU_BAR_DIR=<dir>/.cosmu/market_data/binance \
  python3 scripts/social_leadlag_probe.py
# the three specs through the EXISTING Gate (normalized features so thresholds actually bind)
cd apps/engine && PYTHONPATH=$PWD python3 -m cosmu.research.social_nonobvious_cohort   # run from a dir whose .cosmu has bars+social
```

---

## 1. What leads price — raw numbers

Per-asset Pearson correlation, aggregated as a t-test **across the 30 assets** (each asset = one observation;
conservative against within-asset autocorrelation). `<<<` = cross-asset p < 0.05.

### (a) The headline: social_volume **CHANGE** leads, the **LEVEL** does not

`corr( day-over-day change of the metric at t , forward log-return t→t+k )`:

| metric Δ | k=1 | k=2 | k=3 | k=5 | k=7 |
|---|---|---|---|---|---|
| **social_volume (log-change)** | **+0.024 (t=5.3)** | **+0.030 (t=9.4)** | **+0.020 (t=5.7)** | +0.006 (t=1.7) | +0.006 (t=2.0) |
| social_sentiment (Δ) | +0.006 | −0.002 | −0.001 | −0.001 | −0.003 |
| galaxy_score (Δ) | +0.001 | −0.003 | +0.002 | −0.001 | +0.002 |

A **fresh acceleration** in social attention leads price UP at k=1-3 (83-100% of assets positive), then **decays to
insignificance by k=5**. Sentiment-change and galaxy-change carry nothing. By contrast the **LEVEL** (within-asset z
of social_volume) is only weakly negative and **not robust** (best t=−1.98 at k=5, p=0.057). So the tradeable seam
the absolute-volume specs missed is the **change**, not the level.

### (b) Galaxy-score extremes → drawdowns (the asymmetry that did NOT replicate)

On a shorter sample this looked like a clean "top-decile galaxy → deeper drawdowns, equal upside" asymmetry. On the
**full** 1000-bar sample it **collapses**: HI-vs-MID forward-drawdown t = −0.82 / −1.70 / −1.31 / −0.78 / −1.29
(k=1..7) — none significant, and the top-decile forward **runup** is actually slightly *higher* than the bottom
decile. **Honest call: there is no robust galaxy-altitude drawdown edge here.** A finding that flips from
significant to noise with 20% more (recent) data is exactly the fragility the Gate's holdout is built to catch —
so no spec rests on it (the `galaxy_score_z` feature is still registered for completeness).

### (c) Social volume **RELATIVE to traded volume** → ~1-week continuation (robust, non-obvious)

`excess_attention = ln(social_volume) − ln(dollar_volume)`, within-asset z (how loud the crowd is *for the money
actually trading*). `corr(excess-attention_t, fwd-ret_{t→t+k})`:

| k | mean r | t (across assets) | top–bottom decile fwd-ret spread |
|---|---|---|---|
| 1 | +0.001 | +0.18 | −0.03% (n.s.) |
| 3 | +0.003 | +0.36 | −0.02% (n.s.) |
| 5 | +0.016 | +1.91 | +0.35% (n.s.) |
| **7** | **+0.044** | **+4.34** | **+1.81% (t=+5.77, p<0.001)** |

The effect is **absent short-horizon and emerges only by k=5-7** — a slow continuation. This is genuinely
non-obvious: it is *relative* loudness, not absolute volume, and it pays a week out, not a day out.

### (d) Cross-asset contagion: BTC social spike → the ALT complex (robust)

`corr( BTC social_volume change at t , mean-ALT forward return t→t+k )`:

| k=1 | k=2 | k=3 | k=5 | k=7 |
|---|---|---|---|---|
| **+0.068** | **+0.064** | +0.027 | +0.015 | +0.025 |

A BTC attention spike leads the **whole alt complex** up the next 1-2 days (n~1000 pooled days). BTC
*sentiment*-change and *galaxy*-change show nothing comparable. (BTC galaxy extremes → alt drawdowns is directional
but thin, n≈100/decile — not strong enough to build on.)

---

## 2. Disconfirmers (pre-registered falsification — both PASS at the descriptive level)

- **Spec-1 (acceleration ≠ level):** does the acceleration edge survive controlling for the level? Partial
  correlation of accel vs fwd-ret, residualizing both on the within-asset level z: raw mean r **+0.030** →
  level-controlled **+0.033** (k=2, 30 assets). **Accel SURVIVES** — it is genuinely the change, not the altitude.
- **Spec-3 (BTC social ≠ BTC price):** head-to-head OLS, mean-ALT fwd-ret(k=2) ~ standardized BTC_social_accel +
  BTC_price_return. BTC_social_accel beta **+0.064 (t=+2.01)** vs BTC_price_return **−0.016 (t=−0.50)**. **BTC
  social adds signal over price** — the contagion is the crowd, not the tape.

---

## 3. The three specs through the EXISTING Gate — honest verdict: **FAIL**

Routed as ONE cohort through the untouched scorer + `promote_cohort` BH-FDR (q=0.10) on real bars + the
**normalized** social features (`cosmu/research/social_norm.py`, so thresholds actually bind — unlike the §4
no-op cohort), real taker fees, every grid variant recorded as a trial.

| spec | net | gross | cost_ratio | trades | deflated-Sharpe | gate-PBO | regimes+ | maxDD | gate |
|---|---|---|---|---|---|---|---|---|---|
| social-accel-uncrowded-momentum | +0.51% | +1.57% | 0.33 | 1609 | 0.060 | 0.04 | 1 | 0.065 | STOP |
| social-excess-attention-week-continuation | −0.09% | +1.36% | −0.07 | 1788 | 0.062 | 0.43 | 1 | 0.120 | STOP |
| btc-social-contagion-alt-lead | **+3.25%** | +3.84% | **0.85** | 745 | **0.596** | **0.000** | **3** | **0.037** | STOP |

**No spec survives** (best deflated-Sharpe 0.596 « 0.95 bar; all three fail the untouched-holdout). Reading it:

- **The descriptive edges are REAL but SUB-TRANSACTION-COST.** social-accel bleeds 67% of a tiny gross to fees
  (cost_ratio 0.33 — over-trading a ~k=2 signal); excess-attention's k=7 continuation is too weak per-trade to
  clear daily-rebalance cost (net goes negative). A statistically detectable lead-lag ≠ a tradeable edge.
- **btc-social-contagion is the standout near-miss.** It is the *only* one that is **not overfit** (PBO 0.000),
  is **positive in all three regimes**, has a **3.7% maxDD**, a healthy 0.85 cost_ratio, and +4.3 skew — yet its
  deflated-Sharpe (0.596) still falls short of significance against the trial-inflated benchmark. This is the one
  worth revisiting: as a **lower-turnover or filter-only** signal (e.g. a complex-wide risk-on tag layered on a
  slower book) rather than a daily entry trigger, where the cost drag that kills it here would not apply.
- **Unlike the failed §4 cohort, these features BIND.** Trade counts (1609 / 1788 / 745) and the BTC filter
  gating down to 745 trades / 3 regions confirm the thresholds are doing real work on a scale-stable feature —
  this is an honest test of the signal, not a no-op filter on a price rule.

**Bottom line:** the LunarCrush data *does* contain non-obvious, point-in-time, disconfirmer-surviving structure —
**attention acceleration (k1-3), excess-attention continuation (k7), and BTC→alt contagion (k1-2)** — but none of
it clears the cost-aware Gate as a standalone daily long. The cross-asset contagion is the most promising thread
and is the honest candidate for a follow-up (lower-turnover / filter framing). No PASS was manufactured; no
threshold was changed.

---

## 4. What shipped (PR, not merged)

- `scripts/social_leadlag_probe.py` — the reproducible descriptive probe (raw numbers for §1-2; no engine import).
- `cosmu/research/social_norm.py` — PIT-correct normalized social derivations (`social_volume_accel`,
  `social_attention_z`, `social_excess_attention_z`, `galaxy_score_z`, broadcast `btc_social_accel`) — the §4 fix:
  scale-stable features so a fitted threshold binds. Unit-tested for no-look-ahead (`tests/test_social_norm.py`).
- `cosmu/config/feature_registry.py` — the five derived features registered (tier1, low-confidence).
- `strategies/inbox/` — the three specs: `social-accel-uncrowded-momentum.json`,
  `social-excess-attention-week-continuation.json`, `btc-social-contagion-alt-lead.json`.
- `cosmu/research/social_nonobvious_cohort.py` — the Gate harness (existing scorer + q=0.10, normalized join).
