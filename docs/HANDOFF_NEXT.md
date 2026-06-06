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
1. **LunarCrush grab (running) → then CANCEL.** Banking the **full multi-venue tradeable universe** (~980 coins: Binance + Kraken spot/futures + Hyperliquid + Coinbase × ~6.4 yr × 7 metrics) into Supabase — this history is the irreplaceable asset. Universe lives at `.cosmu/coin_universe_allvenues.txt`. Cancel as soon as it finishes (stocks/topics need Builder; skip). Resumable + deduped. Relaunch: `python3 scripts/lunarcrush_max_extract.py --coins 1100 --coins-file .cosmu/coin_universe_allvenues.txt --sleep 3`. **To UPDATE later** (after cancel/re-subscribe): add `--refresh` (re-fetches all coins, writes only newer days). Ongoing freshness belongs in the `manage-data` skill / a cron, not this one-time script.
2. **Cleanup wave** (cloud agents): RA-1 → then RA-2 / DS-1 / C-1 → RA-3. Then **flip the Railway cron** → the machine self-runs.
3. **Find the edge** (the core mission): test the new social data + the two untested markets (below).
4. **Win =** ONE strategy survives the honest Gate **+** a 30-day forward-test → arm live, small.

## Where to run agents (simple rule)
- **Code** (fixes, refactors, UI) → ☁️ **cloud** agents, parallel.
- **Needs keys/data** (extraction, Gate-on-real-data, deploy) → 💻 **local** (Mac, `.env.local`).
- **Heavy compute** (big backtests/sweeps) → ⚡ **Modal**.
- **New master agent for next session** → open a **fresh Claude Code chat in the MAIN repo `/Users/device/cosmu` on branch `main`** (NOT a worktree). It only dispatches; the real work goes to cloud/Modal. Say: *"read docs/HANDOFF_NEXT.md, run RA-1."* No VPS, ever.
  - ⚠️ If a handoff link won't open ("outside the session folder"), it's because the chat is running inside a `.claude/worktrees/…` sandbox — that can't open files in the main checkout. Start the chat in `/Users/device/cosmu` and the link works.

---

## THE PROMPTS

### Cleanup wave (cloud, self-merge if clean)
- **RA-1** `fix/hygiene-reapply` (sonnet, HIGH): re-apply the closed PR #111 onto the new structure
  (`gh pr diff 111`) — remove synthetic seed, LunarCrush dedup/incremental (cost-safety), doc fixes, + the
  pre-existing fixes (risk_on→pm_risk_on, liquidations→liquidation_cascade). Targeted tests, not full-suite.
  (The batched-Supabase-write speedup — the grab-slowness fix — already LANDED on main; do not redo.)
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

## Going faster — bottlenecks & what to buy (cheap-first)
The binding constraint is **NOT compute or money** — it's (a) features wired into the backtest (~7 of ~40)
and (b) strategy *diversity* flowing through the Gate. So the lever is parallel engineering + automation, not
a bigger box. Order of impact:
1. **Wire the data → features → Gate** (E-1): the social hoard + funding + macro are banked but only ~7 feed
   the backtest. Wiring the rest is the single highest-ROI task. Pure engineering — fan out cloud agents.
2. **Automate the loop** (cron): LLM proposes (`scan-signals`/`strategize`) → Gate disposes → forward-test →
   memory. Once flipped on, throughput stops depending on you babysitting. This IS the "automated trading firm".
3. **Parallelize discovery**: many cheap LLM-proposed strategies (OpenRouter cheap models to propose, Opus only
   for hard synthesis) → the deterministic Gate is the filter. Volume of *honest* attempts is the game.
4. **Compute**: only when sweeps get big → Modal (pay-per-use, already wired). Don't pre-buy.

**What to buy / upgrade (none urgent, all cheap):** keep Railway+Vercel+Supabase+Modal (~$120/mo). Biggest $
is LLM (~70%) → cut by model right-sizing, not by spending more. NautilusTrader only once a 30-day forward
survivor exists. No thousands-per-month infra — the bottleneck isn't buyable yet.

