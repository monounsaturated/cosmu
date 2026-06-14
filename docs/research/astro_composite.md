# Composite index — exploring where structure lives (then the honest read)

_Blends events/periods + astro + the REAL prod alt panel + space-weather + a cross-sectional per-coin NATAL activation into one daily score. Signal directions FIT on each asset's first 60% (train), backtested OUT-OF-SAMPLE on the last 40% — no look-ahead. 26 signals × 35 assets. Isolated 'astro_lab' namespace; saved to R2. `run_composite.py`._

## Pattern 1 — which signal GROUPS actually carry information (train IC)

| group        |         mean |   count |
|:-------------|-------------:|--------:|
| spaceweather |  0.0213361   |       2 |
| calendar     |  0.018871    |       2 |
| real         |  0.0146201   |      10 |
| event        | -0.00229191  |       5 |
| astro        | -0.000578948 |       6 |
| natal_xsec   |  7.51656e-05 |       1 |

_Mean Spearman IC of each group's signals vs next-day return, on train. |IC|~0.01 is the noise floor at these sample sizes; what stands out is the SIGN-CONSISTENCY and which group is non-trivial._


## Pattern 2 — strongest individual signals (train IC, |·| sorted)

| signal                  | group        |   train_ic_mean |   n_assets |
|:------------------------|:-------------|----------------:|-----------:|
| fear_greed              | real         |      0.094848   |         14 |
| kp_index                | spaceweather |      0.0245237  |         35 |
| turn_of_month           | calendar     |      0.0239842  |         35 |
| funding_rate            | real         |      0.023212   |         14 |
| sunspots                | spaceweather |      0.0181485  |         35 |
| social_volume           | real         |      0.0165134  |         24 |
| mars_saturn_hard_aspect | event        |      0.0164082  |         35 |
| btc_hashrate            | real         |     -0.0155531  |         35 |
| mercury_retrograde_flag | event        |     -0.0143803  |         35 |
| jupiter_lon_deg         | astro        |     -0.0140323  |         35 |
| vix_level               | real         |      0.0138406  |         21 |
| halloween               | calendar     |      0.0137579  |         35 |
| moon_near_new           | event        |     -0.0126366  |         35 |
| dxy                     | real         |     -0.0124627  |         21 |
| btc_active_addresses    | real         |      0.00993864 |         35 |

## OOS time-series composite — mean Sharpe by group (last 40%, net of fees)

| group        |       mean |     median |   count |
|:-------------|-----------:|-----------:|--------:|
| event        |  0.154496  |  0.121233  |      35 |
| natal_xsec   |  0.0655871 |  0.0141044 |      35 |
| astro        | -0.147151  | -0.0393695 |      35 |
| spaceweather | -0.278597  | -0.282768  |      35 |
| all          | -0.343417  | -0.335341  |      35 |
| calendar     | -0.376118  | -0.539773  |      35 |
| real         | -0.593735  | -0.580009  |      35 |

### …and by group × segment (where does it live?)

| group        |   commodity_fx |   crypto_large |   crypto_mid |   crypto_small |   equity_index |   equity_sector |
|:-------------|---------------:|---------------:|-------------:|---------------:|---------------:|----------------:|
| all          |          -0.35 |          -0.41 |         0.02 |          -0.54 |          -0.5  |           -0.34 |
| astro        |           0.08 |          -0.09 |         0.02 |          -0.76 |           0.27 |            0.4  |
| calendar     |          -0.35 |          -0.74 |        -0.13 |          -0.12 |          -0.79 |           -0.75 |
| event        |           0.37 |           0.19 |        -0.04 |          -0.06 |           0.59 |            0.4  |
| natal_xsec   |          -0.04 |          -0.04 |         0.22 |           0.31 |          -0.25 |           -0.42 |
| real         |          -0.76 |          -0.17 |        -0.5  |          -0.7  |          -0.93 |           -0.5  |
| spaceweather |          -0.43 |          -0.18 |        -0.12 |          -0.27 |          -0.54 |           -0.3  |

## OOS CROSS-SECTIONAL long-short (rank assets by composite, long top 30% / short bottom 30%)

| group        | kind           |    n |     sharpe |
|:-------------|:---------------|-----:|-----------:|
| natal_xsec   | xsec_longshort | 2330 |  0.387825  |
| all          | xsec_longshort | 2330 | -0.0216603 |
| astro        | xsec_longshort | 2330 | -0.358366  |
| real         | xsec_longshort | 2330 | -0.389527  |
| spaceweather | xsec_longshort | 2330 | -0.898717  |

_This is the construction the prior study could NOT test (market-wide astro is identical across assets). Here the REAL per-asset signals + the per-coin natal chart give genuine cross-sectional spread._


## The honest read (open-minded, then deflated)

- **Time-series OOS median Sharpe:** real=-0.58 · astro=-0.04 · all=-0.34. The pattern to look at: does `all` beat `real` (astro/event/natal ADD), or does blending DILUTE the real edge (as the prior incremental test found)?
- **Best cross-sectional OOS:** group=`natal_xsec` Sharpe 0.39 (n=2330). A single OOS Sharpe is NOT a survivor — it needs DSR at the group-trial count + a forward test. Reported as a pattern to investigate, not an edge.
- **Honest caveat:** train/test (not full CPCV), single OOS window, fixed signs from train — this is EXPLORATION to surface structure, not a gate verdict. A real survivor must then clear the project's Deflated-Sharpe/CPCV gate and a forward test. The prior 152k-trial lab + incremental test say the honest prior is: real signals carry a faint edge, astro/event/natal add ~nothing, and the cross-sectional spread (if any) lives in the REAL per-asset signals, not the planets.

