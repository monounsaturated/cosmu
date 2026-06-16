# Checkpoint — `bb_width` feature + Bollinger squeeze-release reversion spec (2026-06-16)

**Author:** Opus 4.8 agent (video-inspired strategy task)
**Branch:** `feat/rho-bar-wiring`
**Status:** ✅ Implemented, unit-tested, locally green. **Committed as TWO isolated, scoped commits** (`git log`): `c6c74df` (bb_width) and `5fbb5fc` (range_position). NOT pushed, NOT merged — left for the master agent to integrate.

> **Update (2nd increment):** A second feature `range_position` (Donchian/stochastic channel position, bounded [0,1]) + one demonstrating spec (`range-floor-accumulation-...`) landed as commit `5fbb5fc`, on top of bb_width. Same pattern (feature in backtest.py `_BAR_TA_FEATURES`/`_feature_matrix`/`_range_position` + registry line + seed-script spec + `tests/test_range_position.py`). 8 unit tests total (bb_width+range_position), seed script validates 10/10, registry↔route guard green at the committed state. NOTE: a concurrent OSINT agent committed `a903964` (perp-basis) BETWEEN my two commits and is editing `feature_registry.py`/`store.py`/`catalog.py` etc.; I staged ONLY my `range_position` hunk (via `git apply --cached`) so my commit does NOT contain their insider_buy_ratio/jet_colocation/sec_edgar work — verified `git show 5fbb5fc` is clean. Their uncommitted work remains in the working tree, preserved.

---

## TL;DR for the next agent

A self-contained, additive change inspired by a grid-bot trading video. It adds **one new bar-TA feature** (`bb_width` = Bollinger Bandwidth) and **one new strategy spec** that encodes the video's two genuinely-uncovered lessons: (1) enter a mean-reversion trade only inside a *compressed* range (the squeeze), and (2) exit immediately if the range **breaks into a trend** (the "grid bot keeps buying all the way to the floor" failure the video centers on). Everything else from the video was already covered by the existing codebase (verified — see below). The change is low-risk and orthogonal to the rest of the branch's WIP.

---

## What changed (exactly 5 files — the whole commit)

| File | Change |
|---|---|
| `apps/engine/cosmu/data/backtest.py` | `_bb_width()` function (textbook Bollinger Bandwidth = `4·σ/mean`, same rolling window + warmup as `_bb_z`); added `"bb_width"` to `_BAR_TA_FEATURES`; added the `elif name == "bb_width"` branch in `_feature_matrix`. |
| `apps/engine/cosmu/config/feature_registry.py` | `FeatureDefinition(name="bb_width", source="parquet_bars", ...)` — one line, right after `bb_z`. |
| `scripts/seed_inbox_strategies.py` | Appended the new spec dict to `SPECS` (the canonical, validated authoring source). |
| `apps/engine/strategies/inbox/bollinger-squeeze-release-reversion-regime-break.json` | The generated inbox spec (written by `python3 scripts/seed_inbox_strategies.py --write`). |
| `apps/engine/tests/test_bb_width.py` | 4 unit tests: math vs textbook, flat-basis/zero-mean guard, registry↔route coherence, end-to-end spec validate+compile+materialize. |