**GitHub Actions:** already fixed/cheap (PR+main only, path-filtered, concurrency-cancel ≈ $1–6/mo). If you want
$0: add a **self-hosted runner on the M2** (free compute) or lean on local pre-push `verify` + Railway/Vercel
build checks. Not worth more effort now — it's no longer a real cost.

## Frontend (make it smooth, coherent, honest)
- 🐞 **PENDING PR (cloud agent):** `fix/venue-checkbox-bug` — clicking a live/venue checkbox greyed it out and
  froze the app. Root-caused + fixed in an isolated worktree; review + merge.
- ✍️ **Rename the lifecycle stages** for clarity (operator wants "SIM"/"Live" reworded). Decide the pair, then a
  cloud agent renames consistently (badges/tabs/titles/status) — a naming map of every occurrence is in the PR above.
- 📊 **Data viz (SOON, not now — buy don't build):** a charts page that overlays LunarCrush + price + funding +
  macro on one time axis, with event dots on the curve (big-news markers), readable by human AND LLM. Prefer an
  embeddable charting lib (TradingView Lightweight Charts / Recharts) over hand-rolled. Standardize a single
  "series + annotations" data shape so any source plugs in. Goal: scan many signals at a glance + feed the LLM
  a legible multi-series view for weak-signal reasoning.

## Data: hoard wide for backtest, run slim for live
- **Hoard NOW (irreplaceable):** the *history*. We can re-subscribe for fresh values later, but ~6.4 yr of
  daily social history vanishes when the plan lapses. So bank **deep × wide × right-metrics, point-in-time**:
  all ~438 Binance-tradeable coins × 7 metrics (social_volume, social_sentiment, galaxy_score, alt_rank,
  market_cap, volume_24h, price) × full daily history. Wide cross-section matters because the only untested
  edge is **cross-sectional** (rank coins by social momentum) — and small-caps, not majors, are where social
  signal is least arbitraged. Storage is trivial (~390 MB). Daily bucket is enough; skip intraday (10× the calls).
- **Don't over-hoard:** stocks/topics (Builder-only + untradeable on spot = low value), coins on no venue we
  can trade, sub-daily granularity. The hoard is *insurance + discovery fuel*, not proof of edge (E-1 unproven).
- **Use for LIVE (later, slim):** once the Gate proves WHICH metric+transform+universe has edge, live needs
  only THAT one signal, for only the traded symbols, refreshed at the rebalance cadence — cheap to re-subscribe.
  The make-or-break is **honest `available_at` lag**: LunarCrush publishes with a delay; stamp it right so the
  backtest can't see a value before it was knowable, or SIM→live will diverge (use the variance-attribution skill).

## Footnote: Numerai — NOT core, do not build as a focus
Numerai pays you to *sell* a signal (no capital/execution on your side). It's a different profit model from
COSMU's vision (run our OWN money machine). Park it. Only ever a tiny optional side-experiment if you want
to monetize a sub-cost signal — never the mission. The mission is COSMU trading its own edge (E-1/E-2/E-3).

## Lessons (so we stop repeating mistakes)
- File-moving refactors merge ALONE (parallel = collisions). · Targeted tests while iterating, full suite once.
- Building is a CI job, not local (no faster box needed). · All ingest defaults to the Supabase store, never
  silent-local. · Right-size models (Sonnet mechanical, Opus hard). · One branch = disjoint files; self-merge clean.
- **Bulk writes MUST be batched** — row-by-row Supabase inserts made the ~1.3M-row grab crawl (~6h; ~4min/coin,
  CPU 99% idle waiting on the DB). FIXED & LANDED on main: `Store.insert_many` (psycopg2 `execute_values`,
  ~1000-row chunks) → ~4,500 rows/s (~77×). Modal/cloud does NOT help — bottleneck is DB write latency, not
  compute. Batch ALL backfills.
- **Don't churn plan-gated endpoints** — the grab tried 2000 stocks/topics one-by-one (404 on Individual) at
  ~7s each ≈ hours wasted + false "done" marks. FIXED: gated buckets default to 0 and self-abort on the first
  402/403/404 (no quota burned). Only Builder ($15/day) has stocks/topics/categories.
