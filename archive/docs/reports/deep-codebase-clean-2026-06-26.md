# Deep codebase-cleanliness review + uncommitted-work disposition — 2026-06-26

READ-ONLY review. Branch `docs/deep-codebase-clean` off `origin/main` (`588b935`). Nothing executed,
nothing deleted, nothing written to the operator's checkout `<repo>`. This report flags;
it does not remove (per *build-free / delete-nothing / keep-old-code-for-reference*).

---

## TL;DR (the four deliverables)

1. **Cleanliness verdict: GREEN / healthy.** The engine is large but *cohesive*, not god-objected. Only
   ~327 LOC of genuinely dead research code, 6 TODO markers total, zero commented-out dead-code blocks.
   The one real structural debt is **~3.2 KLOC of copy-paste boilerplate across the 11 `equity_*_arm.py`
   files** — medium risk, medium effort, incremental fix. Everything else is "monitor / acceptable".

2. **Full-clean integration of the wip work: NOT possible as a merge, and NOT needed.** The operator's
   99 uncommitted files are a **stale 2026-06-16 working tree that has ALREADY been merged to main via PRs.**
   Of 99 files: **66 are byte-identical-to-main or already-on-main no-ops; 21 modified files are the
   PRE-merge (older) versions that would REVERT 247 commits / 10 days of work (incl. the BRUT model);
   only ~12 files carry genuinely-new forward intent** (the Polymarket prediction lane). The branch
   `feat/rho-bar-wiring` has **zero own commits** — its namesake (rho_bar #272) is already on main.

3. **Priority: LOW. Do the 30-minute forward-salvage, then ship edge/LLM/Polymarket work.** There is no
   "integration project" here. The correct move is to *abandon the stale branch* and cherry-pick the
   ~12 forward files into a fresh branch off current main. Do not rebase, do not replay the diff.

4. **wip integration headline:** **Salvage the Polymarket prediction lane (3 inbox specs +
   `scripts/research/` + 5 research docs); drop everything else as already-merged-or-reverting.**

---

## PART 1 — CODEBASE CLEANLINESS (current `origin/main`)

Scope scanned: `apps/engine/cosmu` (386 `.py`, 293 tests), `apps/web` (TS/TSX). Method: size distribution,
import-graph (`git grep`), marker sweep, god-file concern analysis.

### Cleanliness verdict: **GREEN.** Real, well-factored core; debt is concentrated and low-risk.

Evidence the hygiene is good:
- **6 TODO/FIXME markers total** in the entire engine (2 in `costs/fetchers.py` billing-API stubs,
  4 in `data/sources/xai_twitter.py` influencer-store stub). No FIXME/XXX/HACK/DEPRECATED.
- **Zero commented-out live-code blocks** (matches were docstring pseudocode).
- The four biggest files are **cohesive-but-large, not god-objects** — each solves ONE problem.

### Top debt items (ranked by risk × effort)

| # | Item | Files / LOC | Risk | Effort | Disposition (flag only) |
|---|------|-------------|------|--------|--------------------------|
| 1 | **`equity_*_arm.py` boilerplate** — every arm re-implements `_minimal_spec / _routing_spec / _backtest_row / _existing_version / arm() / mark() / main()`. No shared base class (only `_arm_regimes.py` regime helper is factored). | 11 files, ~3.2 KLOC | MED | MED | Extract an `_ArmBase`/template; migrate pair-by-pair (daa+paa first). Reduces ~120 LOC/arm → ~30 + base. Lets lane/spec-schema changes land in one place. |
| 2 | **Dead research scripts** — `research/equity_faded_backfill.py` (251) + `research/social_nonobvious_cohort.py` (76): no importer anywhere. | 2 files, 327 LOC | LOW | LOW | Move to `research/archive/` (NOT delete). Preserves reference, de-clutters the active dir. |
| 3 | **Confusing inverse-name pair** — `strategy/agent_author.py` (55, the persist site) vs `strategy/author_agent.py` (238, the authoring entrypoint). Both real and complementary, but the word-swap names are a readability trap. | 2 files | LOW | LOW | Rename one for clarity (e.g. `author_agent.py` → `agent_authoring.py`) OR add a one-line cross-reference header. Do not merge them — distinct responsibilities. |
| 4 | **`agent_*` LLM lane functional-isolation** — `agent_{author,decision,executor,loop,run,spec}.py` (~371 LOC) wired only via `lab/nlp_intake.py`, `strategy/author_agent.py`, and `remote/app.py` (observe-only, $0). Not in the autonomous-arming critical path yet. | 6 files | LOW | — | Monitor. Not dead, not duplicated. Promote to first-class lane only if NL-intake usage grows. |
| 5 | **God-file watch (no action)** — `data/backtest.py` (1625), `lab/finder.py` (1062), `research/gate.py` (1059), `evolution/loop.py` (997). Each is cohesive (one job: simulate / search / prove-edge / breed-population). | 4 files | LOW | — | Acceptable. Do not split pre-emptively; revisit only if a second concern creeps in. |
| 6 | **Two `loop.py` (NOT a problem)** — `evolution/loop.py` (breed+gate population) vs `orchestrator/loop.py` (post-gate fund+mark). Complementary, zero code overlap. | — | NONE | — | None. Naming is clear in context. |

### What a "clean build" looks like (target, no deletions)
- One `_ArmBase` collapses the 11 arms; `research/archive/` holds the 2 orphans for reference.
- The `agent_*` lane either grows into the critical path or stays a clearly-labelled offline lab tool.
- Big-4 files stay as-is (cohesive). Net effect: a ~3 KLOC-smaller *active* surface, same capability,
  same reference history retained.

---

## PART 2 — THE 99 UNCOMMITTED FILES (full disposition)

### The decisive fact

`feat/rho-bar-wiring` HEAD **is** the merge-base `9d58c7a` (2026-06-16 21:16). **The branch has ZERO own
commits.** All 99 changes are *uncommitted working-tree* edits sitting on a 10-day-old snapshot of main.
`origin/main` has advanced **247 commits** since. The branch's namesake — rho_bar wiring — is already on
main (`25a823b` + fix `89654c3`).

### Exact classification (verified file-by-file vs current `origin/main`)

| Bucket | Count | Meaning | Disposition |
|--------|------:|---------|-------------|
| Modified, **identical to main** | 32 | byte-for-byte already on main | **no-op — drop** |
| Modified, **differs (= older/pre-merge)** | 21 | operator's version is the PRE-merge one; applying = REVERT | **drop-as-superseded (DO NOT replay)** |
| Deleted, **already gone on main** | 2 | refactor already shipped | **no-op — drop** |
| Untracked, **already on main** | 32 | landed via PRs (agent_*, disconfirmers, operating_costs, migrations, cost-register/fx/lifecycle/equity-panel, agentic-lane.md, 16 tests …) | **drop-as-superseded** |
| Untracked, **genuinely NOT on main** | 9 | true forward intent | **keep-and-integrate / judgement** |
| Untracked dirs | 3 | local artifacts + research scripts | see below |

### The revert hazard (why "just commit the wip" is dangerous)

The 21 differing modified files are smaller/older than main. Applying them as a patch un-does merged work:

| File | Δ vs main | What it reverts |
|------|-----------|-----------------|
| `lab/finder.py` | **+392 / −509** (945 vs 1062 lines) | Pre-**BRUT** finder. `grep -i brut` → present on main, **absent in operator WT**. Replaying drops the BRUT per-combo model. |
| `evolution/loop.py` | **+229 / −421** | Pre-merge FarmLoop (CSCV-PBO clustering etc.). |
| `master/cohort.py` | **−52** (pure deletion) | Removes cohort logic that the gate-integrity work added. |
| `research/equity_*_arm.py` ×14 | various | Pre-`_arm_regimes.py`-shared-helper versions → re-duplicates boilerplate. |
| `config/feature_registry.py`, `api/*`, `costs/*`, `web/*` | various | Pre-merge versions of files whose newer form is on main. |

**Mechanism rule: never `git checkout feat/rho-bar-wiring -- .` and never replay the diff. Both revert main.**

### The genuinely-forward salvage (the only thing worth integrating)

All 9 not-on-main files + `scripts/research/` are the **Polymarket prediction lane** (memory: Edge #1, the
UNLOCK = ingest historical Polymarket odds). They are additive and do not touch the gate/finder.

**KEEP — integrate (low risk, additive):**
- `apps/engine/strategies/inbox/prediction-favorite-bias.json` — well-formed StrategySpec, longshot-favorite
  bias (Whelan 2025), Polymarket venue, has a disconfirmer, no magic numbers (fit from param_space). ✅
- `apps/engine/strategies/inbox/prediction-odds-momentum.json` — odds-momentum spec. ✅
- `apps/engine/strategies/inbox/prediction-odds-reversion.json` — odds-reversion spec. ✅
- `scripts/research/` (4 files: `polymarket_backfill_db.py`, `polymarket_edge_probe.py`,
  `polymarket_ingest.py`, `run_prediction_specs.py`) — Polymarket research tooling; `scripts/research/` is
  **not on main at all**. ✅ (verify imports resolve against *current* main, not the stale finder.)
- 5 research docs (additive, no code risk): `docs/HANDOFF_ARCHITECTURE_AUDIT.md`,
  `docs/HANDOFF_PER_SYMBOL.md`, `docs/research/ASTRO_ULTIMATE_DEEPDIVE_PLAN.md`,
  `docs/research/HANDOFF_polymarket_2026-06-21.md`, `docs/research/idea_intake_2026-06-21.md`. ✅

**NEEDS HUMAN JUDGEMENT (1 file):**
- `apps/engine/tests/test_farmloop_cscv_pbo.py` — main has `test_farmloop_holdout_oneshot.py` (CSCV-PBO #289
  shipped) but NOT this exact test. It imports `CLUSTER_CORRELATION, Candidate, FarmLoop` from
  `evolution.loop` and `cluster_representatives, cohort_cscv_pbo` from `master.cohort`. **Run it against
  current main before keeping** — it was written against the operator's older loop/cohort and may assert
  on signatures that have since changed. If it passes → keep (extra coverage). If it fails → it's stale,
  drop it (the holdout-oneshot test already covers the concern).

**DROP / LOCAL-ONLY (do not commit):**
- `PDFs/`, `mockups/` — local binary/asset scratch, not source. Leave in the operator's checkout, gitignore-worthy.

---

## Is a FULL CLEAN integration POSSIBLE?

**No — and that is the right answer.** "Full clean" of these 99 files would mean reconciling a 10-day-old
working tree against 247 newer commits, file-by-file, where 87 of 99 files are *already on main or would
revert it*. That is not a clean integration; it is a manual un-revert of nearly the whole diff for a ~12-file
payoff. The wip work is **not lost** — it is on main (via PRs) plus snapshotted to `origin/wip/snapshot-2026-06-26`.

The only forward content is the Polymarket lane, and it is **isolated and additive** — so it cherry-picks
cleanly onto current main without any reconciliation. That IS the clean path.

---

## PRIORITY (honest)

**LOW.** Ranked against the live roadmap (edge-hunt, LLM research lane, Polymarket ingest):

- The wip "integration" is a ~30-minute salvage, not a project. Do it once, then forget the stale branch.
- The Polymarket *specs/scripts* inside the salvage ARE aligned with the #1 edge lane — so the salvage is
  worth doing *because* it advances Polymarket, not because the branch needs rescuing.
- The PART-1 cleanliness debt (#1 arm boilerplate) is real but non-urgent: it costs diff-surface, not money
  or correctness. Schedule it behind shipping. Items #2/#3 are cheap and can ride along with any arm work.
- Net: **ship edge/LLM/Polymarket; fold the salvage into the Polymarket work; defer the arm refactor.**

---

## STEP-BY-STEP integration plan (greenlight required — NOT executed)

Goal: capture the ~12 forward files, abandon the revert risk, leave main green. Run in a worktree off
current `origin/main` (never in `<repo>`).

1. **Branch fresh off current main** (NOT a rebase of `feat/rho-bar-wiring`):
   `git fetch origin && git switch -c feat/polymarket-prediction-lane origin/main`

2. **Copy ONLY the forward files** from the snapshot (use the snapshot, not the working tree, for provenance):
   - `git checkout origin/wip/snapshot-2026-06-26 -- apps/engine/strategies/inbox/prediction-favorite-bias.json apps/engine/strategies/inbox/prediction-odds-momentum.json apps/engine/strategies/inbox/prediction-odds-reversion.json`
   - `git checkout origin/wip/snapshot-2026-06-26 -- scripts/research/`
   - `git checkout origin/wip/snapshot-2026-06-26 -- docs/HANDOFF_ARCHITECTURE_AUDIT.md docs/HANDOFF_PER_SYMBOL.md docs/research/ASTRO_ULTIMATE_DEEPDIVE_PLAN.md docs/research/HANDOFF_polymarket_2026-06-21.md docs/research/idea_intake_2026-06-21.md`
   - **Explicitly do NOT** `git checkout` any of `lab/finder.py`, `evolution/loop.py`, `master/cohort.py`,
     `research/equity_*_arm.py`, `config/feature_registry.py`, `api/*`, `costs/*`, `web/*`, the `agent_*`
     files, the migrations, or the 32 already-on-main tests. Those are merged or reverting.

3. **Judgement file:** copy `apps/engine/tests/test_farmloop_cscv_pbo.py`, then run it:
   `pytest apps/engine/tests/test_farmloop_cscv_pbo.py -q`. Pass → keep. Fail (stale signatures) → `git rm`
   it and rely on `test_farmloop_holdout_oneshot.py`.

4. **Verify imports of the scripts** resolve against current main (the scripts were written when the local
   finder was older): `python -c "import ast,sys; [ast.parse(open(f).read()) for f in __import__('glob').glob('scripts/research/*.py')]"` and a quick `pytest -q` of the inbox specs through the normal spec-validation
   path (the `strategize`/`create-strategy` lane) before trusting them.

5. **Green gate, then PR:** `pnpm verify` (or the engine subset) → push `--no-verify` if only env-tests fail
   → `gh pr create --base main`. Keep the PR small (Polymarket lane only).

6. **Abandon, do not merge, the stale branch.** `feat/rho-bar-wiring` and the working tree have no remaining
   value once step 2–4 land — its code is on main, its forward bits are now salvaged. The
   `origin/wip/snapshot-2026-06-26` branch remains as the safety net. (Optionally delete the local stale
   branch later; nothing depends on it.)

### One-line summary the operator can act on
> Don't integrate the wip — it's already on main and would revert. Cherry-pick the 3 Polymarket specs +
> `scripts/research/` + the 5 docs onto a fresh branch off current main, vet the one farmloop test, ship it
> as the Polymarket lane, and abandon `feat/rho-bar-wiring`.

---

## Appendix — how this was verified (read-only)

- Branch has no own commits: `git log 9d58c7a..feat/rho-bar-wiring` → empty; HEAD == merge-base `9d58c7a` (2026-06-16).
- main advanced 247 commits since: `git rev-list --count feat/rho-bar-wiring..origin/main` → 247.
- rho_bar already on main: commits `25a823b` (wire) + `89654c3` (fix); `grep rho_bar` present in main's cohort path.
- BRUT present on main / absent in operator WT: `git grep -il brut origin/main -- lab/finder.py` hits;
  `grep -il brut` of the operator working `finder.py` → no match. Line counts 1062 (main) vs 945 (WT).
- Per-file bucketing done in Python (hash-compare working tree vs `origin/main`, `git cat-file -e` for existence)
  → 32 identical / 21 differ / 2 deleted-gone / 32 untracked-on-main / 9 untracked-not-on-main / 3 dirs.
- Cleanliness: import-graph via `git grep`; god-file concern review; marker sweep
  (`git grep -nE 'TODO|FIXME|XXX|HACK|DEPRECATED'` → 6 hits).