The spec (`lane="gate"`, 4h crypto):
- **Entry:** `bb_width < squeeze_ceiling` AND `bb_z < bbz_floor` (washout inside a squeeze).
- **Exit signals:** `bb_z > bbz_exit` (reverted — take it) OR `adx > adx_break` (**regime break — bail**, the video's missing exit).
- All thresholds are `ParamRef`s in `param_space` — no magic numbers.

---

## Verification done

- `python3 scripts/seed_inbox_strategies.py` → **9 valid, 0 invalid** (the new spec compiles + passes `static_check`).
- `pytest tests/test_bb_width.py` → **4 passed**.
- `_bb_width` math hand-checked against `4·pstdev/fmean`; warmup `None`s correct.
- Registry↔route guard (`feature_names() − (PRICE_FEATURES | _STORE_PROVIDER_OF)`) → **empty** (no dead feature).
- `bb_width` confirmed in `_BAR_TA_FEATURES`, `PRICE_FEATURES`, and `feature_names()` (enabled).

## Verification NOT yet done (next agent should finish)

- **Full engine suite not run to completion.** I started a workflow for it but stopped it at the checkpoint. Run: `cd apps/engine && python3 -m pytest -n auto --dist=loadfile -q` (redirect to a file, read the tail — it's slow).
- **Adversarial review workflow was stopped before completing** (math / coherence / spec-novelty dimensions). Optional to re-run; the change is small and the manual checks below cover the same ground.

---

## Important context / decisions (so you don't re-litigate)

1. **Only ONE spec, not four.** My first plan was 4 mean-reversion specs. I verified the inbox **already** contains the others (`theory-bollinger-washout-reversion-in-chop.json` *is* the bb_z+adx-low reversion; plus `bollinger-z-score-washout-reversion`, `theory-adx-bbz-confluence`, `theory-mean-reversion-fade-of-upside`). Adding near-dups would trip the **novelty gate** (hard-reject for agent batches) and violate the clean-architecture bar. The kept spec is the only one that is genuinely distinct: it uses `bb_width` (new feature, used by ZERO other spec) and an **adx regime-break signal-exit** (no existing reversion spec has this).

2. **Pre-existing test failures are NOT mine.** `tests/test_flywheel_authoring_and_api.py` has ~20 failures (`KeyError: 'has_paper_fills'` / `missing or invalid x-api-key`). **Proven pre-existing** on the clean branch (reverted my changes, re-ran → still fails). It's an API-auth / leaderboard-contract issue on `feat/rho-bar-wiring`. **Open question for the master agent:** does it also fail on `origin/main`? If yes → not a merge blocker. If it passes on main → this branch has a separate regression to fix before merge (unrelated to bb_width).

3. **An out-of-scope revert was undone.** Running `--write` re-serialized `funding-reset-reversion-uncrowded-oversold.json` to an older `funding_ceiling` range (someone had hand-tightened the deployed JSON to `[-0.0001, 0.0001]` without updating the seed script). I `git checkout`-restored that file — my commit does NOT touch it. **Latent coherence bug to flag separately:** the seed script's `funding_ceiling` (`0.0..0.005`) no longer matches the deployed JSON (`-0.0001..0.0001`). Decide which is canonical and reconcile in a separate change.

4. **Stray files in the working tree are from OTHER parallel agents — do not attribute them to this change.** As of checkpoint, uncommitted/untracked strays present: `scripts/ingest_hyperliquid_bars.py` (M), `apps/engine/cosmu/data/sources/jet_colocation.py`, `apps/engine/cosmu/data/sources/sec_edgar.py`, `apps/engine/tests/test_jet_colocation.py`, `apps/engine/tests/test_sec_edgar.py`, `docs/research/ASTRO_ULTIMATE_DEEPDIVE_PLAN.md`. My commit was scoped with explicit `git add` of the 5 files only — these strays were left untouched for their owners.

---

## What to do next (master agent)

1. Decide the merge path for the `bb_width` commit (it's isolated and cherry-pickable):
   - Confirm whether the `test_flywheel_authoring_and_api.py` failures pre-exist on `origin/main` (see #2 above). They are independent of this commit either way.
   - Run the full engine suite; confirm no failures *outside* `test_flywheel_authoring_and_api.py`.
   - Merge / cherry-pick the `bb_width` commit to `main` (and integrate the other parallel agents' work as you see fit).
2. (Optional, propose-only) The spec is `lane="gate"` — it will be screened by the unchanged honest Gate. A **0-survivor outcome is expected and correct** (the Gate is locked-strict by design). The value is the new `bb_width` feature now available to the whole feature vocabulary + a clean, video-faithful hypothesis in the cohort. To run it: `scan_inbox` / the standard inbox→FarmLoop→BH-FDR path picks it up automatically.
3. The "heavy-compute cross-asset sweep" from the original plan (Binance top-N × the squeeze spec on Modal) was **scoped out** of this checkpoint — it's an *operation*, not code. Trigger it separately if you want the empirical read on which symbols (if any) the squeeze edge holds on.

## How to adapt / extend
- `bb_width` is a generic feature — any future spec can reference it (`{"feature": {"name": "bb_width"}, "op": "lt", ...}`). It's bar-computed, PIT-safe, dimensionless (comparable across assets).
- To add a sibling spec, edit `scripts/seed_inbox_strategies.py` `SPECS`, run `--write`, and keep it structurally distinct (different feature set / exit) to clear the novelty gate.
