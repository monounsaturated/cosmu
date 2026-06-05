# COSMU — Master Handoff (2026-06-05, main @ 3d592d6)

> For the next big agent + the human. Lean, prioritized, copy-paste. The HUMAN dispatches; AGENTS
> open PRs and **self-merge if clean** (`gh pr merge --squash --auto || gh pr merge --squash`); a
> file-moving refactor merges ALONE. Repo PRIVATE. CI = PR/main only (feature pushes free).

---

## 🧭 RE-AIM, DON'T REBUILD (read first — the vision is INTACT)
**Keep everything we built.** The machine (LLM-proposes → honest deterministic Gate disposes →
self-learning graveyard → autonomy, all PIT/look-ahead-safe, LLM-walled-from-money) is the moat and it
STAYS. Nothing below removes the vision — it *points the same machine at markets where it can win* and
*adds an output to monetize the signal it already finds.*

Why: after 127 strategies + 7 powered FAILs, the honest read (deep review + our own verdicts) is that
the binding constraint isn't data/compute/capital/speed — it's **WHERE the machine is aimed.** We aimed
it at the most competed-away corner (liquid large-cap crypto · daily bars · free public features), where
our edges (patience, tiny size, LLM synthesis, honesty) are worth ~nothing. The Gate killing everything
is the machine **working correctly** — reporting no free lunch there. That graveyard of powered negatives
is a real asset, not a loss.

**Three aligned moves — additive, ranked by EV (none is a pivot away from the vision):**
1. 🥇 **Numerai Crypto submission — an OUTPUT, not a rewrite.** Bolt a submission step onto the EXISTING
   signal pipeline: the same features the Gate scores → a per-asset signal → submitted to Numerai Crypto
   (our crypto data fits Numerai *Crypto* directly; *Signals* = equities, only if we add equity data later).
   Numerai pays for marginal, decorrelated signal net of *their* execution → **monetizes the "real but
   sub-transaction-cost" signal our reports keep finding** (social-accel leads price; BTC→alt contagion —
   `docs/reports/phase0-social-nonobvious-leadlag.md`). No capital, no venue keys, no beat-fees bar. The
   machine is unchanged; we just stop throwing the signal away. **Caution: prove it small first** (one
   submission, watch diagnostics) before any real stake — it's a complement, not a bet-the-farm switch.
2. 🥈 **Prediction markets (Polymarket/Kalshi)** — a new TARGET for the same machine, where patience +
   small size + LLM synthesis are a *structural* edge (slower/better probability on resolving events).
   Currently data-only, "data too thin"; execution unbuilt. Backfill → wire CLOB → aim the machine here.
3. 🥉 **Cross-sectional market-neutral perps** — a new INSTRUMENT, same machine. Everything tested was
   long-only directional (= levered beta, fails beat-buy-and-hold in a bull regime). A dollar-neutral
   long/short book over the 30-perp universe strips beta + tests the PURE signal; on perps you can short +
   harvest funding. The one untested lever (our own handoff named it). One disciplined pass.

**The vision ("autonomous self-learning profit machine") is unchanged.** We're widening WHERE it hunts +
ADDING Numerai as a way to earn from what it finds. Don't spend on data/compute/capital/a faster box to
make the machine *bigger* — aim it better first.

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
