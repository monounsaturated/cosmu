# Leakage tripwire UPSTREAM of the Gate — PIT audit + shuffle-null + ticker-anonymization (POC)

Date: 2026-06-28
Branch: `claude/leakage-tripwire-poc-2026-06-28`
Status: **DRAFT POC — do not merge yet.** Autonomous-run, propose-only research instrument. Reversible.

## Why

The deterministic Gate (BH-FDR + CSCV-PBO + DSR/expected-max-Sharpe deflation + min-trades + holdout +
beat-buy-and-hold, per `(strategy × symbol × venue)` combo on its own data) validates whether an EDGE is real.
It **cannot see leakage introduced UPSTREAM of it**, on the feature/data side. A vibe-coded feature with
look-ahead (forward-window definitions, global normalization over full history, revision-unsafe alt-data joins,
`available_at >=` the timestamp it describes, target/identity leakage) produces a backtest that **sails through
the Gate and then dies live** — the single most likely way the machine fools itself at scale
([[vibe_coding_leakage_risk]]). This POC is the **feature-side leakage tripwire, BEFORE the Gate.**

It is **propose-only**: it INFORMS, it does not touch the Gate verdict, mutate any Gate constant, or move money.
A PASS is the price of admission to the Gate; the Gate alone disposes.

## What was already there (honest accounting)

