# Cosmu — Master Plan

> **The single operating plan.** What Cosmu *is now* (verified against code), the real gaps, the target, and the ordered roadmap with copy-paste agent prompts. Integrates rather than duplicates: the strategic contract is [VISION.md](VISION.md), deep specs are [BUILD_PLAN.md](BUILD_PLAN.md), current built-state is [IMPLEMENTATION.md](IMPLEMENTATION.md), invariants/skills are [../AGENTS.md](../AGENTS.md). This supersedes the operator topology in HOW_TO_USE / OWNER_SETUP / DEPLOYMENT.

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
- **Venues/execution** (`spine/venue.py`, `master/execution.py`): Binance spot live-capable behind **5 interlocks**; IBKR + Polymarket **data-only**. Sim fill on any interlock fail.
- **DB** (`knowledge/schema_postgres.sql`): 26 tables incl. append-only `events` (money-truth ledger), global `trials` ledger (DSR deflation), `alt_data`, `tracks`, pgvector on `skills`/`sources`.

## 2. The real remaining gaps (this is the actual work)
1. **Forward-test clock has no 30-day minimum lock.** `mark_tracks()` marks held positions daily, but nothing enforces "≥30 forward days net-positive before live-eligible." Today it's advisory text, not a circuit breaker. **← highest-integrity fix.**
2. **No automated CI.** `pnpm verify` is manual; push = deploy. A skipped verify can ship a broken `main`. **← cheapest high-ROI fix.**
3. **Authoring lacks adversarial disconfirmers.** Only ~6 hard-coded briefs; the gate culls junk but the author isn't structurally pushed to test anti-patterns.
4. **No self-reinforcement of *logic*.** Evolution mutates params; it does not yet *isolate a winning signal and graft it onto other assets/strategies* (the "thinking machine" you want).
5. **Breadth not live**: xAI/Grok Twitter signal (key exists, source not wired), IBKR live execution (data-only), event/news *scoring*.
6. **Cockpit thin**: no NL command palette / chatbot, no source-trust scorecard, no news/intel dashboard.
7. **Heavy compute is manual** (cloud Claude sessions); no on-demand worker for big sims / burst scraping.

## 3. North star & non-negotiables
Autonomous, honest, self-reinforcing money machine — profit net of every fee. **Non-negotiables (never violate):** gate + money path stay deterministic, out of any LLM reach · LLM proposes, never disposes · no magic numbers (params fit) · point-in-time, no look-ahead · live OFF behind 5 interlocks · never display synthetic data · generated TS from OpenAPI only · ask first on schema/spend/live/broad-rename.

## 4. Target architecture
```
WEB (Vercel)  ── ⌘K NL palette + chatbot · source scoreboard · news/intel · mission-control
   │ same API                                   ▲ same API
ENGINE API (Railway, always-on) ── Gate · tick · mark-to-market · POST /lab/experiment ─┐
   │                                                                                     │
CLAUDE CODE (Max sub, $0) ── deep authoring, fan-out master (Opus), skills = control     │
   │ enqueue                                                                             │
LAB COMPUTE WORKER (Fly.io, scale-to-zero) ── big sims / sweeps / ML train / burst scrape┘
   └──▶ writes results+scores ──▶ DATA (Supabase Postgres + pgvector, point-in-time store)
LLM GATEWAY (OpenRouter; xAI/Grok fallback) ── tiered: cheap bulk → Opus master
```
**New piece — Lab Compute Worker.** Engine exposes `POST /lab/experiment` (run sweep / train / evaluate cohort) → job row → worker (separate box) runs heavy compute + LLM, writes results+scores to Postgres. **Frontend and Claude Code call the same endpoint and read the same table** — one API, two faces, zero duplication.

## 5. Data & signals
Every source = timestamped point-in-time feature + a **trust score** (realized contribution to gate-passed edge) + plain-language explanation. Add: **xAI/Grok Twitter** with **influencer scoring** (weight an account by historical hit-rate, not followers) · **event/news scorer** (headline → typed dated signal w/ sign+magnitude) · IBKR equities bars · keep crypto funding/OI/liq/Fear&Greed/Polymarket/macro. Rule: a factor enters only with a prior mechanism + a disconfirmer (no data-mined "weather" features without a reason).

## 6. ML discipline (why no RL yet)
Keep ML **classical and explainable** (survival model + meta-labeling + regime). **No RL / deep nets yet** — they overfit financial series and are unverifiable; SOTA-for-its-own-sake is a trap. The edge is clean point-in-time data + ruthless cost accounting + FDR discipline + a few real signals. Revisit deep methods only with a proven, profitable classical baseline to beat.

## 7. Strategy-invention loop (self-reinforcing core)
`scan-signals` / `pine-from-url` / `evolve-strategy` → **COHORT GATE (FDR)** → forward-test clock (≥30d SIM net-positive) → your click → LIVE (5 interlocks, tiny size). Volume of candidates can't manufacture a winner — FDR is the brake. `evolve-strategy` = isolate a gate-passed signal's logic, graft onto other assets, mix survivors → new cohort → re-Gate.

## 8. Live + SIM together
SIM always runs (everything proves itself on its own $100k track). Proven survivors run **live, small**, behind interlocks + your manual launch. Manual launch off a strong backtest is allowed — a human owns the risk via the toggle.

