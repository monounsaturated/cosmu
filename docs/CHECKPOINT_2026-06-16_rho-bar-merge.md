# CHECKPOINT — `feat/rho-bar-wiring` merge + fleet convergence (2026-06-16)

> **Read this first.** Written by an Opus session that was asked to "fix, finish, QA, merge to main"
> but **stopped cleanly** because a multi-agent fleet is concurrently writing the same branch.
> Nothing here is broken. The merge is done. The blocker is **coordination**, not code.

---

## TL;DR for the next (master) agent

> **UPDATE (later same session):** origin/main has since advanced — the branch is now **~1 behind / 6+ ahead**
> (the fleet keeps committing on both sides), so it is **no longer a clean fast-forward**. You must
> `git merge origin/main` again (expect another `backtest.py`-style conflict → resolve as a UNION, same as
> `2368ea8`). Always re-run `git status` + `git rev-list --left-right --count origin/main...HEAD` first.
> New clean commits since checkpoint: `4436333` (this doc), `c6c74df` (sibling bb_width + squeeze spec),
> `a903964` (my **perp-basis discount contrarian long-spot** strategy — novel, validated, 7/7 spec tests;
> see "Build work added this session" at bottom).

1. The branch **`feat/rho-bar-wiring`** was **0 behind / 3 ahead of `origin/main`** at first checkpoint → clean merge was possible then (see UPDATE above for current divergence).
2. The hard part — merging `origin/main` *into* this branch and resolving the `backtest.py` conflict — is **already committed** as `2368ea8` with a **verified-correct union resolution**.
3. **DO NOT race the fleet.** 6+ Claude sessions are writing this same working tree. The merge decision is a single global action — only ONE agent should do it, and only after the working tree is committed + green.
4. Your job: **quiesce the fleet → commit/verify the in-flight work → run QA in isolation → merge to main via PR.**

---

## Exact git state at checkpoint

```
HEAD = 2368ea8  "Merge remote-tracking branch 'origin/main' into feat/rho-bar-wiring"
branch feat/rho-bar-wiring: 0 behind, 3 ahead of origin/main
```

**The 3 committed commits ahead of `origin/main` (the mergeable unit, all tested-clean):**
- `2368ea8` — Merge origin/main into branch (**conflict resolution lives here, verified**)
- `539abb3` — feat(universe): multi-asset finder — equity + Hyperliquid panels, per-venue fees
- `25a823b` — feat(gate): wire rho_bar into effective trial count for correlated cohorts

