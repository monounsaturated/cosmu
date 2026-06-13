# Cosmu v2 — Owner Setup & Handoff

> For the owner (you don't write code). Last revised 2026-06-01.
> Two **free** keys unblock the one number that matters (the real-data gate). Everything else is optional and only worth paying for *after* that gate PASSES. Current infra (Railway + Supabase + Vercel) stays — it's lean and works; no migration needed.

---

## A. Do this right now (~10 minutes, $0)

Already set for you: `XAI_API_KEY` (LLM works), `DATABASE_URL` (Supabase wired). You only need the two free keys below.

### Step 1 — FRED API key (free, ~2 min)
1. Go to **https://fredaccount.stlouisfed.org/apikeys**
2. Create an account (or sign in) → click **Request API Key** → type any one-line description → submit.
3. Copy the 32-character key it shows.
4. It powers the `macro_regime` cross-asset feature.

### Step 2 — Polymarket (OPTIONAL — leave it blank)
**You don't pick a token.** The bot is being made to **auto-discover and navigate many macro/risk markets** via Polymarket's free public Gamma API and aggregate their odds into the `risk_on` feature (the new chat builds this — task 1b). So leave `POLYMARKET_TOKEN=` empty.
- *Only* fill it if you ever want to **pin one specific market**: open https://gamma-api.polymarket.com/markets?closed=false&limit=30, pick a market, copy the first id in `clobTokenIds`.
- Until 1b ships, an empty token means the gate runs **FRED-real + Polymarket-synthetic** (a partially-real gate). With 1b, `risk_on` becomes fully real with zero manual work.

### Step 3 — (optional, recommended) OpenRouter key (~2 min, ~$5)
1. **https://openrouter.ai/keys** → sign in → **Create Key**.
2. Add ~$5 under **Credits**. The 24/7 loop uses cheap/free models (~$1–5/mo).
3. Skip this and the machine still runs on the existing `XAI_API_KEY` (Grok only). OpenRouter unlocks many models **by config** — the preferred gateway.

### Step 4 — Paste the keys into `/Users/device/cosmu/.env.local`
Use these **exact** names (they must match Railway/Vercel exactly):
```
FRED_API_KEY=your_fred_key_here
POLYMARKET_TOKEN=the_clob_token_id_here
OPENROUTER_API_KEY=sk-or-...        # optional
```

### Step 5 — Run the real-data gate
```
cd /Users/device/cosmu/apps/engine
python3 -m cosmu.research.loop --ingest     # ingest real data → run the four-arm gate → record the verdict
python3 -m cosmu.research.gate              # print just PASS / STOP-narrow
```
- **PASS** → cross-asset + aggregated data beats single-asset *and* buy-and-hold on real data. The thesis has legs → build forward.
- **STOP-narrow** → it doesn't hold; the per-source / per-asset-class report tells you what (if anything) to keep. Days spent, not months. Still a win.

### Step 6 — Start a new chat with the prompt in **Section E** below.

> **Going live with real money is a separate, deliberate step** (set Binance keys, arm the 2-click toggle). It stays OFF until you do it, and only after a real PASS.

---

## B. Full spend table (priority + worth-it)

| Item | What it buys | Source | Price (approx — verify) | Priority | Worth it? |
|------|--------------|--------|------------------------|----------|-----------|
| FRED API key | macro regime feature | fredaccount.stlouisfed.org | **Free** | **P0** | ✅ unblocks the gate |
| Polymarket token | cross-asset risk-on feature | gamma-api.polymarket.com | **Free** | P1 (optional) | 🟡 leave blank — bot auto-discovers markets (task 1b) |
| Claude Code sub (have it) | build/maintain core + hard features | claude.ai | $20–200/mo (already paying) | **P0** | ✅ the dev engine |
| OpenRouter key | one gateway → many cheap/free LLMs | openrouter.ai | ~$5 credit; **~$1–5/mo** | **P0/P1** | ✅ big leverage, tiny cost |
| Binance **testnet** keys | ~~paper execution~~ — SKIP (SIM uses real prices) | testnet.binance.vision | Free | — | ❌ not worth it (see §F.5) |
| Railway | always-on engine API + crons | railway.app | **~$5–20/mo** usage | **P1** | ✅ the 24/7 machine |
| Supabase | Postgres + pgvector (truth + RAG) | supabase.com | Free tier → **Pro $25/mo** | **P1** | ✅ free to start; Pro when always-on |
| Vercel | web front | vercel.com | Free Hobby → Pro $20/mo | **P1** | ✅ free to start |
| Binance **real** keys | live spot trading | binance.com | Free (needs funded acct) | **P2** (after PASS + arming) | only when proven |
| Tavily | web-search tool for the research bus | tavily.com | Free 1k/mo → paid | P3 opt | 🟡 nice agentic boost |
| LunarCrush | social / sentiment data | lunarcrush.com | ~$24–30/mo | P3 opt | 🟡 only if the free gate shows legs |
| Norgate / Databento | survivorship-free equity data | norgatedata.com / databento.com | ~$80/mo / usage | P3 (equity phase) | 🟡 later, equities only |
| Modal | sandboxed GPU bursts for agent ML | modal.com | $30/mo free credit → pay-per-use | P3 | 🟡 rare deep models only |

---

## C. Options / alternatives (recommended pick in bold)

- **LLM gateway:** ✅ **OpenRouter** (one key → Qwen/DeepSeek/Hermes/Grok/Claude/GPT, swap by config) · direct XAI/Anthropic/OpenAI (one vendor) · self-host (❌ saves nothing until spend is in the hundreds/mo).
- **Always-on hosting:** ✅ **Railway** (usage billing, no sleep — keep it) · Hetzner VPS (~€4/mo, cheapest at scale, more ops). Render ❌ (free tier sleeps). Heavy bursty compute → **Modal** (see `docs/COMPUTE.md`).
- **Database:** ✅ **Supabase** (managed Postgres + pgvector — keep it) · Neon · self-host PG (only at scale).
- **Web host:** ✅ **Vercel** (Next.js native — keep it) · Cloudflare Pages · Netlify.
- **Crypto data:** already **free** via ccxt/Binance (OHLCV, funding, Fear&Greed) — no spend.

---

## D. Cost reality

- **Run the real gate today:** **$0** (two free keys + your existing Claude Code sub).
- **24/7 SIM operation:** **~$25–65/mo**, hard-capped (Railway + Supabase Pro + Vercel + small LLM).
- **+ optional data (social / equity / GPU):** +$25–110/mo.
- Planned envelope: **~$50–150/mo, fully capped.** Live trading stays OFF until you flip it.

---

## F. Deploy & infra — step by step (keep current stack)

Architecture (unchanged, lean): **Railway** = always-on engine API + a bounded 6h cron · **Supabase** = Postgres + pgvector (truth) · **Vercel** = web front · **deploy = `git push`** (both auto-build).

### F.1 Supabase — DONE
`DATABASE_URL` is already set and the schema is applied + verified. Nothing to do now. Free tier is fine to start; move to **Pro ($25/mo)** only when you want no auto-pause for the 24/7 worker.

### Start commands — the short answer

| Platform | What it runs | Start command | Do you edit it? |
|----------|-------------|---------------|-----------------|
| **Supabase** | Postgres + pgvector | — (managed; nothing to start) | **No.** It's a database — no start command. Already wired via `DATABASE_URL`. |
| **Vercel** | the web front | handled by `apps/web/vercel.json` (build `pnpm --filter @cosmu/web build`, then `next start`) | **No.** Just set env vars (F.3). |
| **Railway** | the engine API (FastAPI) + cron | **none to type** — `apps/engine/railway.toml` runs `uvicorn cosmu.api.app:app --host 0.0.0.0 --port $PORT` | **No command edit.** Set **Root Directory = `apps/engine`** + env vars (F.2). |

### ⚠️ Your current setup vs. the target (from your screenshots)
- Your **Railway** service is currently running the **web** (`pnpm build:railway` / `pnpm start` from the repo-root `railway.toml`) — but it holds all the **engine** env vars. The web already lives on **Vercel**, so Railway should run the **engine**, not a second copy of the web. **Fix = point Railway at `apps/engine` (below).**
- Your **Vercel** project has `API_BASE_URL` + `API_SECRET_KEY` but is **missing `NEXT_PUBLIC_API_BASE_URL`** — without it the client-side panels (Live, Console, autonomy, research) can't reach the engine. Add it (F.3). `ENGINE_API_URL` is **unused** — ignore it; the web reads `API_BASE_URL` (server) + `NEXT_PUBLIC_API_BASE_URL` (client).
- Engine is now deployable: `pyproject.toml` has a build backend (`pip install .` works), `__main__` binds `0.0.0.0:$PORT`, and `apps/engine/railway.toml` carries the start + healthcheck + 6h cron.

### F.2 Railway — switch the service to the ENGINE
1. Open your existing Railway service → **Settings → Source → Root Directory = `apps/engine`**. Save. (This makes `apps/engine/railway.toml` drive it — nixpacks detects Python, `pip install .` installs deps, uvicorn binds `$PORT`.)
2. **Settings → Deploy** → if a Custom Build/Start command is still pinned from the repo-root `railway.toml`, **clear those overrides** so the `apps/engine` config takes over. Healthcheck path = `/health`.
3. **Variables** — keep `DATABASE_URL, XAI_API_KEY, OPENROUTER_API_KEY, FRED_API_KEY, API_SECRET_KEY, SCHEDULER_ENABLED, GUARDIAN_ENABLED`. **Remove the Binance keys** (SIM runs on real prices with the adapter `disabled` — §F.5). Add **`CORS_EXTRA_ORIGINS=https://<your-vercel-domain>`** (or `CORS_ALLOW_VERCEL_PREVIEWS=true`) so the browser can call the engine cross-origin. Leave `POLYMARKET_TOKEN` unset.
4. The 6h `research.loop` cron is in `apps/engine/railway.toml`. If your plan needs it in the dashboard, add a Cron service: command `python3 -m cosmu.research.loop --ingest`, schedule `0 */6 * * *`.
5. Copy the engine's public URL (e.g. `https://cosmu-engine.up.railway.app`) → you'll paste it into Vercel next.

### F.3 Vercel — web (point it at the engine)
1. Your web project is already importing the repo (Next.js preset, Root Directory `apps/web`). No build/start edits.
2. **Settings → Environment Variables** — set BOTH to the Railway engine URL from F.2.5:
   - `API_BASE_URL` = `https://<your-railway-engine-url>` (server-side fetches)
   - `NEXT_PUBLIC_API_BASE_URL` = same (client-side panels) ← **the missing one, add it**
   - keep `API_SECRET_KEY`. (`ENGINE_API_URL` is unused — you can delete it.)
3. Redeploy. Open the Vercel URL → Overview reads live engine data (honest empty states until the loop has run).

### F.4 Ongoing
- **Deploy = `git push`** to the connected branch → Railway + Vercel auto-build. Strategies in `strategies/inbox/` ride the same push.

### F.5 Binance testnet — skip it (you're right)
Testnet is **not worth it**: Binance's testnet has thin, unrealistic liquidity/prices that diverge from the real market, so it's a *worse* validation than the built-in **SIM paper** engine, which marks every position against **real live prices** (shadow trading) and charges real per-venue fees. So:
- **For validation → use SIM paper (real prices).** Set **no Binance keys** anywhere; the execution adapter then resolves to `disabled` → deterministic sim-fills on real marks. This is the realistic harness.
- **Testnet's only honest use** is a one-time "does my order API plumbing work" smoke test — optional, skippable.
- **Going live (later, deliberate):** add real `BINANCE_API_KEY/SECRET` on Railway → in the app, the 2-click Live modal → confirm. Only after a real gate **PASS**. Auto-disarms on the daily-loss cap.
- *Your local `.env.local` testnet keys are inert while the live toggle is off (sim-fills don't touch the network) — leave or clear them, your call.*

---

## G. LLM cost — optimized for your OpenRouter free tier

**What I set:** all three model tiers now use OpenRouter **`:free`** models (Llama-3.3-70B / DeepSeek-V3 / DeepSeek-R1) → **$0 spend** on the 24/7 loop. A stale `:free` id simply 404s and degrades to the deterministic template author (no crash, no spend). Configured in `apps/engine/cosmu/lab/router.py`.

**Your limits (you're fine):**
- Your **$12.6** top-up (≥ $10) unlocks **1000 free requests/day, 20/min**. (Under $10 it'd be 50/day.)
- The 6h cron authors a small batch per run → far under 1000/day and 20/min. No risk of busting it.
- The **$5 key spend limit** only caps **paid** usage — irrelevant while every tier is `:free`. It's a good backstop if you ever swap in a paid frontier model.

**Is $10 enough? Top up?** → **Yes, enough. No top-up needed.** Free models cost nothing; the credit's only job was crossing the ≥$10 line for the 1000/day quota. Only top up (or raise the $5 key cap) if you deliberately add a *paid* tier for hard, low-confidence authoring — and even then the daily USD cap + key cap bound it.

---

## E. New-chat prompt (copy-paste verbatim)

```text
You are continuing Cosmu v2 (autonomous quant money machine) at /Users/device/cosmu.

READ FIRST (in order, don't crawl): AGENTS.md (canonical entry) · docs/OWNER_SETUP.md (owner state + what's set) · docs/IMPLEMENTATION.md (state + ranked next steps — the Alpha-decay/drift primitive is now BUILT, gap #4 closed) · docs/GLOSSARY.md · docs/MASTER_PLAN.md · docs/VISION.md §4.

NORTH STAR (owner's intent — the lens for every decision):
A SIMPLE-to-use, very POWERFUL autonomous AGGREGATOR that is a money machine. Buy > build. Edit the CORE and the hard/judgment work HERE in Claude Code via skills (.claude/skills/) so the codebase stays a great agentic substrate; everything else is a clean, easy-to-manage front. Optimize relentlessly for: CLARITY, EASE OF USE, POWER, MAKING MONEY, and LEVERAGING EVERYTHING — compute, data, tools, LLMs, agents, APIs, trading venues, community/open-source. Do DEEP ML but UNBIASED: every model/strategy is judged only by the deterministic, out-of-reach scorer (walk-forward OOS + one-shot holdout + CSCV/PBO + cumulative trial ledger) — LLMs add intelligence (hypotheses, messy→structured data, code) but NEVER define success or move money. Use the cheapest sufficient model by default; escalate to a frontier model (Claude/GPT via OpenRouter) only when it earns its cost under the cap. Lean UI: ~4–6 surfaces, one job per route, plain language, honest empty states, no fabricated numbers.

INFRA (keep it — it's lean and works; do NOT propose migrations):
Railway = always-on engine API + bounded crons · Supabase = Postgres + pgvector (truth + RAG) · Vercel = web · Claude Code = where the core/hard work is built. Favor INTEROPERABLE seams so growth is CONFIG, not rewrites: OpenRouter gateway (models by config) · DataSourceRegistry + point-in-time feature store (data sources by config) · core/interfaces.py asset-agnostic adapters (a new asset class/venue = one DataAdapter/ExecutionAdapter, not a rewrite) · generated @cosmu/contracts-ts (types, never hand-typed) · StrategySpec + strategies/inbox/ (strategies). ⚠️ The engine is NOT deployable as-is — see task DEPLOY (docs/OWNER_SETUP.md §F.2-pre): app.py binds 127.0.0.1:8000 reload=True, and railway.toml builds/starts the WEB. Fix before trusting any Railway deploy.

NAMING (owner directive — make it intuitive, normal, conventional EVERYWHERE: DB tables/columns, API fields, web labels, code symbols). No invented/weird concepts. Prefer plain finance/software terms a newcomer understands. Treat a rename as a deliberate, end-to-end pass (DB ↔ generated contracts ↔ web ↔ code together — no drift), proposed to the owner first (see task NAMING). Keep one consistent vocabulary; update docs/GLOSSARY.md as the single source.

GUARDRAILS (non-negotiable):
- Scorer/Gate + money are DETERMINISTIC and OUT of any LLM path. LLM only PROPOSES.
- No magic numbers in a strategy spec (params come from a fitted space; monitor/policy constants are fine). Point-in-time, no look-ahead. LLM-optional + offline-testable (mock network).
- Live OFF by default; nothing autonomous moves real money. SIM-only until the human arms live.
- NO Binance testnet (less realistic than the SIM paper engine, which marks on REAL prices). With NO Binance keys the execution adapter resolves to `disabled` → deterministic sim-fills on real marks. Real Binance keys + live toggle only at the deliberate go-live step, after a real gate PASS.
- Env var names match Railway/Vercel EXACTLY. Engine (Railway): XAI_API_KEY, OPENROUTER_API_KEY, FRED_API_KEY, POLYMARKET_TOKEN, DATABASE_URL, API_SECRET_KEY, SCHEDULER_ENABLED, GUARDIAN_ENABLED, CORS_EXTRA_ORIGINS. Web (Vercel): API_BASE_URL + NEXT_PUBLIC_API_BASE_URL (BOTH = the engine's public URL; server + client). `ENGINE_API_URL`/`NEXT_PUBLIC_ENGINE_API_URL` are UNUSED legacy — don't reintroduce them. .env*.local stays local; never commit secrets.
- DON'T run full pytest locally (heavy); run targeted tests + verify against Supabase/CI. Stop & report before: schema changes, new vendor/spend, live-execution changes, deploy-config changes, broad renames (incl. the NAMING pass).

COST + MODEL POLICY: One gateway = OpenRouter (OPENROUTER_API_KEY is set; XAI_API_KEY is the fallback). lab/router.py TIER_MODELS already points all tiers at ":free" models → $0 spend; the account's >=$10 top-up gives 1000 free req/day + 20/min. Keep the loop within that (batch authoring, backoff on HTTP 429, don't crank cron frequency). The frontier tier MAY be a paid model (Claude/GPT via OpenRouter) when it genuinely earns its cost on hard/low-confidence work — gated by the router's confidence test + the daily USD cap + the OpenRouter key spend limit (best model when it pays, cheapest otherwise). A stale ":free" id degrades to the deterministic template author (no crash/spend) — refresh ids from https://openrouter.ai/api/v1/models. Heavy/judgment LLM work (batch authoring, deep research, data-factory passes, migrations, refactors, core features) → do it HERE in Claude Code on the subscription, NOT via paid API.

STANDARDS (uniform, so it grows without getting messy — match these patterns exactly; one template per kind, registry-driven, never a bespoke fork):
- Module: every services/lib/adapters/tools file opens with a tiny `# intent:` header (purpose · inputs · outputs · invariants). Read it before the file.
- Data source: register via DataSourceRegistry; numeric, point-in-time `available_at`; pinned `transform_version`; stdlib HTTP + certifi SSL; a separable pure parse fn; an offline fixture; disk-cached; must earn its place via OOS. Add the feature to config/feature_registry.py with a one-line prior.
- Venue / asset class: ONE core/interfaces.py DataAdapter (+ ExecutionAdapter if tradable) + a VenueCatalog entry; survivorship/expiry via `available_at`/`delisted_at`; enable/disable from the universe gate. No bespoke fills/fees — per-venue fee+slippage model.
- LLM/tool: OpenRouter gateway only, model id from lab/router.py config; structured Pydantic (`extra="forbid"`) validation; LLM PROPOSES structure only; tools live on the read/propose-only research bus (execution is NEVER on the bus); key server-side; offline fixture so CI runs with no key/network.
- Test: tests/test_<area>.py; deterministic + offline (inject providers/mock HTTP); targeted (never the full suite locally); each new module ships its test; assert the scorer/money path makes ZERO LLM calls where relevant.
- Persistence + types: typed Postgres table is truth + append to the events ledger; web types are generated @cosmu/contracts-ts from OpenAPI (never hand-typed). New skills go in .claude/skills/ in the standard SKILL.md format.
Codify these in docs/CODING_AGENT.md (task 6) as copy-me templates so every future addition is uniform.

FIRST, CHECK STATE, THEN SELF-ROUTE:
Run: `grep -E '^(FRED_API_KEY|POLYMARKET_TOKEN|OPENROUTER_API_KEY)=' /Users/device/cosmu/.env.local` (values present?). POLYMARKET_TOKEN is OPTIONAL — blank is expected (task 1b). FRED + OpenRouter are set.
- If FRED_API_KEY is set → TASK 1: `cd apps/engine && python3 -m cosmu.research.loop --ingest`, then publish a PASS or a documented FAIL (with the per-source / per-asset-class drop-one). With no Polymarket token yet, risk_on falls back to synthetic — note that in the writeup, and prioritize task 1b to make it fully real. This number is the only thing that matters until it exists.
- If FRED_API_KEY is NOT set → tell the owner (point to docs/OWNER_SETUP.md §A), then do task 1b + task 2 so progress continues while they grab the (one) free key.

NEXT TASKS (highest impact first):
1) (Owner-blocked) Real-data cross-asset gate — see self-route above. PASS or documented FAIL.
1b) Make Polymarket access GENERAL + LEAN (owner must NOT hand-pick a token): extend the Polymarket path (data/altdata.py PolymarketOddsProvider + ingest/run.py + DataSourceRegistry) to DISCOVER macro/risk markets via the public Gamma API (https://gamma-api.polymarket.com/markets) — filter by tag/keyword/liquidity, aggregate several markets' CLOB midpoint odds into the risk_on transfer feature (point-in-time, numeric → ZERO LLM in the ingest/scoring path; the LLM may PROPOSE which markets matter via the read-only research bus, never decides). POLYMARKET_TOKEN becomes an OPTIONAL pin/seed, not required (blank = auto-discover). Offline-testable with canned Gamma payloads; certifi SSL like the other HTTP providers. Outcome: the real gate is runnable with no manual token-hunting, and the aggregator navigates many markets, not one.
2) Authoring-time NOVELTY/COMPLEXITY control in lab/ (THE remaining genuine gap): penalize structurally-similar specs vs live + graveyard (AST / feature-distance) + a complexity penalty, so the population can't collapse to a monoculture (diversity is enforced only at allocation today). Deterministic, offline-testable; LLM still only proposes; reuse knowledge/memory.py. Targeted tests; reconcile docs.
3) More LLMs + data sources + VENUES + ASSET CLASSES by CONFIG only: extend OpenRouter model ids per tier (keep :free defaults); register new FREE/community/OSS data sources via DataSourceRegistry (+ point-in-time feature store); add markets via the core/interfaces.py DataAdapter/ExecutionAdapter seam so a new venue/asset class is ONE adapter + a catalog entry, not a rewrite. Make it all manageable from the front (the existing universe enable/disable gate). Each source/class must earn its place via OOS. Standardized + ML-ready.
4) DEPLOY — engine production-readiness. DONE: pyproject build-system (pip-installable), app.py binds 0.0.0.0:$PORT, apps/engine/{Procfile,railway.toml} (uvicorn + /health + 6h cron). Topology: Railway = ENGINE (service Root Directory = apps/engine), Vercel = web (API_BASE_URL + NEXT_PUBLIC_API_BASE_URL → the Railway engine URL; engine sets CORS_EXTRA_ORIGINS for the Vercel domain). REMAINING: VERIFY the Railway build+/health succeed end-to-end (can't be tested locally); optionally delete the now-legacy repo-root railway.toml web build once the engine service is confirmed.
5) NAMING — intuitive, conventional naming EVERYWHERE (owner directive): audit DB tables/columns, API fields, web labels, and code symbols for invented/weird terms; propose a plain-language mapping to the owner (e.g. avoid niche metaphors; prefer terms a newcomer knows), then apply it as ONE end-to-end pass (DB ↔ generated contracts ↔ web ↔ code, no drift) behind a migration. Update docs/GLOSSARY.md as the single vocabulary source. Ask the owner before executing (broad rename).
6) Aggregator power + ease-of-use: a true one-stop aggregator (more community/OSS/API sources behind existing seams) AND a clean, easy-to-manage operator front (Overview-led, plain language, progressive disclosure, mobile-first). Write docs/CODING_AGENT.md (coding-agent-driven vs automatic tasks). Add reusable skills to .claude/skills/. Collapse Costs into Paper/Overview.
7) Live-polish + drift consumption: surface GET /research/drift in the web once funded history exists; true mark-to-market in /live/positions + adapter.fills() reconciliation; persist toggle state to the orchestrator envelope.

DEFINITION OF DONE per task: targeted tests green + existing suites you touched stay green + web typecheck/contracts build green (if web/contracts touched) + docs/IMPLEMENTATION.md reconciled. Commit to a branch + PR only when the owner asks.
```
