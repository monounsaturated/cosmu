# Cosmu — Master Plan

> **The single operating plan.** What Cosmu *is now* (verified against code), the real gaps, the target, and the ordered roadmap with copy-paste agent prompts. Integrates rather than duplicates: the strategic contract is [VISION.md](VISION.md), deep specs are [archive/BUILD_PLAN.md](archive/BUILD_PLAN.md) (historical reference), current built-state is [IMPLEMENTATION.md](IMPLEMENTATION.md), invariants/skills are [../AGENTS.md](../AGENTS.md). Operator/deploy detail that used to live in HOW_TO_USE & DEPLOYMENT is folded in here (those docs retired); first-time setup stays in [OWNER_SETUP.md](OWNER_SETUP.md).
>
> **⭐ The near-term money path is the defensive5 TAA floor.** Phase 0 falsified spot funding-carry (best DSR 0.429 vs the 0.95 bar — `docs/reports/phase0-carry-verdict.md`). The actual path: **defensive5 TAA floor** (DAA/VAA/ADM cleared the full unchanged 0.95 gate + beat-B&H on the native multi-asset monthly universe — `docs/reports/ignite-defensive5-2026-06-16.md`) + **SIM→live ignition wire** (TASK I, PR #258: a real order hit Alpaca's paper API, `is_paper=0`, first ever). [DERIVATIVES_PLAN.md](DERIVATIVES_PLAN.md) is a historical reference — do not read it as the current priority.

## Index (jump to the answer)
1. What's real today (verified) · 2. The real remaining gaps · 3. North star & non-negotiables · 4. Target architecture · 5. Data & signals · 6. ML discipline (and why no RL yet) · 7. Strategy-invention loop · 8. Live + SIM together · 9. Infra · 10. Control surfaces · 11. Orchestration as a reflex · 12. Roadmap (waves) · 13. Operator guide · 14. Locked decisions · 15. Open questions.

---

## 1. What's real today (verified against code, 2026-06-03)
The engine is **~85% real, deterministic, and honest.** Confirmed in code:
- **Gate** (`research/gate.py`, `master/scorer.py`, `master/fdr.py`): pre-registered bar, deflated Sharpe, CSCV-PBO, holdout, regime folds, **cohort Benjamini-Hochberg FDR** — all implemented; must-beat-buy-and-hold present.
- **Autonomous tick** (`master/scheduler.py`): 4h cron — ingest → author → screen → gate → fund (SIM) → recommend. Runs **real Binance bars** in prod (`edge_market=False`); synthetic fixture is offline-demo only.
- **Funding** (`orchestrator/loop.py`): funds **only** gate-passed survivors; every FDR cull sets `passed_gates=0` + kills the version. **No bypass.**
- **Data**: 11+ point-in-time sources wired (`ingest/run.py`): funding, Fear&Greed, GDELT news, FRED macro, Polymarket odds, Coinglass liquidations, CBOE put/call, Binance basis/OI/netflow, Reddit, LunarCrush (key-gated), ADSB OSINT. Stored point-in-time in `alt_data` with `read_asof` (no look-ahead).
- **ML** (`ml/survival.py`, `ml/regime.py`): classical survival model that **orders** which gate-passers validate first (never vetoes); regime classifier. **No RL.**
- **Mind** (`mind/`): 7-analyst debate panel, reflections persisted; reasons only, never funds/fires.
- **Venues/execution** (`spine/venue.py`, `master/execution.py`, `adapters/exec/registry.py`): Binance spot + Polymarket CLOB (Polygon/USDC, prediction) **live-capable** behind **5 interlocks** (venue-agnostic ignition resolver); IBKR + Alpaca **data-only**. Sim fill on any interlock fail.
- **DB** (`knowledge/schema_postgres.sql`): 26 tables incl. append-only `events` (money-truth ledger), global `trials` ledger (DSR deflation), `alt_data`, `tracks`, pgvector on `skills`/`sources`.

## 2. The real remaining gaps (this is the actual work)
1. ~~**Paper maturity isn't surfaced.**~~ **SHIPPED**: `/paper` (Simulation) route shows per-strategy forward-return vs backtest + `live_ready` flag + `divergence_status` badge (#152/#153, 2026-06-07). The 30d advisory signal is now visible.
2. **CI is manual-dispatch only.** GitHub Actions (`verify.yml`) is `workflow_dispatch`-only — OFF by default (we are not paying for it). The **pre-push hook is the gate** (naming + contracts drift + engine tests + typecheck — `.githooks/pre-push`); bypassing it (`--no-verify`) can ship a broken `main` since push = deploy. Re-enable PR-triggered CI only if branch protection is ever added.
3. **Authoring lacks adversarial disconfirmers.** Only ~6 hard-coded briefs; the gate culls junk but the author isn't structurally pushed to test anti-patterns.
4. **Self-reinforcement of *logic* — primitive shipped, now armable.** The `/evolve-strategy` skill isolates a gate-passed signal, grafts it onto other assets, and recombines survivors into a new cohort for re-Gating. As of 2026-06-14 it **can fire**: the deploy-lane TAA cohort has **8 honest-Gate survivors** to compound/evolve (3 strict-pass: DAA/VAA/ADM; 5 DSR+holdout: PAA/GTAA/RiskParity/TSMOM/HAA — `cosmu/research/equity_taa_cohort.py`). The novel-MINED-edge lane remains 0.
5. **Breadth not live**: xAI/Grok Twitter signal (**WIRED** — `data/sources/xai_twitter.py`, key-gated; influencer hit-rate store still a stub, so `twitter_influencer_sentiment` duplicates `twitter_sentiment` — see `docs/REVIEW_2026-06-15.md` §6), IBKR live execution (data-only), event/news *scoring*. Polymarket is now live-capable (exec adapter + ignition wired); the remaining prediction last-mile is the autonomous funding+pricing lane (per-market odds ingest + a PricingRouter prediction leg + a gate-passed prediction strategy).
6. **Cockpit improved but incomplete**: full frontend overhaul shipped (#155, 2026-06-07) — premium design system, grouped nav, all surfaces refreshed, zero emojis. Remaining thin: source-trust scorecard and news/intel dashboard.
7. **Heavy compute lane shipped** (Modal — `apps/engine/remote/app.py`; `pnpm modal:gate` / `modal:ingest`, scale-to-zero). The remaining gap is wiring more research runners through it on a schedule, not the lane itself.

## 3. North star & non-negotiables
Autonomous, honest, self-reinforcing money machine — profit net of every fee. **Non-negotiables (never violate):** gate + money path stay deterministic, out of any LLM reach · LLM proposes, never disposes · no magic numbers (params fit) · point-in-time, no look-ahead · live OFF behind 5 interlocks · never display synthetic data · generated TS from OpenAPI only · ask first on schema/spend/live/broad-rename.

## 4. Target architecture
```
WEB (Vercel)  ── Console page (steer/ask, NOT a ⌘K overlay) · source scoreboard · news/intel · mission-control
   │ same API                                   ▲ same API
ENGINE API (Railway, always-on) ── Gate · tick · mark-to-market · POST /lab/experiment ─┐
   │                                                                                     │
CLAUDE CODE (Max sub, $0) ── deep authoring, fan-out master (Opus), skills = control     │
   │ enqueue                                                                             │
LAB COMPUTE WORKER (Modal, scale-to-zero) ── big sims / sweeps / ML train / burst scrape┘
   └──▶ writes results+scores ──▶ DATA (Supabase Postgres + pgvector, point-in-time store)
LLM GATEWAY (OpenRouter; xAI/Grok fallback) ── tiered: cheap bulk → Opus master
```
**New piece — Lab Compute Worker.** Engine exposes `POST /lab/experiment` (run sweep / train / evaluate cohort) → job row → worker (separate box) runs heavy compute + LLM, writes results+scores to Postgres. **Frontend and Claude Code call the same endpoint and read the same table** — one API, two faces, zero duplication.

## 5. Data & signals
Every source = timestamped point-in-time feature + a **trust score** (realized contribution to gate-passed edge) + plain-language explanation. Add: **xAI/Grok Twitter** with **influencer scoring** (weight an account by historical hit-rate, not followers) · **event/news scorer** (headline → typed dated signal w/ sign+magnitude) · IBKR equities bars · keep crypto funding/OI/liq/Fear&Greed/Polymarket/macro. Rule: a factor enters only with a prior mechanism + a disconfirmer (no data-mined "weather" features without a reason).

## 6. ML discipline (why no RL yet)
Keep ML **classical and explainable** (survival model + meta-labeling + regime). **No RL / deep nets yet** — they overfit financial series and are unverifiable; SOTA-for-its-own-sake is a trap. The edge is clean point-in-time data + ruthless cost accounting + FDR discipline + a few real signals. Revisit deep methods only with a proven, profitable classical baseline to beat.

## 7. Strategy-invention loop (self-reinforcing core)
`scan-signals` / `import-pine` / `evolve-strategy` → **COHORT GATE (FDR)** → paper proof (≥30d net-positive, **advisory**) → **human launch via modal** → LIVE (5 interlocks, tiny size). Volume of candidates can't manufacture a winner — FDR is the brake. `evolve-strategy` = isolate a gate-passed signal's logic, graft onto other assets, mix survivors → new cohort → re-Gate.

## 8. Live + SIM together (human launches; LLM only suggests)
SIM always runs (everything proves itself on its own standalone track — default **$1,000**, `sim_track_capital`). **Going live is a deliberate human action — no time gate.** Clicking a strategy → **Launch-live modal**: pick asset + venue, see **fees fetched live & shown** (per-venue, refreshed daily), set **budget (default $100, editable)** + risk settings, confirm. The **5 interlocks remain the hard safety**; the **30-day paper is now ADVISORY** — surfaced as an LLM/UI recommendation ("eligible / not yet proven"), the human may launch anyway. **Venue key-gating:** a venue is greyed-out / cannot arm unless its API keys are present in the engine env (Railway server-side; the UI reads a `configured: bool` flag, never the keys). Prep both crypto (Binance) and equities (IBKR) this way; each stays inert until its keys are plugged.

## 9. Infra
Keep **Railway** (light always-on API + cron). Heavy bursty compute (big sims, sweeps, ML train, burst scraping) runs on **Modal** (scale-to-zero, ~$0 idle, billed per-second — see `docs/COMPUTE.md`). ML runs on Modal, **not inside Claude Code** (Claude authors/orchestrates; Modal computes).

**Latest infra & monthly cost (excludes already-paid Claude Max $100 / OpenRouter $10 credits / existing xAI credits):**

| Service | Role | Cost/mo |
|---|---|---|
| Railway | always-on engine API + crons | ~$5–20 |
| Supabase | Postgres + pgvector | $0 (free) → $25 (Pro) |
| Vercel | web | $0 (hobby) |
| **Modal** | heavy compute: backtests/ML/sweeps (scale-to-zero) | **~$0** idle ($30/mo free credits covers R&D) |
| Data APIs | FRED·GDELT·Polymarket free; LunarCrush optional | $0 (+~$24 if LunarCrush) |
| **New recurring total** | | **~$5–45/mo** (Modal credits cover R&D phase; see `docs/COMPUTE.md`) |

This table is the **source of truth for infra/cost**; an in-app **cost/infra view** (wiring the empty `costs` + `llm_calls` tables, see Wave 2) renders it live + per-strategy ROI.

## 10. Control surfaces
- **Primary = Claude Code** (skills as slash commands) — the deep command surface; no in-app ⌘K (deemed unintuitive).
- **Web = glass cockpit** — watch + approve + the **Launch-live modal** + light `/steer` nudges. A dedicated **Console page** (not a ⌘K overlay) is the in-app home for steer/ask.
- **Later: an MCP server** so Claude Desktop/Code can drive the live app directly (start runs, read state) without bespoke UI.

## 11. Orchestration as a reflex (standard for every big request)
**Decompose → model-tier → one branch/worktree per agent → build → `pnpm verify` → open PR → Opus merge-train → deploy-check → cleanup.** See [/fan-out](../.claude/skills/fan-out/SKILL.md).
- **Model tiers:** Haiku = scrape/read/summarize (emit a summary `.md`, not raw dumps) · Sonnet = implementation (UI, wiring, tests) · **Opus = master + deep reasoning / money-path / gate logic.**
- **Disposable handoffs:** gitignored `.claude/scratch/*.md` for large/cross-agent artifacts; master reads summaries only.
- **Push policy:** agents **commit + push + open PR — never push to `main` directly.** Only the orchestrator merges (squash, `--delete-branch`). The **local `pnpm verify` is the gate** (CI is manual-dispatch only); run it before merging.
- **Worktree:** required for any parallel code agents on one machine (prevents branch-stomping). Solo sequential agent doesn't need one.

## 12. Roadmap (waves)
**Wave 1 — foundations + highest integrity/ROI**
- W1.1 ~~CI GitHub Action on PRs~~ **SUPERSEDED** — CI is now `workflow_dispatch`-only (OFF, not paying for Actions); the **pre-push hook (naming + drift + engine tests + typecheck) is the gate**. Re-enable PR-triggered CI only if branch protection is added.
- W1.2 Paper **maturity signal** (compute + surface ≥30d net-positive as *advisory* live-readiness; do NOT hard-block — human decides) — *engine · cloud · opus · PR*
- ~~W1.3 xAI/Grok **Twitter source + influencer scoring**~~ **SHIPPED** — `data/sources/xai_twitter.py` + `twitter_sentiment` ingested into the store; registered in `default_source_registry`; read by the research brain in `gather_context`. `twitter_influencer_sentiment` **DISABLED** until the real `InfluencerHitRateStore` is wired (stub returns 0.5 = byte-identical duplicate; `BACKLOG.md:65`). `gtrends_search_interest` **QUARANTINED** (revision_safety hazard — rescales history) until `profile-source` validates it.
- W1.4 **Launch-live modal + dynamic fees + venue key-gating** (pick asset/venue, live fees, budget default $100, grey-out venues with no keys; prep crypto+equities) — *web+engine · cloud · sonnet · PR*
- W1.5 **Cost/ROI + infra view** (wire `costs`+`llm_calls` writers; render the infra cost table + per-strategy ROI) — *web+engine · cloud · sonnet · PR*

**Wave 2 — breadth & invention**
- W2.1 Event/news **scorer** + **source-trust scoreboard** + news/intel dashboard (plain language) — *web+engine · cloud · sonnet · worktree · PR*
- W2.2 **`/evolve-strategy`** skill + engine hook (isolate→graft→cohort) — *engine · cloud · opus · worktree · PR*
- W2.3 ~~`/pine-from-url`~~ **REMOVED** — TradingView renders Pine client-side so URL scraping doesn't work; copy-paste via `/import-pine` (+ the `pine_indicators/` indicator-port for feature mining) supersedes it.
- W2.4 **Lab Compute Worker** (`POST /lab/experiment` + Modal heavy lane) — *engine+infra · cloud · opus · worktree · PR*

**Wave 3 — multi-asset & live**
- W3.1 **IBKR live execution adapter** (flip data-only→live-capable, stays interlock-gated) — *engine · cloud · opus · worktree · PR*
- W3.2 Adversarial disconfirmers in the authoring corpus — *engine · cloud · opus · worktree · PR*
- W3.3 First **live launch** via the modal — one strategy, $100, your click (30-day proof advisory, not required) — *operator action*

## 13. Operator guide (how you use it)
- **Start any session:** `/start-session` (reads AGENTS+BACKLOG+state, recommends next + parallel splits).
- **Capture ideas:** append to [../IDEAS.md](../IDEAS.md); run `/triage-ideas` to promote into [../BACKLOG.md](../BACKLOG.md).
- **Big feature:** ask for it → `/fan-out` splits it into parallel agents (you only approve launches).
- **Author strategies:** `/dump-idea` (loose), `/create-strategy` (spec), `/import-pine` (TradingView), `/scan-signals` (sweep) → `/run-gate`.
- **Before push:** `/deploy-check` (= `pnpm verify`). **After push:** `/deploy-iterate` (watch Railway/Vercel).
- **Maintain:** `/groom` + `/tech-debt` (prune), `/align-check` (drift check).
- **Go live:** open a strategy → **Launch-live modal** → pick venue (must have keys), confirm budget ($100 default) → arm. 30-day proof is shown as advice, not a blocker; the 5 interlocks are the hard safety.
- **Watch:** `/` overview, `/lab`, `/forward-test`, `/mind`, `/live`.
- **Cadence (Railway crons, 7 total — see `apps/engine/railway.toml`):** 15-min ingest · 4h autonomous tick · daily (00:10 + 22:10 UTC) + hourly forward-test/mark clocks · hourly voices · daily rotation re-arm. Setup checklist: [OWNER_SETUP.md](OWNER_SETUP.md).

## 14. Locked decisions (this cycle)
- **Live:** human launches via a modal (asset/venue, live fees, **budget default $100 editable**, settings); **no time gate** — 30-day proof is advisory, LLM may suggest, human decides; 5 interlocks are the hard safety; **venues grey-out without keys**.
- **Testing throughput:** start **many strategies at once** (SIM only), iterate continuously; LLMs fetch/propose ideas from Pine, social, NL, search — all funnel to the FDR gate.
- **Scope:** crypto (Binance) + equities (IBKR) **prepped + key-gated**; read-only alt-data. Don't go live on a venue until its keys are plugged.
- **Infra budget:** target **~$50/mo**, ceiling **$100** (excl. Claude Max + OpenRouter + xAI). Modal covers bursty compute at ~$0 idle on free credits.
- **Twitter = xAI/Grok** (credits already in env.local → move to Railway). **News/intel = buy-not-build / free / open-source** (GDELT free now; paid only if it clearly pays).
- **Control:** Claude Code primary · web cockpit + Launch modal + Console page · **no ⌘K** · MCP later.
- Edge-integrity first · near-autonomous · hedge-fund-grade capital management.

## 15. Open questions
Tracked in [../IDEAS.md](../IDEAS.md). Remaining: LunarCrush paid tier yes/no · IBKR account + market-data sub timing · live capital ramp speed after the first $100 track works · whether the Console page also does free-form Q&A or command-routing only.

## 16. Accounts & APIs to set up (owner)
Already have: Railway · Supabase · Vercel · Claude Max · OpenRouter ($10) · xAI credits (key in `.env.local`).
- **Now (the only new spend):** set up **Modal** (heavy compute lane, ~$0 idle on $30/mo free credits) — see `docs/COMPUTE.md` for one-time setup. Set up when Wave 2.4 lands (already wired in `apps/engine/remote/app.py`).
- **Now (free):** confirm a **FRED** API key (macro feature); move **`XAI_API_KEY`** into **Railway env** (prod can't read `.env.local`).
- **When going live crypto:** **Binance** API key+secret → Railway env (then the venue un-greys).
- **When going live equities:** **IBKR** account + market-data subscription.
- **Optional later:** **LunarCrush** paid (richer social, ~$24/mo) — only if it earns its keep.
- **Keys policy:** live keys live **server-side in Railway env** (never committed). UI shows only a `configured` boolean. `.env.local` is for local debugging/reads.
