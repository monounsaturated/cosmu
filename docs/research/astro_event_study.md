# Astro event study — vol/turnover around named events vs a fake-date placebo

_For each named astro event (new/full moon, eclipse, Mercury-retro station, Mars-Saturn hard aspect), the ±3-day window's realized-vol / |return| / volume-z / return, pooled by segment, vs a permutation null of 2000 FAKE-date sets (same count, random). The fake-date placebo is the disconfirmer. BH-FDR over all 76 (event×pool×metric) tests. Real data, PIT. `event_study.py`._

## Verdict — **3 of 76 tests beat the fake-date placebo after BH-FDR(5%)**

⚠️ Some events beat their placebo — candidates for a proper deflated + forward test (NOT yet an edge):

| pool         | event     | metric       |   n_events |   effect |          p |
|:-------------|:----------|:-------------|-----------:|---------:|-----------:|
| crypto_large | full_moon | realized_vol |         31 |  3.7264  | 0.00049975 |
| crypto_large | eclipse   | realized_vol |          8 |  4.8731  | 0.0009995  |
| crypto_mid   | eclipse   | realized_vol |          8 |  4.19365 | 0.00149925 |

## Strongest raw effects (pre-FDR — read skeptically)

| pool         | event     | metric       |   n_events |   observed |   null_mean |   effect |          p | survives_fdr   |
|:-------------|:----------|:-------------|-----------:|-----------:|------------:|---------:|-----------:|:---------------|
| crypto_large | eclipse   | realized_vol |          8 |  0.0815674 |  0.0339899  |  4.8731  | 0.0009995  | True           |
| crypto_all   | eclipse   | realized_vol |          8 |  0.0834579 |  0.0411472  |  4.30483 | 0.0029985  | False          |
| crypto_mid   | eclipse   | realized_vol |          8 |  0.08658   |  0.0412173  |  4.19365 | 0.00149925 | True           |
| crypto_large | full_moon | realized_vol |         31 |  0.0520348 |  0.0339498  |  3.7264  | 0.00049975 | True           |
| crypto_all   | full_moon | realized_vol |         31 |  0.0578402 |  0.0409454  |  3.2954  | 0.003998   | False          |
| crypto_mid   | full_moon | realized_vol |         30 |  0.0576616 |  0.041027   |  3.0818  | 0.00549725 | False          |
| crypto_mid   | eclipse   | abs_ret      |          8 |  0.0648758 |  0.0387961  |  2.91111 | 0.0109945  | False          |
| crypto_large | eclipse   | abs_ret      |          8 |  0.0574301 |  0.032532   |  2.75917 | 0.0124938  | False          |
| crypto_large | full_moon | abs_ret      |         31 |  0.0456114 |  0.0327701  |  2.74337 | 0.009995   | False          |
| crypto_all   | full_moon | abs_ret      |         31 |  0.0504439 |  0.0390835  |  2.50627 | 0.0134933  | False          |
| crypto_all   | eclipse   | abs_ret      |          8 |  0.0615565 |  0.0389827  |  2.4745  | 0.0224888  | False          |
| crypto_mid   | full_moon | abs_ret      |         30 |  0.050281  |  0.0388084  |  2.39732 | 0.0184908  | False          |
| crypto_small | new_moon  | volume_z     |         20 | -0.224943  | -0.00599993 | -1.69142 | 0.955022   | False          |
| crypto_all   | new_moon  | volume_z     |         31 | -0.142682  |  0.034972   | -1.60229 | 0.952524   | False          |
| crypto_large | new_moon  | volume_z     |         31 | -0.157182  |  0.0330742  | -1.57157 | 0.945027   | False          |

_`effect` = (observed − fake-date mean) / fake-date std. |effect|≳3 with a low p AND FDR-survival is the only thing worth a follow-up; an isolated big effect at small n_events is the usual mirage._

