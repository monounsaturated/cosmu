# State of COSMU — 2026-06-06

One clean picture. No spin. Built from a five-dimension audit (codebase, frontend, investigation-agent flow, data, workflow), each rated high-confidence.

---

## 1. ARE YOU OVERTHINKING?

**Partly — yes.** The codebase is in far better shape than the "messy" feeling suggests, and the feeling is being amplified by a few specific things that are loud but localized.

- **The engine core is more coherent than it feels.** 166/177 modules carry an `# intent:` header, 905 tests with **zero** skips/xfails, only 7 debt markers in ~49k LOC, no `_old/_v1/_legacy` graveyards, and the research harnesses genuinely *compose* on one shared backtest engine. This is a disciplined solo codebase, not a dump.
- **The clutter you feel is real but localized.** It lives in three named spots, not everywhere: (a) the *process/docs layer* (4+ docs each claiming to be the "single source of truth", a backlog that contradicts itself in the same file, ~12 handoff rewrites in 14 days); (b) two divergent simulation/cost engines; (c) a half-migrated data layer. The UI is *not* a dump — every heavy page uses progressive disclosure and honest empty-states. Its problem is route/naming sprawl at the seams, not per-page clutter.
- **The genuine overthinking is re-planning instead of running.** 279 commits in 14 days, the same "fix harness → re-run → judge" plan re-authored in 7+ places — while the one action that produces a profit verdict (run the Gate on data already on disk) keeps getting deferred behind a *mis-stated* "bar cache is empty" blocker. **The cache is not empty** (30 symbols × 3 timeframes, ~1004 daily BTC bars, confirmed on disk). You could run the majors Gate today.

Bottom line: stop auditing the engine for messiness — it's fine. The mess is the doc/process layer and two code seams. Fix those, run the experiment.

---

## 2. WHAT WE BUILT

A tired founder's 5-bullet version:

- **An autonomous crypto research-and-trade engine** (`apps/engine`, Python, ~49k LOC) on Binance spot, with a clean separation: `mind`=analysis, `master`=gates/risk, `orchestrator`=tick loop, `spine`=execution, `evolution`=mutation.
- **An honest "edge Gate"** — deterministic code (not LLM-guessed) that backtests a strategy on real Binance bars with real fees, runs purged/embargoed splits and a look-ahead integrity check, and returns PASS/FAIL on *profit net of fees*.
- **An idea→strategy pipeline:** an LLM drafts a loose intuition into a *typed* `StrategySpec` with no magic numbers, then it's forced through the same deterministic Gate. The authoring path consults memory of past kills/winners.
- **A clean data layer:** one declarative catalog of ~48 alt-data features, an append-only point-in-time store (no look-ahead), a build-time guard that fails if a feature is enabled-but-dead, and honest degradation to `[]` when a feed has no key.
- **A lean web app** (`apps/web`) that displays all of this honestly — overview-led, progressive disclosure, real empty-states, Console as its own page — plus solid infra (Railway warm host, Modal burst lane, lean CI).

---

## 3. WHAT'S CLEAN vs WHAT'S MESSY

| CLEAN (keep / trust) | MESSY (real hazards) |
|---|---|
| **Intent headers** on 166/177 modules (`master/risk.py`, `master/holdout.py`) — strongest coherence signal | **Two simulators disagree on profit** — `research/gate.py::_simulate` (5bps flat slip, no impact, fixed stops) vs `data/backtest.py::run_strategy_backtest` (slip 5bps **+** 50bps impact, purged splits). Gate can bless what the live loop can't trade. **Profit-critical.** |
| **905 tests, 0 skips/xfails** across 118 files | **Two parallel data abstractions** — old `data/providers/` + `altdata.py` shim (38 refs) vs new typed `data/sources/` registry (12 refs); same concept duplicated (`providers/prediction.py` AND `sources/polymarket.py`) |
| **Research harnesses compose** on one backtest (`carry_ablation.py`, `funding_crowding_cohort.py`, etc.) | **Pipeline is real, conversation is faked at edges** — UI single-signal Gate (`api/routers/research.py:62`) is hardwired to **synthetic** data; only **6 of ~40** features are computed in the backtest, so most authored specs trade **zero times** |
| **Honest data seam** — declarative catalog, append-only PIT store, registry↔route build guard, `verify` look-ahead check | **Prod ingest is BTC/ETH-only** (`ingest/run.py:60` `DEFAULT_SYMBOLS`); 28 of 30 universe symbols get no alt-data refresh. **Cron never backfills bars** — caches silently rot |
| **UI progressive disclosure + honest empty-states** everywhere (`app/lab`, `app/mind`, `app/strategy/[id]`); Console its own page | **UI route/naming sprawl** — `/strategies` is "Strategies" in one nav and "Backtest" in another; `/forward-test` duplicates a filter `/strategies` already has; 5 legacy redirect routes still shipped (`/farm,/research,/steer,/paper,/scores`) |
| **No abandoned-version cruft**; 7 debt markers total, all honest stubs | **`_ssl_context()` copy-pasted 7×**; ~120 cross-module imports of `_private` symbols (a shadow public API) |
| **Lean infra** — single `verify.yml`, clean Modal lane, coherent Railway config | **Doc/process sprawl** — 4+ "single source of truth" docs; `BACKLOG.md` contradicts itself in one file; pre-push comment promises CI-on-push that no longer fires; `research/` accretes dead one-shot harnesses |
| **No mid/small-cap universe** — `data/universe.py` is 30 hardcoded large-caps; the segment where a solo's edge lives is **entirely absent** |

