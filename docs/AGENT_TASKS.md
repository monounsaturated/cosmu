# COSMU — Agent Task Prompts (dispatch queue)

> **Copy-paste source for parallel agents.** Each block is a self-contained prompt: paste it into a new
> Claude Code session (cloud or local as marked), it works one branch, opens a PR, **does NOT merge**.
>
> **Rules for every agent (baked in):**
> - **One branch per agent.** Never two agents in one tree.
> - **Targeted tests only while building** (`pytest -k <area>` + `python3 scripts/check_naming.py`). Do **NOT**
>   run the full `pnpm verify` / `next build` / full `engine:test` locally — the **full suite runs once in CI at merge**.
> - **PR to main, don't merge.** The orchestrator runs the CI-gated merge train.
> - **Non-negotiables:** LLM proposes / deterministic gate disposes (LLM never in scoring/money path); no magic
>   numbers (params fit); point-in-time, no look-ahead; live OFF; never display synthetic data; generated TS from
>   OpenAPI only; lean pure-Python (no numpy/scipy/sklearn).
>
> **Cloud vs local:** this repo's cloud sessions can't reach modal.com / Railway / many live APIs. So **CLOUD =
> pure code + offline tests + `next build`**; **LOCAL = `.env.local`, real ingest, `modal run`, `railway run`.**

