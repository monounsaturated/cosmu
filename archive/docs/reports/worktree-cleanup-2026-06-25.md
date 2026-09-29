# Worktree cleanup triage — 2026-06-25

> **READ-ONLY triage.** No git mutation was performed in any worktree below — every worktree was
> inspected with `git worktree list` + `git status --porcelain` + `git diff` only. The dispositions are
> *recommendations* for the operator to action from the owning worktree (or main), not actions taken here.
>
> Baseline: `origin/main` @ `32d4605` (`fix(sec_edgar): … (#363)`). "Already on main" below means the
> uncommitted change is byte-equivalent to, or fully superseded by, code that is already merged at `32d4605`
> — verified by grepping the merged tree, not assumed.

## Summary table

| Worktree | Branch | Uncommitted content | Already on main? | Recommended disposition |
|---|---|---|---|---|
| `interesting-jemison-b561ec` | `claude/interesting-jemison-b561ec` | paris-beer-weather DataSource + 3 specs + study doc + 8 wiring edits | No | **Discard the code; keep ONLY the study doc** (commit-to-docs). Edge was measured **0/10** and killed. |
| `elegant-jennings-075baa` | `claude/elegant-jennings-075baa` | `zero_capital.py` + `orchestrator/loop.py` edits | **Yes — both** | **Discard.** Both changes are already merged on main. |
| `charming-blackburn-6d6a39` | `claude/charming-blackburn-6d6a39` | `lab/research.py` + `research/fixtures.py` test-fixture edits | No | **Commit (separate engine PR).** Live, coherent BRUT-migration fixture fix; not yet merged. |
| `pedantic-kalam-62a080` | `claude/pedantic-kalam-62a080` | logo/icon/app-shell visual edits | Unverified (visual) | **Stash or commit (separate web PR).** Subjective visual change — needs operator eyeball, not a doc PR. |
| `mystifying-gagarin-5c371d` | `fix/dedup-watch-tracks-per-cell` | `_full_multivenue_sweep.py` (untracked one-off script) | No | **Discard.** Throwaway research-run script with a hardcoded `.env.local` path; not library code. |
| `quirky-austin-f6a067` | `claude/quirky-austin-f6a067` | `docs/epics/copy-trade-lane.md` (untracked) | No | **Commit-to-docs.** Killed-epic record worth keeping (€0 kill rationale + sound design). |
| `peaceful-tesla-a6ad40` | `claude/peaceful-tesla-a6ad40` | 3 polymarket plan docs + `sec_edgar.py` edit | sec_edgar: **Yes (superseded by #363)**; plans: No | **Commit the 3 plan docs; discard the sec_edgar edit** (redundant since #363). |

---

## Per-worktree detail

### 1. `interesting-jemison-b561ec` — paris-beer-weather (MEASURED 0-edge / killed)

**Path:** `<repo>/.claude/worktrees/interesting-jemison-b561ec`
**Branch:** `claude/interesting-jemison-b561ec` (HEAD `db6f596`, no commits ahead of main).

**Uncommitted content:**
- *Modified (8 files, +85 lines):* `config/feature_registry.py`, `data/providers/store.py`,
  `data/sources/altdata_bridges.py`, `data/sources/registry.py`, `data/venue_universe.py`,
  `ingest/catalog.py`, `ingest/run.py`, `spine/venue.py` — the wiring to register a `paris_beer_weather`
  DataSource into the ingest pipeline + feature registry.
- *Untracked:* `data/sources/paris_beer_weather.py` (11.8 KB source), three inbox specs
  (`paris-heat-anomaly-*.json`, `paris-heatwave-extreme-*.json`), `tests/test_paris_beer_weather.py`,
  `scripts/research/beer_weather/` (4 scripts + a `.pyc`), and `apps/engine/docs/research/beer_weather_study.md`.

**Verdict from the study doc:** the edge is **dead**. `beer_weather_study.md` records **0/10 survivors**
(beer 0/7, placebo-control 0/3) through the locked BRUT gate, net of real IBKR equity fees, window
2008→2026. Best name (SAM) hits DSR 0.664 but is killed by `deflated_sharpe` + `buy_and_hold`; all 10 fail.
This matches memory ("MEASURED 0-edge/killed").

**Recommended disposition:** **Discard the source/wiring/specs/scripts** — a 0-edge weather-anomaly source
should not land in the ingest pipeline or feature registry (it permanently widens the feature surface for a
falsified signal, and is exactly the kind of "data-mined weather feature without a prior mechanism" the
research skills warn against). **Keep only the study doc** by copying `beer_weather_study.md` into the repo's
`docs/research/` (commit-to-docs) so the negative result is durable and the experiment isn't silently
re-run. The `__pycache__/*.pyc` is build artifact — never commit it.

---

### 2. `elegant-jennings-075baa` — zero_capital / loop (BOTH already merged)

**Path:** `<repo>/.claude/worktrees/elegant-jennings-075baa`
**Branch:** `claude/elegant-jennings-075baa` (HEAD `da7ae7a`, **44 commits behind** `origin/main`).

**Uncommitted content (2 modified files):**
- `master/zero_capital.py` — adds a `_screened_pool(...)` helper and rewires `_resolve_symbol_venue` to use
  it (inlining the old `orchestrator.loop._screened_symbols` after the BRUT per-cell migration).
- `orchestrator/loop.py` — adds a cell-keyed snapshot fallback in `_update_track_returns` (read the
  cell-keyed `portfolio_snapshots` first when cell columns exist, fall back to the version-keyed series).

**Already on main?** **Yes — both.** Verified against the merged tree at `32d4605`:
- `master/zero_capital.py` already defines `_screened_pool` and calls it at the same site.
- `orchestrator/loop.py` already carries the `has_cell_cols`-gated cell-keyed (`cid`) snapshot read with the
  version-keyed fallback (lines ~527–557).

**Recommended disposition:** **Discard.** This worktree's branch base is 44 commits stale and its
working-tree changes have since been merged to main through other PRs. Nothing here is unique. (No
stash/commit value — keeping it only risks a confusing future re-apply of already-merged code.)

---

### 3. `charming-blackburn-6d6a39` — research fixtures (LIVE, not yet merged)

**Path:** `<repo>/.claude/worktrees/charming-blackburn-6d6a39`
**Branch:** `claude/charming-blackburn-6d6a39` (HEAD `ea7d5ba`, no commits ahead of main).

**Uncommitted content (2 modified files, +23/−6):**
- `research/fixtures.py` — parameterizes `edge_bearing_screen_market(...)` with `up_drift` / `down_drift` /
  `noise` (defaults unchanged) so callers can dial trade density.
- `lab/research.py` — `_EdgeBearingBars` now calls the fixture with a DENSE+LONG preset
  (`n=1000, up_drift=0.006, down_drift=-0.002, noise=0.016`) so each per-combo **BRUT cell clears its own
  30-trade floor** (the old pooled-across-5-symbols count is gone after the BRUT per-cell migration).

**Already on main?** **No.** The merged `fixtures.py` signature is still `(*, seed=3, n=900)` with the
literal `0.004 / -0.001 / 0.012` drifts inline — this change is not present.

**Recommended disposition:** **Commit as a small, separate engine PR.** This is coherent, self-contained,
and genuinely useful — it keeps the offline survivor-track test green under the new BRUT per-cell gate
(otherwise a midpoint trend seed fires only ~27 trades/cell and misses the floor). It is engine test-harness
code, **not docs**, so it does not belong in this docs PR; flag it to the operator as a quick follow-up.
Run `pytest` on the touched test before merging.

---

### 4. `pedantic-kalam-62a080` — logo

**Path:** `<repo>/.claude/worktrees/pedantic-kalam-62a080`
**Branch:** `claude/pedantic-kalam-62a080` (HEAD `2303232`, no commits ahead of main).

**Uncommitted content (3 modified files, +29/−28):** `apps/web/app/icon.svg`,
`apps/web/components/brand/logo.tsx`, `apps/web/components/nav/app-shell.tsx` — a brand/logo visual revision.

**Recommended disposition:** **Stash or commit as a separate web PR — operator decision.** A logo is a
purely subjective visual change that needs a human eyeball (does the new mark look right in the app shell?);
it cannot be auto-dispositioned from a diff and does not belong in a docs PR. If the operator likes it, it's
a clean ~57-line web-only PR; if undecided, `git stash` preserves it without cluttering a branch. No data /
trading / correctness risk either way.

---

### 5. `mystifying-gagarin-5c371d` — sweep script

**Path:** `<repo>/.claude/worktrees/mystifying-gagarin-5c371d`
**Branch:** `fix/dedup-watch-tracks-per-cell` (HEAD `db6f596`).

**Uncommitted content (1 untracked file):** `apps/engine/_full_multivenue_sweep.py` (51 lines) — a one-off
research-run harness that screens every inbox spec through the FarmLoop against PROD from an EU host. It
**reads `DATABASE_URL` by parsing `<repo>/.env.local` directly** and lives at the engine root
(the `_`-prefix marks it as a throwaway).

**Recommended disposition:** **Discard.** This is a disposable research script, not library/product code: a
machine-specific hardcoded `.env.local` path, repo-root placement, and a `_`-prefixed throwaway name. It
should never be committed (committing a script that parses a local secrets file is a footgun). If the *sweep
logic* is worth keeping, it already belongs to the `research-to-cohort` / Modal-sweep skills — re-derive
there, don't preserve this file.

---

### 6. `quirky-austin-f6a067` — copy-trade killed-epic doc

**Path:** `<repo>/.claude/worktrees/quirky-austin-f6a067`
**Branch:** `claude/quirky-austin-f6a067` (HEAD `c45f83c`, no commits ahead of main).

**Uncommitted content (1 untracked file):** `docs/epics/copy-trade-lane.md` (184 lines). Header:
*"Status: ❌ KILLED by backtest (2026-06-20)."* It documents the Fat Pig Signals copy-trade investigation —
1060 signals reconstructed on real Binance prices, **−14.86% alpha vs buy-hold** on the best (BTC/ETH long)
subset, beat buy-hold only 38% of trades; meta-labeling found zero winner/loser separation → nothing to
distill. **Decision: don't pay, don't copy, don't build** — killed at €0 via the Gate's own
`must_beat_buy_and_hold` criterion.

**Recommended disposition:** **Commit-to-docs.** A well-evidenced negative-result epic record is exactly what
the backlog process wants to keep durable (it stops the copy-trade idea from being re-proposed and re-built).
It is not in main's history (verified) and `docs/epics/` already houses epics. This is the kind of doc this
PR could carry — but to keep this PR's scope tight (the social/LLM plan + cleanup report), the
recommendation is to commit it from its own worktree (or fold it into this PR only if the operator prefers a
single docs landing).

---

### 7. `peaceful-tesla-a6ad40` — polymarket plans + sec_edgar dup

**Path:** `<repo>/.claude/worktrees/peaceful-tesla-a6ad40`
**Branch:** `claude/peaceful-tesla-a6ad40` (HEAD `db6f596`, no commits ahead of main).

**Uncommitted content:**
- *Untracked `docs/plans/` (3 files):* `edge-sprint-plan-2026-06-21.md` (16.6 KB — the 80-agent edge-sprint
  implementation plan), `polymarket-edge-findings-2026-06-21.md` (7.9 KB), `polymarket-master-plan-2026-06-21.md`
  (8.2 KB — the build-ready Polymarket plan). All three are substantial, build-ready planning docs **not in
  main's history**.
- *Modified `data/sources/sec_edgar.py` (+10 lines):* strips a leading `xsl…/` directory segment from the
  Form-4 `primaryDocument` so the live path fetches raw XML instead of the XSL HTML rendering.

**Already on main?** **The sec_edgar edit is redundant — superseded by #363.** Verified: `origin/main`
@ `32d4605` IS commit #363, which fixes the *exact same* XSL-prefix bug, but more robustly — it does an
unconditional `doc_name = primary.split("/")[-1]` (strips any prefix, idempotent for bare names) plus three
regression tests, whereas this worktree's diff does a *conditional* `if _head.lower().startswith("xsl")`
strip with no tests. The merged version subsumes it. **The plan docs are not on main.**

**Recommended disposition:**
- **Commit the 3 `docs/plans/*.md` files** (commit-to-docs) — they are the load-bearing Polymarket /
  edge-sprint planning record and directly inform the priority-1 lane (see the companion
  `docs/plans/social-llm-edge-lane.md`, which references them). They land cleanly into the new `docs/plans/`
  directory.
- **Discard the `sec_edgar.py` edit** — #363 already fixes the bug more completely; re-landing this would be
  a redundant, weaker, test-less duplicate.

---

## Net recommendation

| Disposition | Worktrees / files |
|---|---|
| **Commit-to-docs** | `peaceful-tesla` 3 polymarket plans · `quirky-austin` copy-trade epic · `interesting-jemison` study doc only |
| **Commit (separate non-docs PR)** | `charming-blackburn` fixtures (engine) · `pedantic-kalam` logo (web, operator eyeball) |
| **Discard** | `elegant-jennings` (both files already on main) · `mystifying-gagarin` sweep script · `interesting-jemison` source/wiring/specs · `peaceful-tesla` sec_edgar edit (redundant since #363) |

The two safest immediate wins are the **commit-to-docs** set (durable plans + negative-result records, zero
code risk) and **discarding the three already-merged / throwaway** changes. The two engine/web commits
(`charming-blackburn`, `pedantic-kalam`) are real but need their own scoped PRs + a human eyeball, so they
are flagged, not folded into the docs PR.
