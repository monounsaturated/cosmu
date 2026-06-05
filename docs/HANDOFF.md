# COSMU — Master / Orchestrator Brief

> The canonical handoff. Read this first, then `AGENTS.md`. You own `main`, design
> sub-agent prompts, merge their work, drive compute, and **decide the means**. The
> goal is fixed; the path is yours. **Buy-over-build** when cheaper/faster/easier to
> maintain. If you do anything twice, make it a **skill**. Keep everything lean,
> durable, replicable, agentic-first.

## 🧭 Operator direction (current, from the operator)
1. **Both depth AND breadth.** Nail edges end-to-end *and* widen the research machine.
2. **Test SEVERAL high-impact ideas where we have an unfair advantage** — smart, logical,
   small-size niches big funds ignore. **Across ALL assets + strategy variants**
   (the strategy × asset × timeframe matrix). Likely edges to probe: funding carry,
   social-authority/insider signals (our build moat), prediction markets, cross-market
   signal transfer, vol-regime — but **you test and let the Gate decide**.
3. **Live with real money is wanted** — once a strategy proves in SIM, the operator
   WILL fund it small to try, **across all assets** (crypto, equities, prediction mkts).
4. **Spend:** manage fees first; **invest more for high-impact work or to clear a
   bottleneck; scale spend as profit grows** — build a continuously-better machine.
5. **Track external trends** (AI-narrative coins, rates/macro, geopolitics via
   prediction markets, X/Reddit sentiment) and exploit where there's edge.

## 🔑 Your authority & autonomy (you may operate the whole stack)
You may **edit and operate everything**, smartly and securely:
- **Code/GitHub:** own `main`, branches, PRs, merges, CI.
- **Infra:** Railway, Vercel, Supabase, Modal — config, deploys, migrations, regions.
- **Secrets:** edit `.env.local` (gitignored) to add Modal + any keys; **sync secrets
  OUT to the platforms** — `pnpm modal:secret` (Modal), and for Railway create the
  mirror `railway:sync` (Railway CLI `railway variables --set …` or API with
  `RAILWAY_API_TOKEN`). **Feasible & secure IF:** secrets only ever pass as env/CLI
  args, **never printed to chat/logs, never committed, never put in an LLM prompt**;
  `.env.local` stays gitignored; prefer a script over hand-typing (replicable).
- **Spend/models:** **audit and decide** — OpenRouter free is the 24/7 default; escalate
  to a paid model (e.g. Kimi) when a step is genuinely hard and it's worth it; pay when
  it raises expected return; throttle when it doesn't. Be wise; ROI-gate everything.
- **Ask the operator only** on money-at-risk, product direction, or genuine uncertainty.

## 🎯 Mission / success
Autonomous risk-adjusted **PROFIT, net of every cost**. Success = the FIRST strategy
that clears the deterministic **Gate** AND proves net-of-fee edge on its own track
(today: 127 authored → 0 passed → **no edge yet**). Then decorrelated survivors →
operator arms one Live small → it keeps edge live. The human drives in plain language.

## 🧑‍🚀 The only loop the human touches
They dump ANYTHING — idea, trade hunch, feature, gripe — into `IDEAS.md` 🗑️ **DUMP ZONE**.
You run the rest, every time: **read → sort → route** (product/infra → `BACKLOG.md` as a
defined **user story**; trade → `/strategize` → typed spec → the **Gate**; junk → dropped)
**→ prioritize → `/fan-out` builds it (sub-agents) → CI tests it → clear the zone.**
The human only dumps and reviews results. Keep that promise.

## ✅ Checkpoint 0 — verify live/merged/deployed (do first)
- `git log --oneline origin/main -1` → `f05b58c`, clean (this was confirmed pushed).
- `curl -s https://cosmu.up.railway.app/health` → ok ; open the Vercel URL → cockpit
  loads on real data ; `railway run env PYTHONPATH=apps/engine python3 -m
  cosmu.master.scheduler --n 6` → a tick runs end-to-end. Fix anything red first.

## 🤖 Agentic operating model (the codebase IS your interface)
- **Skills = your verbs** (`.claude/skills/*`): start-session, strategize, create-strategy,
  dump-idea, triage-ideas, run-gate, scan-signals, evolve-strategy, debug-strategy,
  add-venue, add-data-source, profile-source, manage-data, import-pine, fan-out,
  split-tasks, groom, tech-debt, align-check, code-review, deploy-check, deploy-iterate,
  variance-attribution. Use them; **if a procedure recurs, write a new skill.**
- **Docs = your map:** `AGENTS.md` → `docs/START_HERE.md` → `docs/AGENT_TASKS.md` →
  `BACKLOG.md` → `IDEAS.md` → `docs/COMPUTE.md` → VISION. Read the INDEX, not everything.
- **Types:** TS contracts generated from the engine OpenAPI (`@cosmu/contracts-ts`) —
  never hand-typed. Every module opens with an intent-spec. Keep docs token-frugal.
- **Buy-over-build:** managed for plumbing (OpenRouter, Modal, Supabase, social-listening,
  voice, search). Build only the differentiator: the deterministic Gate + the loop.

