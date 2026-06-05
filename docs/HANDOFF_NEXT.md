# COSMU — Master Handoff (2026-06-05, main @ 3d592d6)

> For the next big agent + the human. Lean, prioritized, copy-paste. The HUMAN dispatches; AGENTS
> open PRs and **self-merge if clean** (`gh pr merge --squash --auto || gh pr merge --squash`); a
> file-moving refactor merges ALONE. Repo PRIVATE. CI = PR/main only (feature pushes free).

---

## 🧭 THE BIG REFRAME (read first — it changes the mission)
After 127 authored strategies + 7 powered FAILs, the honest conclusion (deep external review + our own
verdicts): **the binding constraint is NOT data/compute/capital/speed — it's MARKET SELECTION.** We
aimed an A-grade honest falsification machine at the most competed-away corner: **liquid large-cap
crypto · daily bars · free public features.** There our advantages (patience, tiny size, LLM synthesis,
honest discipline) are worth ~nothing and our disadvantages (no speed, no private data, no capital) are
maximal. The gate killing everything = the machine **correctly reporting no free lunch there.** A
result, not a failure.

**Re-aim the same machine at games it can win (ranked by EV):**
1. 🥇 **Numerai Signals + Numerai Crypto** — monetizes EXACTLY what our reports keep finding: signal that
   is **real but sub-transaction-cost** (social-accel leads price; BTC→alt contagion robust —
   `docs/reports/phase0-social-nonobvious-leadlag.md`). Numerai pays for marginal, decorrelated signal net
   of *their* execution → **no capital, no venue keys, no execution infra, no beat-fees requirement.** Our
   "dies on costs" signal IS a Numerai submission. **Fastest path to first dollars.** (Footnote in
   VISION.md:309 today — make it the headline.)
2. 🥈 **Prediction markets (Polymarket/Kalshi)** — the one venue where our architecture has a *structural*
   edge: better/slower probability estimation on resolving events, where small size is an advantage and big
   funds can't deploy. Currently data-only, "data too thin, backfill needed"; execution unbuilt. Backfill →
   wire CLOB adapter → point the LLM-synthesis machine here.
3. 🥉 **Cross-sectional market-neutral perps** — everything tested was long-only directional (= levered
   beta, fails "beat buy-and-hold" in a bull regime). A dollar-neutral long-short book over the 30-perp
   universe strips beta + tests the PURE signal; on perps you can short + harvest funding. The one untested
   lever. Do ONE disciplined pass; if it FAILs, *close* the crypto-directional question.

**Do NOT spend another dollar on data / compute / capital / a faster box until re-aimed.** Fix is
direction, not horsepower.

---

