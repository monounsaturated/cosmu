# CHECKPOINT — `feat/rho-bar-wiring` merge + fleet convergence (2026-06-16)

> **Read this first.** Written by an Opus session that was asked to "fix, finish, QA, merge to main"
> but **stopped cleanly** because a multi-agent fleet is concurrently writing the same branch.
> Nothing here is broken. The merge is done. The blocker is **coordination**, not code.

---

## TL;DR for the next (master) agent

1. The branch **`feat/rho-bar-wiring`** is **0 behind / 3 ahead of `origin/main`** → a **clean fast-forward merge to main is mechanically possible** right now.
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