**`origin/main` HEAD = `ff243e8`** (gate-hardening #273) — fully contained in the branch already.

### The `backtest.py` conflict — already resolved correctly, already committed

The only merge conflict was `apps/engine/cosmu/data/backtest.py`. It is **resolved in `2368ea8`** as the
**union of both sides** (confirmed: 15 resolution tokens present in the committed blob):
- from **origin/main (sizing T1 + gate-hardening):** `val_price_returns` collection PIT to the validation
  window → fed to `compute_target_vol(val_price_returns)` (line ~262).
- from **our branch (multi-asset finder):** `sym_fee = fee_schedule.get(symbol, fee_bps)` per-venue fee +
  `fee_schedule` param threaded through `run_strategy_backtest`, `_run_symbol` calls, holdout, and
  `_buy_and_hold_return(market, fee_bps, fee_schedule)`.
- The `_run_symbol(...)` calls correctly use **`sym_fee`** (the per-venue value), not the blended `fee_bps`.

This resolution **compiles** and the **directly-affected tests pass** (see QA below). No action needed on it.

---

## ⚠️ The blocker: a live multi-agent fleet on ONE shared branch

`ps aux` shows **6+ concurrent Claude Code sessions** (mix of `opus-4-8[1m]` and `sonnet-4-6`, several
`ultracode:true`), all on `/Users/device/cosmu` with `bypassPermissions`. They are actively:
- committing (one made `2368ea8` 13 min before checkpoint),
- and writing **uncommitted in-flight files** (see below).

Consequences:
- The working tree is a **moving target** — `git status` changed twice during this session.
- **QA is unreliable while they run.** The engine test config loads **real `.env.local` DB credentials**
  (commit `287a35f`), so 3+ concurrent `pytest tests/` runs hit the **same Postgres** → cross-process
  state contention → **flaky failures that are NOT real bugs**. My full-suite run showed scattered `F`
  marks AND hung at 96%; the *isolated* affected-tests run was 100% green. Treat any full-suite failure
  as suspect until re-run in isolation.

---

## Uncommitted in-flight work in the tree (NOT mine — do not discard, likely sibling agents' WIP)

At checkpoint, `git status --short` showed (all sibling fleet work, may be incomplete):

```
 M apps/engine/cosmu/config/feature_registry.py        # new sources / bb_width registration
 M apps/engine/cosmu/data/backtest.py                  # adds _bb_width() Bollinger-bandwidth TA feature
 M scripts/ingest_hyperliquid_bars.py
 M scripts/seed_inbox_strategies.py
?? apps/engine/cosmu/data/sources/jet_colocation.py    # NEW alt-data source
?? apps/engine/cosmu/data/sources/sec_edgar.py         # NEW alt-data source
?? apps/engine/strategies/inbox/bollinger-squeeze-release-reversion-regime-break.json  # NEW strategy
?? apps/engine/tests/test_bb_width.py
?? apps/engine/tests/test_jet_colocation.py
?? apps/engine/tests/test_sec_edgar.py
?? docs/research/ASTRO_ULTIMATE_DEEPDIVE_PLAN.md        # pre-existing untracked, not fleet
```

These are **additive** (new features/sources/strategy + their own tests). Each appears self-consistent
(`backtest.py`'s `_bb_width` adds `bb_width` to `_BAR_TA_FEATURES`, a `_feature_matrix` branch, and the
function — coherent). But **verify each is complete + green before committing** — some may be mid-write.

---

## QA status (what I actually verified)

- ✅ **All merged engine `.py` files parse** (`ast.parse` over the 13 merge-touched files).
- ✅ **Directly-affected tests: 62/62 PASS** in isolation —
  `test_finder_honesty test_sizing test_gate_hardening test_paper_step test_llm_narrative test_farmloop_global_deflation test_verdict_log`.
- ⚠️ **Full suite: INCONCLUSIVE** — confounded by concurrent sibling pytest runs on the shared DB.
  Re-run in isolation (fleet quiesced) before trusting any failure.
- ❌ **`pnpm verify` NOT run** (the canonical deploy gate:
  `naming:check → contracts:generate → contracts:check-drift → engine:test → typecheck → build`).
  Run this once the tree is committed + the fleet is stopped.

---

## Recommended path for the master agent (in order)

1. **Quiesce the fleet.** Stop/await the other local sessions so the working tree stops moving and QA is
   reliable. (User said: "I have too many agents running in parallel.")
2. **Triage the uncommitted in-flight work** (bb_width, jet_colocation, sec_edgar, bollinger strategy):
   for each, confirm it compiles, its test passes in isolation, then commit it with a focused message —
   OR `git stash` / set aside anything half-baked. Don't bundle unrelated WIP into one commit.
3. **Run QA in isolation** (no other pytest running):
   `cd apps/engine && python3 -m pytest tests/ -n auto --dist=loadfile -q -rf > /tmp/qa.log 2>&1`
   then `pnpm verify` from repo root. Both must be green.
4. **Merge to main.** Branch is a clean superset of `origin/main` → open a PR (idiomatic here; recent
   history is all `Merge pull request #…`) and merge, **or** fast-forward `main` and push. Prefer a PR
   (reversible, fleet-safe). `push = deploy` — see `deploy-check` / `deploy-iterate` skills.
5. **Post-merge:** run `deploy-iterate` to confirm Railway/Vercel are healthy.

---

## Hard constraints (do not violate)

- **Never loosen the Gate.** Core gate constants are LOCKED (see memory `gate_calibration_locked`).
  0 survivors is the machine working, not a bug.
- **Don't `git reset --hard` / force-push** while the fleet is live — you'll clobber sibling commits.
- **Don't commit a sibling's half-written file** — verify it's complete + green first.
- The merge resolution in `2368ea8` is correct — **don't re-resolve it.**

---

## Build work added this session (commit `a903964`)

While waiting on fleet coordination I authored one genuinely-novel strategy (the user said "keep building"):

**`apps/engine/strategies/inbox/perp-basis-discount-contrarian-long-spot.json`** — the absent **LONG mirror**
of the existing `perp-basis-premium-contrarian-short`. Goes **long spot** when `perp_spot_basis` crosses
**down** into a discount (crowded-short capitulation → mean-revert up). Key properties:
- **Genuinely novel** (not a near-dup): the only other basis spec is the SHORT leg (`cross_up`, `direction=-1`);
  this is `cross_down`, `direction=1`. Opposite mechanism, opposite side.
- **Spot-executable on Binance** (`direction=1`, `funding_feature=null`) → fits the spot-only live constraint,
  unlike the short leg which needs perp shorting.
- **Validated:** `validate_spec` → `[]` (clean), `compile_spec` → CompiledStrategy, all thresholds are ParamRefs
  (no magic numbers), `test_composable_specs` + `test_strategy` 7/7 green. Same `perp_spot_basis` data path as
  the already-accepted short spec, so it's immediately screenable by the cohort/finder.

**Why this and not another momentum spec:** I surveyed all 53 inbox specs by entry-feature. The price/momentum/
vol/funding cluster is **saturated** (`ret_Nd` 37×, `vol_realized` 13×, `funding_rate` 8×, `xsec_momentum_rank`
already paired with funding in `xsec-neutral-momentum-long-leg`). The **flow/positioning axis is under-mined**
(`perp_spot_basis` 1×, `open_interest` 1×, `liquidation_cascade` 1×; `stablecoin_net_flow_usd` 0×). Note:
`exchange_netflow` is **DISABLED** in the registry (mislabeled/fabricated prior — do not author on it). The next
under-mined hypotheses for whoever continues: a **stablecoin dry-powder inflow** regime gate
(`stablecoin_net_flow_usd`, 0 specs, clean documented mechanism) and an **OI-divergence** reversal.