## 1. STATE (post-merge)
- main @ 3d592d6. ✅ **fix-1 + fix-2 merged** (#110): the deployed gate now deflates vs the global trial
  ledger AND requires beating buy-and-hold = **trustworthy**. ✅ **God-files split** (#109):
  `api/app.py`→`api/routers/*`, `api/models.py`→`api/models/`, web `data.ts`→`app/data/`,
  `data/altdata.py`→`data/providers/`. Future agents work in these dirs = **collision-free**.
- 0 edges. Cost ≈ $120/mo (Claude ~70%). Engineering A · Honesty A+ · Alpha not-yet.

## 2. RE-APPLY WAVE (3 PRs collided with the refactor's moves — re-do on the NEW structure)
Built on the OLD layout; #109 moved those files. Re-apply each small known diff onto the new modular
structure, then close the stale PR. **Priority: RA-1 > RA-2 > RA-3.**

**RA-1 — integrity hygiene (was PR #111)** · sonnet · `fix/hygiene-reapply` · HIGH (cost-safety + repairs main)
> Re-apply PR #111 onto the NEW structure (`gh pr diff 111` for the exact diff). Moved targets: synthetic
> removal → `api/routers/*` + `spine/engine.py`; LunarCrush dedup/incremental → `data/providers/lunarcrush.py`
> + `data/providers/store.py` + `ingest/pipeline.py`. Includes fix-3 (remove synthetic seed), **fix-4
> (LunarCrush append_dedup + `since` incremental + UNIQUE index — REQUIRED before autonomy cron)**, fix-5
> (docs aspirational), AND the pre-existing fixes it found (risk_on→pm_risk_on, liquidations→
> liquidation_cascade — these repair latent broken tests on main). TARGETED tests while iterating, full
> suite ONCE at the end. Self-merge if clean.

**RA-2 — usable vibe loop + nav (was PR #106)** · sonnet · `web/usable-reapply` · apps/web only
> Re-apply PR #106 onto the new `app/data/` structure (`gh pr diff 106`). Wire orphaned
> `components/overview/idea-inbox.tsx` + `getInboxQueue` + `POST /lab/author` so the loop shows
> queued→spec→verdict; add Mind + Lab to nav; repoint dead /forward-test. Additive, never delete a page.

**RA-3 — groom (was PR #108)** · sonnet · `chore/groom-reapply` · LOW · AFTER RA-2
> Re-apply PR #108's dead-code/orphan pruning onto the new structure (`gh pr diff 108`). Net-negative.
> ⚠️ Do NOT prune `idea-inbox.tsx` if RA-2 wired it.

## 3. DEV-SPEED FIX — "building is a CI job, not interactive" (kills the M2/slow-cloud pain)
The slowness was never the box — it was **building interactively** (OOMs M2 / cold cloud) because CI gave
no verdict on feature branches. Fix the loop, not the hardware. **Codespaces/a faster box just papers over
building in the wrong place — skip it.**
**DS-1 — dev-loop speedups** · sonnet · `chore/dev-speed`
> (1) `verify:remote` = push current branch + trigger `verify.yml` via `workflow_dispatch` + tail the run
> (one-liner "is it green?", no local build). (2) Add `verify:fast` =
> `naming:check && contracts:generate && engine:test -n auto && typecheck` (everything EXCEPT `next build` —
> no OOM, ~1 min; CI's build job catches prerender). (3) `next build --turbopack` + `next dev --turbopack`
> (lower memory → fixes build OOM). (4) Pin `"latest"` deps (next/react/react-dom/typescript/@types/*) to
> exact versions (kills cache-miss + drift). (5) `-n auto` on local `engine:test`. Low-risk tooling. Self-merge.

## 4. COSTS PAGE — real suppliers, dynamic (NO Fly.io)
**C-1 — costs accuracy** · sonnet · `feat/costs-real-suppliers`
> Costs surface references wrong/stale suppliers (e.g. Fly.io). We use: **Railway, Vercel, Supabase, Modal,
> OpenRouter, LunarCrush, GitHub Actions, Anthropic (Claude)**. Update `cosmu/costs/*` to fetch real spend
> where an API exists (Railway, Vercel, OpenRouter, Modal), else a maintained static rate; store in DB (PIT,
> deduped — reuse the cache pattern), refresh on the tick. Surface on /costs + the Overview opex line. Lean,
> not duplicated, no fabricated numbers.

## 5. THE EDGE WORK (after re-aim — the real mission)
- **E-1 (highest EV) — Numerai path** · opus · `feat/numerai-signals` — turn the PIT signal pipeline into a
  Numerai Signals + Crypto submission (no capital, no execution). Map features → per-ticker signal, schedule
  submission, track diagnostics. Monetizes sub-cost signal we already find. Read VISION.md:309. Prove the pipe small.
- **E-2 — prediction markets** · opus · backfill Polymarket → wire CLOB → LLM-synth probability on resolving events.
- **E-3 — cross-sectional market-neutral perp gate** · opus · the one untested crypto lever; if FAIL, close crypto-directional.

## 6. 🧑‍🚀 HUMAN — your clicks (optimistic + careful)
- ✅ **Set `AUTONOMY_CRON_ENABLED=1` on Railway — ONLY after RA-1 (fix-4) merges.** fix-1+fix-2 are already
  in (gate trustworthy); cost-safety (fix-4) is the last gate — until then the 4h tick re-spends LunarCrush
  ($5/day) every run. After RA-1 → flip it → **the machine self-runs** (Slack pings on a pass).
- 🟢 Buy a fresh $5 LunarCrush day only right before a NEW backfill (incremental after RA-1 = cheap).
- 🟢 Repo private; CI cheap (PR/main only). **No Codespaces/faster box** — DS-1 is the cure.
- 🎯 Win = ONE Numerai submission earning, OR one strategy surviving the honest gate + 30-day forward-test.

## 7. ⚙️ BEST PRACTICES (so it stops being slow — learned the hard way)
- **A file-moving refactor merges ALONE, never parallel with edits to those files.** (#109 collided with
  #106/#108/#111 run in parallel → cost a re-apply wave.)
- **Targeted tests while iterating** (`pytest -k … -n auto`), full suite ONCE at the end. (A Sonnet agent
  burned 1h26m re-running the 14-min suite ~5×.)
- **Building is a CI job** (DS-1). Inner loop = edit → `verify:fast`/`pytest -k` → push for CI verdict.
- **Right-size models:** Sonnet/Haiku for mechanical, Opus only for hard judgment/money-path. Mind Claude
  usage limits (support.claude.com/articles/9797557) — don't burn Opus on refactors.
- **Autonomous LLM = OpenRouter API in-engine (cheap); Claude Code = operator-driven.** Do NOT build
  "scheduled headless Claude Code for autonomous work" — burns the Max quota. The 4h tick + OpenRouter
  already batches autonomous authoring. (Decision: discard that idea.)
- One branch = disjoint files; agents self-merge clean PRs; you stay out of the loop.

## 8. DISPATCH ORDER (lean)
1. **RA-1** (hygiene re-apply — cost-safety) → merge → **flip the Railway cron** = machine self-runs.
2. **RA-2 + DS-1 + C-1** in parallel (disjoint: web / tooling / costs) → self-merge.
3. **RA-3** after RA-2. Then **E-1 (Numerai)** — the highest-EV move.
> Stale PRs #106/#108/#111 stay open only as `gh pr diff` reference for the re-applies; close after.
