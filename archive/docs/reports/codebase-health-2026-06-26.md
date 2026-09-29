# Codebase Health & Non-Regression Verification — 2026-06-26

**Verdict: 🟢 GREEN** — full engine suite passes, every module imports, recent merges (#404, #406, #393) are non-regressed. No behavior changed by this pass. Nothing was deleted.

| Field | Value |
|---|---|
| Date | 2026-06-26 09:43 CEST |
| Base | `origin/main` @ `7741c65` (clean) |
| Branch | `docs/codebase-health` (report-only, do NOT merge) |
| Worktree | isolated; `/Users/device/cosmu` never touched |
| Python | 3.13.9 · pytest 9.0.2 · pytest-xdist 3.8.0 |
| Scope | second-pass non-regression: verify everything, change nothing, delete nothing |

---

## 1. Full engine test suite

Command:

```
python3 -m pytest apps/engine/tests -q -p no:cacheprovider -n auto --dist=loadfile
```

Result:

```
2721 passed, 2 skipped, 1 xfailed in 2377.49s (0:39:37)
EXIT_CODE=0
```

| Outcome | Count |
|---|---|
| **passed** | **2721** |
| failed | **0** |
| errors | **0** |
| skipped | 2 |
| xfailed | 1 |
| **collected** | **2724** |

- **Zero failures, zero errors.** Grep of the full log for `FAILED`/`ERROR`/`failed`/`errors` → none.
- The historically-flaky `test_finder_permutation_null` (permutation null) **passed** on the first run — no re-run needed, no flake observed this pass.
- Runtime ~40 min: the tail (last ~3%) is one heavy file pinned to a single worker under `--dist=loadfile` (loadfile keeps a whole file on one worker). Workers were CPU-pegged the entire time — slow, not hung. Confirmed via per-worker CPU snapshots (one worker at 98.5% CPU, state R, throughout).

### The 2 skips + 1 xfail (all benign, environment-conditioned, pre-existing)

These are NOT regressions — they are guarded by environment capability, not by code under test:

| Test | Kind | Reason |
|---|---|---|
| `test_retention` / `test_age_out` / `test_ducklake_cold_tier` (module-level) | skip | `ducklake`/sqlite extension unavailable offline |
| `test_cell_oos_window` / `test_cell_equity_curve` | skip | local sqlite build lacks `ALTER TABLE DROP COLUMN` |
| `test_schema_parity` | xfail | soft `pytest.xfail` on schema table/column-name divergence (intentional advisory) |

(Only 2 skips + 1 xfail actually fired in this run; the skip markers above are the candidate set — exact firing depends on the offline sqlite/ducklake capability of this M2.)

---

## 2. Recent-merge non-regression (#404, #406, #393)

All three merges are at or below HEAD on `origin/main`. Verified by (a) importing every touched module and (b) running every affected test file.

### Import-check of touched modules — 17/17 OK

| PR | Headline | Touched modules import? |
|---|---|---|
| **#404** | repair stale `KrakenFuturesFundingRateProvider` against live API | ✅ `cosmu.data.providers.funding` |
| **#406** | graveyard the direction-blind, data-starved `liquidation_cascade` feature | ✅ all 13 touched modules (feature_registry, altdata, onchain, store, seeder, ingest/catalog, ingest/pipeline, ingest/run, lab/author, mind/analysts, mind/matcher, mind/rubric, strategy/taxonomy) |
| **#393** | schedule orphaned per-market Polymarket odds ingest into hourly cron | ✅ `cosmu.data.sources.polymarket`, `cosmu.ingest.polymarket_odds`, `cosmu.research.loop` |

### Affected-test run — 106/106 passed

```
python3 -m pytest \
  test_okx_funding_provider.py test_data_research_loop.py test_dormant_sources.py \
  test_free_alt_providers.py test_ingest.py test_ingest_extra_free_sources.py \
  test_ingest_universe_broadening.py test_manage_data.py test_polymarket_gamma.py \
  test_xai_twitter.py test_polymarket_per_market_odds.py
→ 106 passed in 53.06s
```

These cover the funding-provider repair (#404), the `liquidation_cascade` graveyard fallout across ingest/altdata/mind (#406), and the per-market Polymarket odds ingest + research-loop wiring (#393). All green.

---

## 3. Whole-package import sweep

```
walk_packages(cosmu) → scanned 384 modules → ALL-IMPORTS-OK
```

- `import cosmu` → OK.
- Every one of the **384** modules under `cosmu.*` imports without error. **No broken imports, no module that fails to load** anywhere in the engine.

---

## 4. Web typecheck

**Not run — dependencies absent in this isolated worktree** (no `apps/web/node_modules`, no root `node_modules`). A `tsc -p tsconfig.json --noEmit` would require a full `pnpm install` first, which is out of scope for a "quick" check. **Not load-bearing for this pass:** all three verified merges (#404, #406, #393) are engine-side Python only — they touch no TypeScript. No web files were changed by the merges under review.

---

## 5. Regressions found

**None.** No real regression and no flake observed. Nothing was deleted; no behavior was changed by this verification pass.

---

## Verdict

🟢 **GREEN** — 2721/2724 pass (2 env-skips + 1 advisory xfail, all pre-existing and benign), 384/384 modules import, the three recent merges are confirmed non-regressed at both import and test level. Codebase is healthy on `origin/main` @ `7741c65`.
