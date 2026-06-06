# COSMU — Handoff (simple)

## What COSMU is
An autonomous machine that **finds a real trading edge and trades it with its OWN money** (small, gated).
LLM proposes → deterministic Gate disposes → LLM never touches money. North star: **its own profit, net
of fees.** (NOT a signal-vendor. Numerai is a footnote, not the plan — see bottom.)

## State (main is current, 0 open PRs, prod healthy)
- ✅ Gate is now **trustworthy** (global deflation + beat-buy-and-hold merged).
- ✅ Code **de-collided** (god-files split into routers/models/providers) → agents won't collide.
- ✅ CI cheap (PR/main only). ✅ Memory auto-loads this plan.
- ⚪ **0 edges yet** — 7 powered FAILs on spot-crypto-directional (the Gate doing its job, not a failure).
- 🆕 **Deep social data banked**: ~95 coins × ~6 yr × 7 metrics in Supabase → fresh signals to test.

---

## WHAT TO DO (in order — simple)
1. **Let the LunarCrush grab finish → cancel LunarCrush** (cancellation already scheduled ✓).
2. **Cleanup wave** (cloud agents): RA-1 → then RA-2 / DS-1 / C-1 → RA-3. Then **flip the Railway cron** → the machine self-runs.
3. **Find the edge** (the core mission): test the new social data + the two untested markets (below).
4. **Win =** ONE strategy survives the honest Gate **+** a 30-day forward-test → arm live, small.

## Where to run agents (simple rule)
- **Code** (fixes, refactors, UI) → ☁️ **cloud** agents, parallel.
- **Needs keys/data** (extraction, Gate-on-real-data, deploy) → 💻 **local** (Mac, `.env.local`).
- **Heavy compute** (big backtests/sweeps) → ⚡ **Modal**.
- **New master agent for next session** → just open a **fresh Claude Code chat, LOCAL** (it only dispatches; the real work goes to cloud/Modal). Say: *"read docs/HANDOFF_NEXT.md, run RA-1."* No VPS, ever.

---

## THE PROMPTS

### Cleanup wave (cloud, self-merge if clean)
- **RA-1** `fix/hygiene-reapply` (sonnet, HIGH): re-apply the closed PR #111 onto the new structure
  (`gh pr diff 111`) — remove synthetic seed, LunarCrush dedup/incremental (cost-safety), doc fixes, + the
  pre-existing fixes (risk_on→pm_risk_on, liquidations→liquidation_cascade). **ALSO: batch the Supabase
  writes** — `PgAltDataStore.append` inserts row-by-row, which made the LunarCrush grab take ~1.5h for ~1.3M
  rows; switch to a batched insert (psycopg2 `execute_values` / `executemany`, ~1000-row chunks) keeping the
  ON CONFLICT dedup → 10–100× faster for ALL ingest. Targeted tests, not full-suite.
- **RA-2** `web/usable-reapply` (sonnet, apps/web): re-apply PR #106 — wire the orphaned `idea-inbox.tsx` +
  `getInboxQueue` + `POST /lab/author` so the vibe loop shows queued→spec→verdict; add Mind+Lab to nav. Additive.
- **DS-1** `chore/dev-speed` (sonnet): `verify:remote` (push→trigger→tail CI), `verify:fast` (no next build),
  `next --turbopack`, pin `latest` deps, `-n auto`. "Building is a CI job."
- **C-1** `feat/costs-real-suppliers` (sonnet): costs page = Railway/Vercel/Supabase/Modal/OpenRouter/LunarCrush/
  GitHub/Claude (NO Fly.io); fetch real where API exists, else static; DB-cached, no fabricated numbers.
- **RA-3** `chore/groom-reapply` (sonnet, after RA-2): re-apply PR #108 dead-code prune; don't remove idea-inbox.tsx.

### Edge work — COSMU's OWN profit (the core mission, after cleanup)
- **E-1 — Social-signal Gate run** (local+Modal, opus): we just banked ~6 yr of LunarCrush social history.
  Author social strategies (volume-accel lead, sentiment divergence, galaxy-score momentum, BTC→alt
  contagion) → run the cohort through the EXISTING honest Gate (global FDR). COSMU trades survivors itself.
- **E-2 — Cross-sectional market-neutral perps** (opus): the one untested lever. Dollar-neutral long/short
  over the perp universe — strips beta, tests the PURE signal, harvests funding. COSMU trades its own book.
  Needs an OKX/Kraken-Futures venue (add-venue) before live; SIM/Gate first.
- **E-3 — Prediction markets** (opus): Polymarket/Kalshi — structural edge for small + patient + LLM-synth.
  Backfill → wire CLOB → Gate → COSMU trades its own. (Currently data-only, "data too thin".)

### Cleanup agent (branch graveyard — optional, anytime)
> Cloud/local, READ-ONLY then SAFE delete. For each local branch except `main` + current: SAFE if its work
> is on origin/main (ancestor, OR byte-identical files, OR head of a MERGED PR) → `git worktree remove` +
> `git branch -D`; never --force, never delete unique work. Goal: lean branches, zero code lost (~50 today).

### Future: LunarCrush BUILDER 1-day mega-grab (only if/when you want stocks+topics)
> Individual = coins only. To get stocks/topics/full-coin-tail: upgrade to **Builder ($15/day)** for ONE
> day (all endpoints + 100 req/min), run `scripts/lunarcrush_max_extract.py --coins 4000 --stocks 2000
> --topics 800 --categories 300 --sleep 0.7 --quota 20000` → Supabase → **cancel.** Resumable, deduped.
> Only after crypto social signal proves useful. NOT a priority.

---

## Footnote: Numerai — NOT core, do not build as a focus
Numerai pays you to *sell* a signal (no capital/execution on your side). It's a different profit model from
COSMU's vision (run our OWN money machine). Park it. Only ever a tiny optional side-experiment if you want
to monetize a sub-cost signal — never the mission. The mission is COSMU trading its own edge (E-1/E-2/E-3).

## Lessons (so we stop repeating mistakes)
- File-moving refactors merge ALONE (parallel = collisions). · Targeted tests while iterating, full suite once.
- Building is a CI job, not local (no faster box needed). · All ingest defaults to the Supabase store, never
  silent-local. · Right-size models (Sonnet mechanical, Opus hard). · One branch = disjoint files; self-merge clean.
- **Bulk writes must be BATCHED** — row-by-row Supabase inserts made a 1.3M-row grab take ~1.5h. Use
  `execute_values`/`executemany` (chunked) for any backfill. Moving to Modal/cloud does NOT help — the
  bottleneck is DB write latency, not compute. (Fixed in RA-1.)
