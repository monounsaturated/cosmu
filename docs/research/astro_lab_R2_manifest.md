# astro_lab R2 lake — manifest & how to use it

_All experiments persisted under **`r2://cosmu-lake/astro_lab/`** as Parquet — one prefix per experiment, DuckDB-queryable, trivially droppable. The raw trials are kept for learning; the distilled findings + lessons are the top-level tables. `r2_manifest.py` (idempotent)._

## Inventory

| prefix                           |   n_files |   n_rows | columns                                                                                                                   |
|:---------------------------------|----------:|---------:|:--------------------------------------------------------------------------------------------------------------------------|
| astro_lab/_findings.parquet/     |         1 |        6 | experiment, prefix, finding, headline, verdict, tradeable                                                                 |
| astro_lab/_lessons.parquet/      |         1 |        5 | lesson                                                                                                                    |
| astro_lab/_manifest.parquet/     |         1 |       10 | prefix, n_files, n_rows, columns                                                                                          |
| astro_lab/composite/             |         3 |      276 | signal, group, train_ic_mean, n_assets                                                                                    |
| astro_lab/event_study/           |         1 |       76 | pool, event, metric, n_events, observed, null_mean, effect, p, survives_fdr                                               |
| astro_lab/lunar_vol/             |         2 |       31 | asset, full_vol, rest_vol, ratio                                                                                          |
| astro_lab/run_1781470150_e1df61/ |        48 |   152166 | config_id, school, feature, transform, hold, polarity, level, q, asset, n, n_trades, sharpe, net_return, avg_pos, segment |

## Curated findings (the interesting stuff)

| experiment   | prefix                       | finding                                                                         | headline                                                                            | verdict            | tradeable   |
|:-------------|:-----------------------------|:--------------------------------------------------------------------------------|:------------------------------------------------------------------------------------|:-------------------|:------------|
| strategy_lab | astro_lab/run_*/             | 152,166 astro strategy trials (5 schools × 35 assets × 6 segments)              | raw best Sharpe 1.85 → 0 survive Deflated-Sharpe at the true trial count            | NO EDGE            | False       |
| deep_study   | (docs) astro_vs_markets_deep | 126 astro features vs 13.6M-row real alt panel; incremental test                | astro DEGRADES OOS AUC on top of real signals (-0.015/-0.042, p=1.0)                | NO EDGE (negative) | False       |
| composite    | astro_lab/composite/         | multi-signal composite (astro+events+real+spaceweather+natal), train/test       | train→OOS ranking INVERTS (best-train=worst-OOS); astro dilutes the faint real edge | NO EDGE            | False       |
| event_study  | astro_lab/event_study/       | vol/turnover in ±3d windows around named astro events vs fake-date null         | apparent full-moon/eclipse realized-VOL effect (3/76 survive BH-FDR) — CANDIDATE    | CANDIDATE→KILLED   | False       |
| lunar_vol    | astro_lab/lunar_vol/         | decisive phase-shuffle null on the lunar-vol candidate                          | phase-shuffle p=0.33, flat profile, outlier-driven → the candidate is an artifact   | ARTIFACT (no edge) | False       |
| pit_audit    | astro_lab/audits/            | point-in-time honesty of the REAL signals (available_at / backfill / revisions) | which real signals are tradeable-live vs look-ahead (see alt_data_pit_audit.md)     | SEE AUDIT          |             |

## Lessons (reusable for the next signal)

- Expected best raw Sharpe under noise ≈ sqrt(2·ln N)/sqrt(T); Deflated Sharpe charges exactly that — more configs deflate HARDER, never 'find' an edge.
- Train-IC ranking that does NOT predict OOS-Sharpe ranking is the fingerprint of noise/decay, not structure.
- A fake-RANDOM-date placebo is too weak for autocorrelated metrics (vol); the proper null is a LABEL/PHASE-SHUFFLE that preserves the series.
- Astro is broadcast-identically across assets → cross-sectional needs a per-asset construction (natal); even that carried nothing.
- Pure astro (planets/aspects/lunar/eclipse/natal) is dead; the only faint signal is wider NON-astro (calendar turn-of-month, real macro/sentiment) and it decays OOS.

## Query / dump (DuckDB — no boto3, R2 secret in-memory)

```sql
INSTALL httpfs; LOAD httpfs;
CREATE SECRET r2 (TYPE r2, KEY_ID '…', SECRET '…', ACCOUNT_ID '…');
-- curated findings:
SELECT * FROM read_parquet('r2://cosmu-lake/astro_lab/_findings.parquet');
-- inventory:
SELECT * FROM read_parquet('r2://cosmu-lake/astro_lab/_manifest.parquet');
-- all 152k strategy trials, ranked:
SELECT * FROM read_parquet('r2://cosmu-lake/astro_lab/run_*/*.parquet') ORDER BY sharpe DESC LIMIT 50;
```

## Drop a single experiment (clean teardown)

Each experiment is one prefix under `astro_lab/` — delete that prefix in R2 to drop it; nothing else references it (isolated namespace, never touches prod `alt_data` or the Gate).