---

## 4. HOW TO USE IT TODAY

The honest current flow (import idea → verdict):

1. **Drive it from Claude Code, not the web app.** The real authoring round-trip lives in the `/strategize` skill (CLI/agent loop): chat a vibe / paste a URL or Pine / "find me something on funding" → it classifies intent, authors a typed `StrategySpec`, validates it (no magic numbers), runs it through the Gate.
2. **To get a profit verdict on an existing/authored spec:** run the `run-gate` skill (cross-asset cohort / FarmLoop path = real data) or `manage-data verify` to see coverage first.
3. **To deepen data:** `manage-data backfill` then `manage-data panels` then `verify --panels`.

**What is NOT smooth yet (the central gap):**

- **No conversational surface in the product.** The web intake (`app/idea-dump-box.tsx`) is **fire-and-forget**: it POSTs prose to `/lab/inbox`, returns "Queued. The next tick…", and **no spec or verdict ever comes back in the UI**. There is no `/strategize` HTTP endpoint at all. "Drive by talking" today means "type a skill in a terminal."
- **The richest endpoint is orphaned.** `POST /lab/author` already returns a typed spec + validity + guardrails synchronously, and `/lab/author/run` even gates it — but **no web component calls them.** The conversational verdict is one wire away from existing.
- **"Next autonomous tick" is a check no scheduler cashes.** `scan_inbox` only fires on engine boot or a manual `POST /autonomy/tick`. A queued vibe sits as prose until a reboot/tick.
- **Two honesty leaks** undercut the verdict: the UI EdgeGate card shows a **synthetic** verdict (the skill doc claims "real data"); and a "fade funding" vibe authors a clean-looking spec that **backtests to zero trades** because `funding_rate` is `None` at every bar (feature not wired).

---

## 5. PRIORITIES (ranked)

North star = **an honest profit verdict on a strategy that survives the Gate + forward-test.**

