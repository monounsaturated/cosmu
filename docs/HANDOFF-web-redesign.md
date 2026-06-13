# Handoff — web redesign (frontend) → local build

> Written 2026-06-13 at the end of the cloud design session. Branch: `claude/adoring-darwin-5o11r4`.
> This branch now contains **the final design mockup + the latest `main` backend merged in**, so a
> local session can check it out and have everything (mockups as reference, contracts to bind to,
> `.env.local` for real APIs / modal). Goal of the next step: port the locked design into `apps/web`.

## 1. The locked design

**`mockups/cosmu-final-v12.html`** is the reference (self-contained HTML; open in Chrome).
It is the consolidation of the whole session. Key decisions already baked in:

- **5 pages**, sidebar order **Live · Paper · Strategies · Costs · Commands**, default landing = **Live**.
- Obsidian-Iris tokens (purple). Brand name still "Cosmu" in this file; name/colour exploration lives in
  `mockups/brand-*.html` (grovepool / thorow × green/orange/steel/iris/mocha/darkred/navy/black/revolut)
  — pick one before building if a rebrand is wanted.
- **Strategies**: one JS-rendered table over a `COLS` config — sortable, **drag-to-reorder headers**,
  **column picker** (cp1 = checkbox + row-highlight; whole row clickable) with a **Reset-to-default**
  button, real **horizontal scroll** when wide. Optional columns off by default: Venue, Fees, Origin.
  Row click → **side panel** (the strat sheet).
- **Strat sheet** (side panel, 720px / 54vw): stage badge + Stop/Start; money-band; **interactive
  phased equity chart** (Backtest/Paper/Live; phases never reached are greyed/disabled; hover crosshair);
  **AI summary** (badge = the model name, e.g. "Sonnet 4.6" — local, no API fees); gate chips; phase
  comparison; trades; data feeds; activity.
- **Live / Paper dashboards**: chart on top (interactive, hover) → KPI row (Live folds the 3 guardrails
  as small boxes into the KPI line) → `[ Open positions | Recent trades ]` side-by-side, each with its
  own **See all** toggle (independent — `align-items:start`).
- **Costs**: expense-tracker model with real-date logic (lifetime since day 1, run-rate, renewals,
  flat calendar in Add-cost). Chart on top.
- **Sizing**: `zoom:1.08` (mild, a touch bigger), responsive — collapses the sidebar to icons (labels
  hidden) and stacks grids on narrow / half-width windows. iOS/Safari pass still TODO.
- **Device-adaptive defaults (already wired):** the **theme follows the OS** `prefers-color-scheme` on
  load AND live (until the user manually toggles); the layout adapts to window width via the media
  queries. In the web port, replace the `zoom` shortcut with a rem/spacing **scale token** so size scales
  with the device/user font-size preference rather than a fixed CSS zoom.

## 2. Design requirements still to apply (operator, 2026-06-13) — fold into the web port

These are now reflected in the v12 mockup (reference); implement them in `apps/web` too (and/or patch the mockup if iterating there):

1. **OOS must show its window, not just a %.** Out-of-sample is "`+8.2%` **over <period / N trades>**".
   Surface the duration next to the OOS return on the **strat sheet** (gate OOS chip + the phase-comparison
   Backtest column) and a compact hint in the table — keep it uncluttered. Needs an `oos_window` field
   (e.g. months or trade count) added to `LeaderboardRow` (backend) — today the mock has only `oos:'+8.2%'`.
2. **Always show `$` on dollar values.** Anywhere a dollar evolution sits next to an absolute sum, render
   `+$24`, never `+24`. Audit the Paper/Live dashboards + strat pages; e.g. paper "Recent trades" P&L
   currently shows `%` only — show the **$** (and % alongside). Absolute sums + their $ and % delta together.
3. **Strat-sheet "Recent trades" needs the time** next to the date (the Paper/Live dashboard trade tables
   already do — `Jun 12 · 14:22`). Add the same to the sheet's trades table.
4. **Costs chart = the dashboard equity chart, exactly.** Same component: **timeframe segmented control
   (7D/30D/All)**, same height/markup/hover/headline scrub. Today the costs chart is the simpler
   `curveInto` variant (hover, no timeframe). Reuse the dashboard `equityBlock`+`mkChart` engine, feeding
   it the cumulative-spend series sliced by timeframe.

(Everything else in §1 is considered final by the operator.)

## 3. How to build it — bind to contracts that already exist

The compatibility audit is **`docs/epics/web-redesign-compat.md`** — read it first. Verdict there:
~90% of the design binds to endpoints that exist (`/leaderboard`, `/strategy/{id}`, `/overview`,
`/blocks`, `/costs`, …). The four real backend gaps it lists (live/sim money split, `value_usd` on
LeaderboardRow, real liquidate-sells, pause-paper endpoint) plus the new `oos_window` field (req. #1)
are the additive backend work. Routes: `/live`,`/paper`,`/strategies`,`/costs`,`/commands`
(redirect the folded pages). Regenerate `@cosmu/contracts-ts` after any LeaderboardRow additions; never
hand-type. Use `html.light` for the light theme; replace the mockup's `zoom:1.05` with a rem/scale token
(CSS `zoom` is a mockup shortcut).

## 4. Repo / merge state (READ — needs verification before main)

- This branch = **`origin/main` merged in** (commit `a5885c2`). The merge had 6 conflicts, all the same
  shape (an early `forward_test → paper` rename on this branch vs `main`'s newer, tested code). **I took
  `main`'s side for every conflict region** (its code is newer and CI-tested), so the rename is ~95%
  auto-merged with a few cosmetic `forward-test` wordings left in comments/CLI/docs.
- **I could NOT run the test suite in the cloud env (no pytest).** Resolved Python compiles and
  `openapi.json` is valid JSON, but the merge is **not test-verified**. Before this goes to `main`:
  run `pnpm verify` / the engine `pytest` locally (or via CI on a PR), fix any residue, and do a quick
  cosmetic pass to finish the `forward_test → paper` wording the operator asked for.
- The substantive backend on this branch (besides the rename) is the **building-block registry**
  (`cosmu/strategy/blocks.py`, `knowledge/block_registry.py`, `api/routers/blocks.py`, the two
  `2026-06-11_*` migrations, `tests/test_blocks.py`) — that auto-merged cleanly.

## 5. Recommendation on merging

- For the **local build itself, merging to `main` is NOT required** — work on this branch: it already
  has the mockups (reference) + `main`'s backend + contracts, and your `.env.local` gives modal/API access.
- When the web port is ready, land it via a **PR to `main` so CI runs the full verify** (the test
  verification I couldn't do here) — that's the safe gate, and it lets the other (backend) agent see the
  `forward_test → paper` rename. Don't force-push this merge straight to `main` unverified.