A leakage tripwire was already merged (`apps/engine/cosmu/research/leakage_tripwire.py`, PR #387) bundling
available_at audit + shuffle-null + **forward-shift sanity**, and `cosmu/research/disconfirmers.py` already
implemented a `symbol_anonymization_null`. This POC **wires the operator's named third disconfirmer
(ticker/identity anonymization) into the bundled tripwire report** — it was implemented but not in the bundle —
while keeping the forward-shift guard (it catches a back-dated-alignment leak the other three structurally miss).
Net result: the single `audit_feature` front door now runs all three operator-named disconfirmers + forward-shift.

## The disconfirmers (each a clean function → a structured verdict)

`audit_feature(points, bars, ...) -> TripwireReport` runs, all reusing the SAME `align_asof` join the backtest
runs + `spearman_ic` (never a second hand-rolled correlation):

1. **PIT / available_at audit** (`available_at_audit`) — brute-verify the `align_asof` join is strictly
   backward-looking: for every bar that received a value, that value is reproducible from ONLY the points whose
   `available_at <= bar.ts`, and is the LATEST such point. Flags **look-ahead** (a value present with nothing
   knowable by then) and **wrong-winner** (a stale/future revision). Output: `n_joined`, `violations`,
   `mismatches`, `passed`. The companion `test_leakage_tripwire_pit.py` extends this to every feature-side join
   (`sum_funding_per_bar`, `store.read_asof`, the bridge `_snapshot`, and the FEATURE_REGISTRY as-of declarations).

2. **Shuffle / permutation null** (`shuffle_null`) — measure the real PIT IC, then permute the feature's VALUES
   in time over K=200 string-seeded trials (break the temporal alignment, preserve the marginal) and recompute.
   A real edge collapses (BlindTrade: IC 0.015 → 0.0004); an IC inside the shuffled band is a noise/autocorr
   artefact. Output: `real_ic`, `null_mean_abs`, `null_p95_abs`, empirical add-one `p_value`, `survives`.

3. **Ticker / identity anonymization** (`symbol_anonymization_null`) — strip SYMBOL IDENTITY by demeaning each
   symbol's feature AND forward return WITHIN that symbol, then pool. A cross-sectional IC that comes from a
   memorized per-symbol PRIOR (a constant level that ranks with that symbol's drift — "BTC always goes up")
   VANISHES; a transferable within-symbol timing signal SURVIVES. The IC analog of the LLM ticker-memorization
   test (Sarkar & Vafa). Output: `pooled_ic`, `within_ic`, `identity_share`, `memorized`. **Active only when a
   multi-symbol map is supplied** (identity is cross-sectional); a single series is reported SKIPPED, never
   silently passed.

4. **Forward-shift sanity** (`forward_shift_sanity`, kept from #387) — shifting +1 bar (tomorrow's value today)
   must IMPROVE |IC|; if shifting BACKWARD (a more honest, extra-lagged read) materially improves the fit, the
   live wiring is already peeking a bar too early — a baked-in look-ahead the available_at audit can miss when
   `available_at` itself is wrong.

`TripwireReport.passed` = AND of every ACTIVE check. `failed_checks` names the disconfirmer that caught it.
`require_shuffle_survival` / `require_anonymization_survival` (both default True) can drop their check to advisory
(verdict still recorded). The positive-look-ahead checks ([1], [4]) are always hard.

## Acceptance tests (the criterion: a known leak is CAUGHT, a known-clean PASSES)

`apps/engine/tests/test_leakage_tripwire.py` (extended) — offline, deterministic, string-seeded:

- KNOWN-CLEAN on-bar-honest feature → PASSES all checks.
- LEAKED feature (each value stamped one bar early, back-dated so the join looks clean) → FAILS, specifically on
  **forward-shift** ([1] and shuffle stay green — the leak is the alignment, not the data; exactly the
  Gate-invisible mode).
- KNOWN-CLEAN multi-symbol panel (transferable within-symbol timing, no per-symbol level prior) → **PASSES
  ticker-anonymization** (`within|IC| ≈ pooled|IC|`, identity_share ≈ 0).
- IDENTITY-MEMORIZED panel (constant per-symbol feature level ranking with that symbol's constant drift) →
  **FAILS ticker-anonymization** (`pooled|IC| ≈ 0.33`, `within|IC| ≈ 0`, identity_share ≈ 1.0, `memorized=True`,
  `ticker_anonymization` in `failed_checks`). The acceptance criterion for disconfirmer #3.
- Single-series → anonymization SKIPPED and named in the render (never silently passed).
- Direct-call isolation of [3]; advisory-mode for both shuffle and anonymization; determinism; render readability.

Verified robust across seeds {1,7,11,42,100}: clean panel always survives, memorized always flagged.

### Test results

```
tests/test_leakage_tripwire.py tests/test_leakage_tripwire_pit.py
tests/test_disconfirmer_harness.py tests/test_prediction_tripwire.py  ->  44 passed
```

Plus `test_placebo_panel.py` + `test_green_tests_not_correct.py` + `test_authority_disconfirmers.py` (dependents
of the tripwire / disconfirmers) → green. No Gate constant touched; `prediction_tripwire.py` (the live caller of
`audit_feature`) is unaffected — all new params default to off/None (fully backward-compatible).

## CLI

```
python -m cosmu.research.leakage_tripwire clean            # clean single-series control  -> PASS (exit 0)
python -m cosmu.research.leakage_tripwire leaked --leaked  # back-dated 1-bar look-ahead   -> FAIL forward-shift
python -m cosmu.research.leakage_tripwire anon  --anon     # transferable multi-sym panel  -> PASS anonymization
python -m cosmu.research.leakage_tripwire memo  --anon --leaked  # identity-memorized panel -> FAIL anonymization
```

All offline, keyless, deterministic — no network, no DB, no Binance (the M2 is geo-blocked).

## Honest limitations (a PASS is necessary, NOT sufficient)

- **Coverage gap.** The shuffle + anonymization nulls catch the spurious/memorized class; available_at +
  forward-shift catch look-ahead. None catches a leak that is simultaneously real-in-alignment, shuffle-surviving
  AND symbol-transferable — e.g. **global-normalization** (mean/std/min/max/quantile over the WHOLE history)
  whose leak is a slow drift rather than a per-bar misalignment. That smell is best caught at INGEST (the
  `profile-source` PIT-lag profiler + the raw-source available_at audit), not in this per-feature IC harness.
  This is documented in the module header, not over-claimed. The tripwire REDUCES the surface; it does not close
  it.
- **Anonymization is a binary flag with a 50% threshold.** A MIXED edge (real timing + a partial identity prior)
  shows a partial `identity_share` and may land either side of the boundary — read `identity_share`, not just the
  flag. Within-symbol demeaning removes constant levels but not, e.g., a per-symbol scale; it is the IC analog of
  ticker masking, not a full causal de-identification. Needs a multi-symbol map; SKIPPED for one series.
- **Statistical power.** The shuffle p-value is empirical (add-one corrected); with few obs the null band is
  wide. The forward-shift margin (15%) is conservative against estimation noise — a sub-margin baked-in peek can
  slip [4].
- **Synthetic fixtures** prove the harness can tell clean from leaked; real-data behavior depends on the actual
  source's PIT stamps being honest in the first place (the available_at audit assumes the points carry truthful
  `available_at`; a source that lies in its OWN available_at is an ingest-side problem the profiler must catch).

## Files

- `apps/engine/cosmu/research/leakage_tripwire.py` — wired anonymization into the bundle + multi-symbol fixtures + `--anon` CLI + limitations.
- `apps/engine/tests/test_leakage_tripwire.py` — anonymization acceptance tests (clean panel PASS, memorized panel FAIL, isolation, advisory, skipped-single-series).
- `docs/reports/leakage-tripwire-poc-2026-06-28.md` — this report.

DO NOT MERGE yet — autonomous-run POC for review.