Status legend: 🟢 RUNNING (don't re-dispatch) · 🔵 NEXT (dispatch now) · ⚪ QUEUED.

---

## 🟢 RUNNING (the 4 — leave alone until they PR)
- `env-local-setup` (local) · `venues` · `data-sources` · `llm-index-scores`. If any of these were launched from the
  earlier 01–04 files, the refined A/B/D below **supersede** them for the *next* round — don't double-dispatch.

---

## 🔵 NEXT — dispatch in this order

### G · verify-parallel — DO FIRST (config, CLOUD, sonnet)
Branch `claude/verify-parallel`. **Goal: cut the ~18-min gate to ~6–8 min** so every future PR is faster.
In `.github/workflows/verify.yml`: split into **parallel jobs** — `engine_test`, `typecheck`, `build` — running
concurrently (matrix or separate jobs), not sequentially. **Cache** the pnpm store and the Next.js `.next/cache`
(keyed on lockfile + source hash); pip cache is already wired — verify it. Add a root script `verify:remote` that
pushes the branch and tails the workflow via the GitHub MCP until green/red. Keep `pnpm verify` (local full) intact
as a fallback. **Done when:** the workflow file shows 3 parallel jobs + caches; a dry push shows wall-clock ≈ slowest
single job. Targeted check: `python3 scripts/check_naming.py`. PR, don't merge.

### E · Frontend redesign + unified Strategies page (web, CLOUD, opus)
Branch `claude/web-product-redesign`. **The current pages aren't grounded in product — fix from first principles.**
1. Write `docs/PRODUCT.md`: persona (operator = a one-person fund), **epics → user stories → acceptance**, and the
   single decision each surface serves. Anchor to VISION §1/§11: **4 surfaces only — Dashboard · Leaderboard ·
   Strategy detail · Console.** "If a page doesn't help you *decide* or *earn*, it doesn't ship."
2. Rebuild surfaces on REAL data (empty states say so honestly; never synthetic):
   - **Dashboard** — fund read-out: aggregate equity (SIM+live), P&L net of all costs, opex-vs-alpha gauge,
     data-freshness + **Mind-consensus banner**, global live toggle.
   - **Mind / Research Desk** — the hedge-fund committee: 6 analyst pillars + ML-survival + Memory, each with its
     **score + one-line LLM rationale + abstain-when-no-data**, debating a consensus. The "24/7 monitoring" surface.
   - **Leaderboard → unified Strategies page** with **faceted filters** (see taxonomy): primary filter =
     **signal-family** {Social · News/Events · Math/Price · Macro/Positioning · On-chain/Flow}; orthogonal facets =
     asset class · venue · timeframe · status (lab→screened→forward→live→killed) · origin · edge-type. Ranked by
     risk-adjusted %. A strategy's signal-family is **derived from the features it references** (no manual tagging).
   - **Strategy detail** — backtest+SIM equity, trades, fee/slippage, OOS vs holdout, authored spec + Mind notes.
   - **Console** — chat steer + recommendation/approval inbox + live toggle.
3. **Scores are first-class**: render index scores (reg_risk/risk_on_off/narrative_momentum) + per-source LLM
   "what this means" reviews, PIT with sparkline history. Pull from engine API via **generated contracts only**.
   **Done when:** `docs/PRODUCT.md` exists; surfaces build (`pnpm --filter @cosmu/web build` passes); filters work
   off real fields. Lean shadcn/Tremor/TanStack, dark, finance-grade. PR, don't merge.

### C · Social Authority Engine — flagship (engine, opus; ph1–3 CLOUD, ph0 LOCAL)
Branch `claude/social-authority`. Build a **"PageRank for credibility"**: score voices (X→Reddit→Substack/news) by
whether their predictive claims came true, whether they were FIRST, and weight by a citation network. **LLM extracts;
deterministic resolves + ranks.** Phase it so each phase PRs on its own:
- **Phase 0 (LOCAL — needs live xAI/Reddit):** ingest a voice's timeline. xAI/Grok for X (key set), Reddit API,
  RSS for newsletters. Provider in `cosmu/data/altdata.py` pattern; offline-testable with fixtures.
- **Phase 1 (CLOUD):** **claim extraction** — LLM → structured `{entity, direction, horizon, conviction, ts}`
  (instructor/Pydantic), in `cosmu/lab/` or `cosmu/mind/`. Mock-LLM offline test.
- **Phase 2 (CLOUD):** **outcome resolution (deterministic)** — resolve each claim vs price/OHLC we hold →
  hit/miss + magnitude **vs base rate**; per-author **Brier/calibration**, **deflated for claim volume** (a spammer
  scores ~0). No LLM here. Offline test with canned bars + claims.
- **Phase 3 (CLOUD):** **primacy + authority** — timeline graph (who-said-it-first), lead-lag vs an event timeline
  (GDELT/news/on-chain) to flag **evidence vs echo**; **PageRank/eigenvector** over the citation graph **weighted by
  the deterministic track record**. Emit `author_authority[handle]` + `authority_weighted_claim_signal[entity]` as
  **PIT features with history** → `feature_registry` (tier1, "must earn via OOS") → `/profile-source` must be **GO**.
**Guardrails:** claim-timestamp = `available_at` (no look-ahead); small-sample/correlation/multiple-testing handled by
the gate; influence ≠ authority (a loud wrong account scores low). **Done when:** each phase has offline tests +
(phase 3) a profile-source GO + a registered feature. PR per phase, don't merge.

### F · Mind hardening — LLM-as-judge committee (engine, CLOUD, opus)
Branch `claude/mind-judges`. In `cosmu/mind/`: each analyst pillar emits a **rubric-scored, structured (instructor)
verdict + confidence + rationale**; the consensus is a **deterministic, auditable aggregation** (LLM scores, the math
combines — the LLM never decides funding). Mock-LLM offline tests; pillars with no data **abstain** (never fabricate).
**Done when:** pillars return typed verdicts, consensus is deterministic + tested, Mind still only reasons (Gate
disposes). This makes E's committee view real. PR, don't merge.

### I · Make POST /autonomy/tick async (engine, CLOUD, sonnet)
Branch `claude/autonomy-tick-async`. The endpoint runs the tick synchronously and exceeds Railway's gateway timeout
(`upstream error`). Change it to **return 202 immediately + run the tick in a background task**, with a status the UI
can poll. Don't change tick logic. Offline test the 202 + background dispatch. **Done when:** endpoint returns fast;
`pytest -k autonomy` green. PR, don't merge.

---

## ⚪ QUEUED (need local/Railway or real data — run after the cloud wave)

### J · Wire the 4h autonomy cron (infra, LOCAL/Railway)
The tick isn't scheduled (no cron in repo) → it never runs itself. Add a Railway cron (or `railway.json`) running
`python -m cosmu.master.scheduler --n 6` every 4h (or schedule `pnpm modal:gate`). Version-control it. **Done when:**
the schedule is committed/set and a manual `railway run … scheduler --n 6` confirms it writes prod. Also: set the
Railway engine service **region → EU-West (Amsterdam)** to match EU Supabase.

### K · Chase the first survivor (engine, opus, LOCAL/Modal — real data)
Hand-author the lucrative families as typed StrategySpecs → run ticks → honest gate verdict. **funding-carry FIRST**
(sits on the deep 731d funding data), then cross-sectional momentum, funding-contrarian, vol-regime. Use
`/create-strategy` or `/strategize`, push specs to `apps/engine/strategies/inbox/`, run the cohort on **Modal**
(`pnpm modal:gate`) or `railway run`. Volume can't manufacture a winner (FDR brake). **Done when:** a real survivor
or an honest documented fail.

### H · LESSONS loop (docs, CLOUD, sonnet)
Branch `claude/lessons-loop`. Create `docs/LESSONS.md` (append-only, structured: `{date, what broke, root cause,
rule now enforced}`) and add a one-line `/postmortem` habit note in `AGENTS.md` session protocol (append a lesson at
each merge/CI-break). Tie to `knowledge/memory.py` + the skills Curator. **Done when:** the file + the protocol line
exist. PR, don't merge.

---

## ⚪ ALSO QUEUED — refined A/B/D (if the running 4 were the old 01–04, these supersede)
- **A · Venues core** (`venues-core`, sonnet, cloud): `/add-venue` Kraken Futures + verify Binance + IBKR for FR/EU
  in `spine/venue.py` (real tiered fees, `restricted_jurisdictions`, `live_enabled=False`, offline fee tests). OKX
  only if trivial, else a stub + TODO.
- **B · Data sources 2** (`data-sources-2`, sonnet, cloud): `/add-data-source` + `/profile-source`: keyless EU feeds
  (GDELT tone, Deribit DVOL, ECB SDW, CoinGecko breadth), each a prior hypothesis, profile-GO.
- **D · LLM index scores** (`llm-index-scores`, opus, cloud): qualitative→quantitative indexes (reg_risk/risk_on_off/
  narrative_momentum), LLM-judge + rubric + structured output, PIT-with-history, registered, profile-GO.