## 9. Infra
Keep **Railway** (light always-on API + cron). Add a **Fly.io scale-to-zero worker** for big sims + **burst scraping** (xAI/Grok, social) — pay ~$0 idle, spin up per job; this is the "not-always-on, cloud-card" model, and can go always-on later if needed. Reserve **Modal/Hetzner** for genuinely large/always-on compute. ML runs on the worker, **not inside Claude Code** (Claude authors/orchestrates; the worker computes).

## 10. Control surfaces (both)
- **In-app ⌘K palette + chatbot** → calls the same skills/endpoints ("scan signals", "import this Pine URL", "evolve top BTC strategy", "why is X winning?", "launch X live small"). App-use, deep, not a toy chat.
- **Claude Code cockpit** → same skills as slash commands.

## 11. Orchestration as a reflex (standard for every big request)
**Decompose → model-tier → one branch/worktree per agent → build → `pnpm verify` → open PR → Opus merge-train → deploy-check → cleanup.** See [/fan-out](../.claude/skills/fan-out/SKILL.md).
- **Model tiers:** Haiku = scrape/read/summarize (emit a summary `.md`, not raw dumps) · Sonnet = implementation (UI, wiring, tests) · **Opus = master + deep reasoning / money-path / gate logic.**
- **Disposable handoffs:** gitignored `.claude/scratch/*.md` for large/cross-agent artifacts; master reads summaries only.
- **Push policy:** agents **commit + push + open PR — never push to `main` directly.** Only the orchestrator merges (squash, `--delete-branch`). Tiny docs/config still go via PR (cheap, and CI gates it).
- **Worktree:** required for any parallel code agents on one machine (prevents branch-stomping). Solo sequential agent doesn't need one.

## 12. Roadmap (waves)
**Wave 1 — foundations + highest integrity/ROI**
- W1.1 CI GitHub Action (`pnpm verify` on PRs to main) — *config · local · sonnet · PR*
- W1.2 Forward-test **30-day lock** (enforce in code) — *engine · cloud · opus · worktree · PR*
- W1.3 xAI/Grok **Twitter source + influencer scoring** (follow `/add-data-source`) — *engine · cloud · sonnet · worktree · PR*
- W1.4 **NL command palette + chatbot** (⌘K → existing endpoints + `/steer`) — *web · cloud · sonnet · worktree · PR*

**Wave 2 — breadth & invention**
- W2.1 Event/news **scorer** + **source-trust scoreboard** + news/intel dashboard (plain language) — *web+engine · cloud · sonnet · worktree · PR*
- W2.2 **`/evolve-strategy`** skill + engine hook (isolate→graft→cohort) — *engine · cloud · opus · worktree · PR*
- W2.3 **`/pine-from-url`** skill (scrape URL→spec→inbox→Gate; Haiku scrape, Sonnet compile) — *config+engine · cloud · sonnet · worktree · PR*
- W2.4 **Lab Compute Worker** (`POST /lab/experiment` + Fly.io worker) — *engine+infra · cloud · opus · worktree · PR*

**Wave 3 — multi-asset & live**
- W3.1 **IBKR live execution adapter** (flip data-only→live-capable, stays interlock-gated) — *engine · cloud · opus · worktree · PR*
- W3.2 Adversarial disconfirmers in the authoring corpus — *engine · cloud · opus · worktree · PR*
- W3.3 First **live launch**, one strategy, tiny size, after ≥30d forward-test — *operator action*

## 13. Operator guide (how you use it)
- **Start any session:** `/start-session` (reads AGENTS+BACKLOG+state, recommends next + parallel splits).
- **Capture ideas:** append to [../IDEAS.md](../IDEAS.md); run `/triage-ideas` to promote into [../BACKLOG.md](../BACKLOG.md).
- **Big feature:** ask for it → `/fan-out` splits it into parallel agents (you only approve launches).
- **Author strategies:** `/dump-idea` (loose), `/create-strategy` (spec), `/import-pine` (TradingView), `/scan-signals` (sweep) → `/run-gate`.
- **Before push:** `/deploy-check` (= `pnpm verify`). **After push:** `/deploy-iterate` (watch Railway/Vercel).
- **Maintain:** `/groom` + `/tech-debt` (prune), `/align-check` (drift check).
- **Go live:** flip the toggle in `/live` (2-click arm) after a survivor proves ≥30 forward days net-positive.
- **Watch:** `/` overview, `/lab`, `/forward-test`, `/mind`, `/live`.

## 14. Locked decisions (this cycle)
Priority = honesty + breadth **in parallel** · control = **both** surfaces · scope = **crypto spot + stocks (IBKR, toward live) + read-only alt-data** · ML home = **Railway now + Fly.io worker for burst** · Twitter = **xAI/Grok** · scraping = **cloud burst (not always-on; upgrade later)** · keep buy-not-build unless trivial · edge-integrity first · target = near-autonomous, hedge-fund-grade capital management.

## 15. Open questions
Tracked in [../IDEAS.md](../IDEAS.md) and the questionnaire in the working session. Key ones: Twitter source spend tier · IBKR account/compliance for live equities · when to provision the Fly worker vs stay manual · how aggressive the live capital ramp.
