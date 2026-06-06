# COSMU — Handoff (definitive · 2026-06-06)

Single source of truth. Detail lives in `docs/reports/*`. Memory auto-loads the summary.

## What COSMU is
An autonomous machine that **finds a real trading edge and trades its OWN money** (small, gated).
LLM proposes typed StrategySpecs → **deterministic Gate disposes** → LLM never touches money. North star:
**its own profit, net of fees.** It generalizes to a research engine, but **finance is the proving ground and the
only domain with an incorruptible oracle** (profit net of fees). Rule: *no oracle → no graduation* (never build
LLM-grades-its-own-homework advice). See `docs/reports/generalization-plan-2026-06-06.md`.

## 🧭 The big reframe this session (the most important thing to understand)
The old "**0 edges / 7 powered fails**" verdict is **NOT trustworthy** — the backtest harness was broken/starved.
Two adversarial workflows + audits proved it:
- ✅ **FIXED & HARDENED (#123 + #126):** the P0 `risk_on→pm_risk_on` split is fully resolved — gate queries the
  canonical name, fixtures/API router reconciled, AND `StoreBackedAltProvider.fetch_series` now RAISES on an
  unrouted metric (silent-miss class can't recur). 924 tests pass. **Harness P0 = DONE.** Remaining harness work:
  bar backbone (empty cache) + honesty fixes (netflow/funding/FRED) → then re-run. *(Original detail below.)*
- ✅ **FIXED (#123):** the P0 `risk_on→pm_risk_on` split — the live Gate's cross-asset feature was a **silent no-op**,
  production **scored synthetic**, the API router had the same bug. Now bridged + 5 social fields wired + a
  regression test that proves the feature is non-zero. **The Gate is now honest on live data.**
- ⚪ **STILL BROKEN (next):** the **price-bar cache is empty** (Gate runs starved), `exchange_netflow` is a **fake
  feature** (mislabeled long/short ratio), funding annualization is **2–8× off**, the fill model is a **flat-5bps
  fantasy**, and **xsec was only tested on 3–5 names**.
- ➡️ **Therefore: we genuinely do NOT know if an edge exists.** Finish the harness, RE-RUN, *then* judge. The binding
  constraint was never "no edge" or "wrong market" — it was **"we couldn't measure."**

## ⚠️ DO FIRST — the prerequisite (USER action, ~now)
**Upgrade Supabase to Pro ($25/mo).** The DB is **3.3 GB on a 500 MB free cap (6.5× over)** → over-quota free
projects get restricted/paused → the **irreplaceable 10.5M-row social hoard is at risk**, and it's likely why the
grab keeps dropping its connection. $25 protects the data + stabilizes the grab + gives the 8 GB the full universe
needs. Cheapest, highest-ROI spend in the project. **Then cancel LunarCrush once the grab finishes** (re-sub a slim
tier later only if a social edge screens).

## ✅ The plan (ordered — the confirmed best decision: fix measurement, then re-run, before any new surface)
1. **Supabase → Pro** (protect data). [USER, now]
2. **Finish the harness** (cloud agents, serialize — all touch engine):
   - **Bar backbone** — Binance Vision bulk OHLCV (2017→now, full universe) — the cache is EMPTY (the precondition).
   - **Honesty fixes** — kill/relabel fake `exchange_netflow`; fix funding annualization; FRED point-in-time vintage.
   - Add the routability guard test (`enabled features ⊆ routable`) from the integrity report.
3. **RE-RUN the crypto cohort** on the honest harness — the real moment of truth. Start with the **btc-social
   risk-on OVERLAY** (the only non-overfit signal; needs a low-turnover overlay harness shape). [LOCAL]
4. **WIN = ONE strategy survives the honest Gate + a 30-day forward-test** → arm live, small. (The POC. Unchanged.)
5. **Only after step 3 proves the Gate works:** Lane A2 (LlamaParse SEC filings, Firecrawl/GDELT/Quiver, Cohere
   Rerank), then Lane B (cross-domain, oracle-gated). **EXCEPT MCP over engine+Supabase — cheap, independent, do
   early** (the biggest "Claude Code drives it" lever).

## 🔒 Confirmed decisions (locked)
- **Naming:** Backtest → Simulation → Live (shipped #114/#122). Lifecycle: Lab→Backtest→Simulation→Live, per-strategy,
  NO pooled wallet, "Paper" killed.
- **Data:** hoard WIDE for backtest (Pro holds it), run SLIM for live. Social = **SCREEN + forward-test only** (single
  backfill, vendor-revision unprovable → look-ahead risk; see edge-plan + PIT audit). Next free data: Binance Vision
  OHLCV/OI/funding, DefiLlama, Deribit DVOL.
- **Generalization:** barbell, finance funds it, oracle-gated. MLflow NO · MCP YES (early) · NautilusTrader only once a
  forward-survivor exists · LlamaParse for filings (Lane A2).
- **UI:** mobile-first nav on every page + lifecycle stage-strip + progressive disclosure (shipped #121/#122);
  top-N preview → dedicated sortable data pages (in flight). Keep it digestible.
- **Compute:** LOCAL default · Modal heavy · cloud agents for parallel CODE · NO VPS.
- **CI (decided):** KEEP GitHub-hosted Actions — it's off-Mac, parallel, and lean (path-filtered + PR-only + $10 cap
  ≈ $1–5/mo steady-state). Do NOT self-host on the Mac (funnels all CI onto it → slows the Mac, esp. with cloud-agent
  PRs) and NOT Codespaces (paid dev VM, not CI). The big spend was a 13-PR/day spike, not the rate.
- **Polymarket region:** US Railway regions (Virginia/California) are BLOCKED (Polymarket blocks the US). Singapore
  (current) is fine but geo-circumvention is ToS-risky + NOT a priority — park prediction markets until an edge proves out.
- **Agent rule:** one branch = DISJOINT files. Web vs engine = safe parallel; **two engine agents collide — serialize.**

## ▶️ Next parallel cloud agents (prompts ready in `.claude/tasks/` + below)
- **Bar backbone** (engine) — `BinanceVisionBarBackfiller` on the `fetch_history`→`write_bars_cache` seam; fixture-test; PR. *(Run is LOCAL.)*
- **Honesty fixes** (engine) — `altdata.py` netflow + `carry_ablation.py` funding annualization + FRED vintage. *(Serialize after bar-backbone — both engine.)*
- **MCP layer** (infra) — Supabase MCP + Postgres MCP + thin MCP over the engine/Gate CLIs. Independent, do early.
- **Re-run cohort** (LOCAL) — once harness fixed; btc-social overlay first; one BH-FDR family.
- **Declutter** (git, when no agents active) — branch graveyard.
- `.claude/tasks/lane-a-filings-llamaparse.md` — SEC filings (Lane A2, after the Gate is proven trustworthy).

## 📄 Reports (read these — the detail)
- `integrity-bugs-2026-06-06.md` — P0 (fixed in #123) + the routability/registry P2 gaps.
- `poc-acceleration-plan.md` — fix-the-harness path, TOP-5 moves, free-data backfill order.
- `edge-plan-2026-06-06.md` — the 3 hypotheses to Gate (+ PIT-trust verdict on the social hoard).
- `generalization-plan-2026-06-06.md` — the barbell + the oracle doctrine.

## Where the master runs
Fresh Claude Code chat in **`/Users/device/cosmu` on `main`** (NOT a worktree — worktree sandboxes can't open
main-repo files). It dispatches; real work goes to cloud (code) / local (keys+data) / Modal (heavy).

## QA discipline (NEW — the live-checkbox lesson)
**Build-green ≠ a click works.** #113 passed CI but the operator says the Live-page controls still break. So for any
UI/interaction fix, an agent MUST run the app with `.env.local` (engine connected) and exercise the ACTUAL control
before claiming it's fixed — and include a **manual QA checklist** in the PR (control · click · expected result).
Typecheck/build/naming are necessary, not sufficient, for interactive behavior.

## Lessons (banked, so we stop repeating)
- A metric rename must be verified **end-to-end** (ingest→store→provider→gate→fixtures→tests); tests must assert a
  feature is **non-empty**, not just a label. Run the **full engine suite** on any engine change (path-filters hid a
  latent red for weeks). · Bulk DB writes must be **batched**. · Don't churn plan-gated endpoints. · **Refactors/engine
  agents merge ALONE** (parallel = collisions); web vs engine is safe. · Targeted tests while iterating, full suite once.
  · Building is a CI job. · Hoard wide, run slim. · A rate-limited API can't be parallelized faster. · **Fix the
  measurement before trusting any verdict.**