## 🧩 Sub-agent dispatch (quick · smart · coherent)
Queue: `docs/AGENT_TASKS.md` (spawn via `/fan-out` + `/split-tasks`). Standard prompt
shape: **branch · 🌍 env (cloud = offline code+tests+`next build` | local =
secrets/Modal/Railway/live data) · 🔌 needs · scope · done-when (targeted tests) ·
"PR, don't merge".** **One branch = one environment.** Cloud = parallel offline code;
you (networked) = `.env`/Modal/Railway/live. Heavy quant → Modal. Verify → CI.

## 🧪 Human checkpoints (small, testable, frequent)
After each wave, hand the operator a thing to click/run: (a) live app loads + a surface
shows new real data; (b) a tick runs, counts move; (c) `/run-gate` verdict on a real spec;
(d) Costs card shows real vendor spend; (e) **first survivor in Forward-test** — the
milestone that matters. Give the exact command/URL each time.

## 🗺️ Architecture
Deterministic **MASTER** (money/schedule/caps/live-gate/**SCORER**) + LLM **LAB AGENT**
(authors/mutates/ML in sandbox). **LLM proposes, Gate disposes — no LLM in money.**
Flow: author → screen → walk-forward (real fees) → **GATE** (deflated Sharpe · CSCV-PBO ·
holdout · regime folds · cohort BH-FDR) → $100k SIM track → forward-test → Live (armed).
**THE MIND:** analyst panel (Technical · Macro · Sentiment · Social · OSINT · Positioning
+ ML-survival + Memory) → consensus; reasons only, never funds, abstains w/o data.
No pooled wallet. Live OFF behind 5 interlocks.

## 📊 Stack
- **Data** (PIT, look-ahead-safe, each needs a prior hypothesis): FREE — ccxt
  funding/OI/liq/basis/netflow, FRED, fear&greed, DefiLlama, Polymarket odds, Reddit,
  GDELT tone, Deribit DVOL, ECB. KEYED — xAI (Twitter), LunarCrush (paid, wired).
  DERIVED — LLM index scores (reg_risk_crypto, risk_on_off) + planned social-authority.
  Prod DB: ~731d funding + macro depth (real).
- **ML:** deterministic tabular **survival** ranker (orders compute, never vetoes) +
  agent-written ML + LLM-as-judge index scores (rubric + structured, PIT w/ history).
  Lean pure-Python today (no numpy/scipy/sklearn — deliberate; revisit on Modal only if
  edge justifies).
- **LLM routing:** OpenRouter free = 24/7 default (protect ~$10) · xAI = Twitter only ·
  paid OpenRouter (e.g. Kimi) on hard steps under a cap · Claude Code (Max) = heavy.
- **Venues** (EU/FR, live gated): binance, kraken(spot), coinbase, ibkr, okx,
  kraken_futures; polymarket/alpaca data-only. Real per-venue fees = costing truth.
  Operator wants **all assets** in scope.
- **Compute:** Railway = engine API + crons (→ EU-West). Modal = heavy lane
  (`pnpm modal:gate/ingest/secret`). GitHub Actions = verify gate.

## 🚦 State / in-flight
main green & deployed (`f05b58c`). Tick works but is **NOT scheduled** (no cron → runs
only when invoked). In-flight sub-agent PRs to verify + merge: LLM routing (free-first),
parallel-CI, frontend refine + unified input, social-authority, cost monitor (/costs
prerender fixed `f84ee84`), Slack notifier (Slack is a **seam** — emits events, nothing
POSTs yet), async `/autonomy/tick` (sync = gateway timeout). Edges: apply survival-features
migration to Supabase; some free feeds blocked (CBOE/Coinglass); verify ≈ 18 min
(parallel-CI fixes it).

## 🔒 Non-negotiables
LLM proposes / Gate disposes · scorer + money out of LLM reach · no magic numbers ·
PIT / no look-ahead · never display synthetic · generated TS only · live OFF · one
scheduler, every tick audited. **Never read pytest results through `tail`/`head`** (it
masked a failure → broken `main` once). Coerce web response arrays to `[]` (prerender
safety). Auto-merge green + low-risk; fix risky yourself; ask operator only on
money/product/Gate calls.

## 🔓 Open decisions (yours — facts, not answers)
1. **Dev box:** Mac M2 16GB (free, full control, ~16–18 min verify + `next build` OOM) ·
   GitHub Codespaces (~free 120h then ~$0.18–0.36/h, fast, networked, secrets,
   devcontainer ready, ephemeral) · Hetzner VM (~€8/mo always-on EU, you set up). Decide
   or ask.
2. First-edge selection (test several high-impact, all assets) · 3. schedule the tick or
   not · 4. when a step earns a paid model + the cap · 5. buy-vs-build & premium-data buys
   (ROI-gated; operator will fund high-impact).

## 📌 Resources & budget
Keys: DATABASE_URL, XAI, OPENROUTER, FRED, MODAL, RAILWAY, SLACK. Budget ≈ $5–45/mo infra
+ $100/mo Claude Max; OpenRouter ~$10; Modal ~$0 ($30 credits). Operator will invest more
for high-impact / bottlenecks and scale with profit.

## ▶️ First move
Checkpoint 0 → pick your dev box → merge the in-flight PRs (CI-gated train) → then drive
the highest-leverage path to the FIRST surviving edge across the asset matrix. Go.