**Matters (drives the verdict):**
1. **Run the Gate now on cached majors.** The one action that produces a real signal. Deferred behind a false "empty cache" blocker. 1 hour beats another planning rewrite.
2. **Unify the two simulators.** If Gate and backtest disagree on net-of-fee profit, *every verdict is suspect.* Highest-ROI correctness fix.
3. **Close the feature-wiring gap.** 6/40 features computed → most specs trade zero times. Either wire more, or refuse/warn on un-ingested features so verdicts aren't silently empty.
4. **Fix the two honesty leaks** (synthetic UI Gate; specs that can't trade). They directly corrupt the "honest verdict" promise.

**Noise (feels urgent, isn't, for the verdict):**
- Re-planning / handoff rewrites — actively *substituting* for the experiment.
- `_ssl_context` dedupe, router merges, lab jargon polish — real but cosmetic; do in a single groom pass, not now.
- Mid/small-cap universe — high *future* value but **AFTER** the current liquid verdict exists (don't broaden a universe whose edge you haven't confirmed on majors).

---

## 6. BUILD ASAP

The 3–5 concrete next builds, each with why + lean scope:

1. **Run the majors Gate (do, don't build).** *Why:* produces the first real PASS/FAIL; un-blocks the whole project. *Scope:* one local/Modal cohort run on the ~30 cached liquid perps. Output a verdict, not a plan.

2. **Unify the cost model across the two simulators.** *Why:* protects the profit metric — Gate and live backtest must not disagree. *Scope:* make `research/gate.py::_simulate` delegate to `data/backtest.py`'s cost model (same slip+impact, same stop/take source). One PR, no new behavior.

3. **Wire ONE conversational box to `/lab/author` (+ `/lab/author/run`).** *Why:* turns the half-built "chat → spec → verdict" into something real with almost zero engine work — the endpoints already exist and return spec+validity+guardrails synchronously. *Scope:* convert the existing fire-and-forget textarea to render the typed spec inline, plus a "Run Gate" button that calls `/lab/author/run` and shows the verdict. Fix the synthetic-Gate leak in the same pass (run on real bars or relabel the card "machinery demo (synthetic)").

4. **Lean-UI de-clutter (one PR).** *Why:* kills the "patchy" feeling that's driving the overthinking. *Scope:* (a) collapse `/forward-test` into a `/strategies?status=simulation` preset and delete the route; (b) pick ONE name for `/strategies` so both navs agree; (c) decide whether you need two navs at all — express lifecycle as the status facet, drop the stage strip; (d) delete the 5 legacy redirect routes; (e) finish the `paper`→`simulation` vocabulary migration; (f) remove the childless `<Tooltip>` on overview.

5. **(AFTER #1's verdict) Mid/small-cap universe slice.** *Why:* the segment where a solo's edge is most accessible is entirely absent — but only worth it once majors confirm the harness works. *Scope:* add a second universe tuple (~30–50 mid-cap Binance USDⓈ-M perps) or a tiny volume-screened builder (`eligible_from_bars` already has `min_quote_volume`), backfill bars (keyless Binance Vision + ccxt), run the xsec-momentum Gate on that slice as a separate testable cohort.

---

## 7. ADD MORE DATA

The cheapest path to deeper + broader + smaller-asset coverage. The architecture is already excellent; the *reality* is thin. Spend money on nothing until the free path is exhausted:

- **Broaden prod ingest (free, code-only).** Make `run_once`/scheduler sweep the full `perp_universe()` instead of hardcoded `DEFAULT_SYMBOLS` (`ingest/run.py:60`). Today 28/30 symbols get no per-symbol alt-data — this is the difference between "we have a wide universe" and "we feed one."
- **Schedule a bar+funding backfill (free).** The 4h cron only refreshes alt-data; bars/funding rot between manual runs. The verb (`manage-data backfill_bars`/funding) exists — just isn't on any schedule. Add a daily tick.
- **Deepen the keyless tier-0 feeds before adding new ones.** FRED macro, multiasset (Stooq), funding, OI, basis, liquidations, GDELT, DVOL all cost **$0** — backfill to multi-year depth across the universe so the Gate scores real history, not ~50-day windows. (Stop assigning tier-0 weight to feeds with <50 days; that's a recurring trap — see the `exchange_netflow` incident.)
- **Smaller/illiquid assets (free, but AFTER the liquid verdict).** The bar backfiller is keyless + venue-agnostic, so adding mid/small-cap perps is near-zero cost. Gate them as a *separate slice* — do not contaminate the majors verdict.
- **Build the panels to turn "registered" into "usable."** Locally no `ml_panels` exist and the alt store holds only 5 funding files. Run `manage-data backfill` → `panels` → `verify --panels` for an honest, deterministic coverage map (rows/span/staleness/look-ahead per series). That map — not intuition — should drive what to deepen.
- **Cheap docs fix:** `add-data-source/SKILL.md` still points at the old `altdata.py` shim; real providers moved to `data/providers/*.py`. A new source author will edit the wrong file.

---

## 8. THE LEAN-PRODUCT PATH

What "a simple, usable, coherent product" looks like:

- **One front door.** A single conversational box where the operator types an intuition and gets back, in the same view: the typed spec, whether it's valid, and a Gate verdict (PASS/FAIL with the net-of-fee numbers). No queue-and-pray, no terminal round-trip.
- **One navigation, few surfaces.** ~8 conceptual surfaces, one nav, lifecycle expressed as a status facet — not two navs disagreeing on names and a duplicate `/forward-test` route.
- **Honest by construction.** Every verdict says what data it ran on (real vs synthetic) and refuses to show a "PASS" on a spec that traded zero times.
- **One live plan, one log.** Not 36 markdown files with 4 competing "source of truth" claims.

Shortest route there (in order, each small):
1. Run the majors Gate → get the first real verdict (proves the engine).
2. Unify the simulators → make verdicts trustworthy.
3. Wire the `/lab/author` conversational box + fix the synthetic leak → makes it a *product*, not a CLI.
4. Lean-UI de-clutter PR → kills the patchy feel.
5. Collapse the doc layer to AGENTS.md (invariants) + ONE live plan; archive the rest.

That's the whole product. Everything else is optimization on top of a thing that already works.

---

## 9. A DECISION / REASONING LIBRARY

You already have memory + `docs/reports/*` — but they're a sprawl (36 docs, 7 phase-0 verdicts with no superseded markers, a self-contradicting backlog). The fix is **one append-only log**, not another planning doc.

**Recommendation: create `docs/DECISIONS.md`** — a single, append-only, reverse-chronological log. One entry per real decision or verdict. It does **not** exist yet (confirmed). Rules that keep it lean:

- **Append-only.** Never edit past entries. To reverse a decision, write a new entry that supersedes it (`Supersedes: 2026-06-05 #carry-verdict`). This solves the "which verdict is live?" ambiguity that the 7 phase-0 files currently have.
- **One entry = one decision/verdict.** Fixed shape: `Date · Title · Decision · Why (2–3 lines) · Evidence (file/run/commit) · Status (live | superseded by …)`.
- **It absorbs the phase-0 verdicts.** Each FAIL becomes a one-line entry pointing at its detailed report (kept in `docs/reports/` or archived). The log is the index of *what was decided*; the reports are the appendix.
- **It is the trace, memory is the working set.** MEMORY.md stays a short pointer set; DECISIONS.md is the durable reasoning history. The single live plan (pick MASTER_PLAN.md **or** HANDOFF_NEXT.md, delete the other) covers "what's next"; DECISIONS.md covers "what we concluded and why."
- **Discipline rule:** no new plan/handoff/task `.md` until the current experiment produces a verdict — and that verdict goes in DECISIONS.md. One log replaces the re-planning reflex.

Net: **AGENTS.md** (invariants) + **one live plan** + **`docs/DECISIONS.md`** (append-only trace). A new agent reads three files and is fully oriented.
