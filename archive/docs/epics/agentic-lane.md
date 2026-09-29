# Epic — The LLM strategy model (Gate B) — unified design (v2)

> Status: **DESIGN, operator-validated 2026-06-17.** Synthesises the operator's P0–P4 answers, the
> external research pass ("how the pros run LLM trading"), and the codebase standardization audit into
> ONE vision. No real-money LLM code ships until the pieces below are built + the human launches it.
> **Gate A (the deterministic FDR gate) is LOCKED and untouched by everything here.**

---

## 1. The one-paragraph vision
COSMU has **two strategy MODELS**, not one: **Quant** (typed `StrategySpec` → the deterministic **Gate A**)
and **LLM** (an agent that reasons over unstructured info → a scientific-but-flexible **Gate B**). They share
ONE lifecycle, ONE status/lane vocabulary, ONE caps system, ONE UI — *uniformised so a human can manage
thousands of strategies simply*. The machine is a **risk machine**: it goes fast, takes bounded risks, accepts
errors, and optimises for **total gain that offsets losses** — NOT for fewest errors. The binding rule on BOTH
gates: **never kill a real signal out of caution** — over-pruning destroys the edge. The LLM **proposes**; a
**deterministic** path (admission → risk gauntlet → sizing → order) **disposes, sizes, and fires**. Live is
**OFF by default**; the **human clicks launch** for every strategy.

## 2. Why an LLM model at all (the gap Gate A can't fill)
Many real edges — a journalist's call, a small-cap social catalyst, a Polymarket rumour — are **not
backtestable** (probabilistic, unstructured, fast-moving). Refusing them because they can't pass a quant gate
throws away exactly the alpha LLMs are good at. Research confirms the trap *and* the cure:
- **End-to-end LLM-trader backtests are structurally leaky** — the model's training cutoff postdates the test
  data, so it "predicts" prices it memorised. FINSABER (100+ stocks, 2004-24): **zero significant alpha**
  (p>0.34); "Profit Mirage"/"Alpha Illusion" show Sharpe 8 in-sample collapsing below buy-and-hold out-of-sample.
- **The pros agree: "LLM proposes, deterministic executes."** Balyasny (*Arcane*), Man Group (*AlphaGPT*) use
  LLMs in the **research/analyst** layer; humans + deterministic modules own sizing, risk, execution.
- **~0% of published LLM-trading work is methodologically rigorous** → COSMU's honest validation discipline is
  the **differentiator**, not a constraint.

→ So Gate B does **not** backtest the LLM. It validates **prospectively + by cross-verification**, and the human
is the final launch guardrail.

## 3. The two models (P0 = option A: unified DB/UI, two kinds)
| | **Quant** | **LLM** |
|---|---|---|
| Artifact | `StrategySpec` (typed rules, `param_space`) | `AgentSpec` (a **Mind** reasoning loop → typed `Decision`) |
| Validated by | **Gate A** (DSR/PBO/BH-FDR, locked) | **Gate B** (§5, scientific-flexible) |
| Backtest | yes | **no** (leaky) — paper/forward only |
| Compiler | `compile_spec` (param_space) | bypasses the quant compiler (its own validate) |
| Reasoning engine | — | `cosmu/mind/` (judge · thinker · signal_builder + RAILGUARD), already money-incapable |

**How it slots in (from the audit — the axes are already orthogonal):**
- Add a top-level **`kind: Literal['quant','llm'] = 'quant'`** discriminator (default → every Quant spec
  byte-identical). Route by `kind`, mirroring the existing `lane_router`/`event_router`. **`status` and `lane`
  stay SHARED.** The LLM model is a new **kind**, NOT a new status and NOT a new lane.
- DB: add a CHECK-constrained `kind` on `strategy_versions`; relax the 4 quant-only NOT NULL columns
  (`spec/generated_code/code_hash/params`) when `kind='llm'`.
- Executor: `paper_step.py` dispatches by `kind` (quant → today's path; llm → the Decision path).

**Modularity over schema-bloat (operator):** an LLM strategy is *mostly a natural-language SUMMARY* of its
thesis/research, not a wall of quantified columns. Generate a short NL recap to stay fast and modular; **do not
re-migrate the DB for every new strategy**. Quantify/`index` only where it clearly pays (we already have
`cosmu/indexes/` — reuse it for the few signals worth a numeric series).

## 4. Decisions locked this session
- **Q3** Gate B = **score + proofs** (the human reads + decides), not pass/fail.
- **Q4/Q5** the validation components are good; **no source whitelist/allowlist**; **single source ≠ discard**
  (it could be huge alpha) → flag "single/weak source = caution" and let the agent act anyway, smaller size.
- **Q6** the human can launch **any** strategy live at **any** time (even ~zero paper); the 3-week "maturity"
  is an **aesthetic indicator only**.
- **Q7** **no LLM backtest** (we'll run one throwaway test to confirm it's useless, then drop it). *Future
  feature:* quantify a concrete event (news → price) into a real, leakage-checked mini-backtest — only when
  cheap, never built from scratch now.
- **Q12** build **both** the unified leaderboard **and** the agent-trace replay ASAP.
- **Q13** badges **as identical as possible** across Quant+LLM (one visual language), LLM-specific badges
  (confidence · sources · debate) only where needed — built to scan **thousands** of strategies.
- **P4** cost model = §7. **Modal** redeployed so the autonomous fleet runs current code.

## 5. Gate B — the scientific-but-flexible protocol (the core)
Not a backtest. A **score + evidence bundle** the operator reads. Components:
1. **NL thesis summary** (the primary artifact — fast, modular).
2. **Unbiased critic agents** — fixed, calibrated prompts that are **neither bull nor bear, neither optimistic
   nor pessimistic**; they try to *refute* the thesis on the merits. (Research: multi-agent debate + minority-veto
   measurably cuts hallucination; but a single LLM judge is ~25% noisy/overconfident → **never** let one agent
   size/arm.)
3. **Two passes (operator):** an **optimistic** pass ("see the signal everywhere") and a **pessimistic** pass.
   If only one is feasible at first, ship one — but **never over-prune**: missing a real signal is the worse
   error.
4. **Source / catalyst forensics** (especially small social-driven markets — crypto, Polymarket — where you
   *can* see who moved it): build a **track record** for the source (journalist / account): is he *right* (% of
   calls that played out)? does he have **alpha or just beta** (was he first, or following momentum already
   visible)? how many other tweets/signals corroborated? follower count + real-vs-fake. Essentialise → a
   **replicable** strategy, with **no look-ahead / no mirage**.
5. **LLM-specific disconfirmers** (cheap, from research) where applicable: ticker-anonymisation (edge dies when
   the symbol is masked = memorised prior), reverse-evidence flip, outcome-embargo, alpha-vs-beta regression.
6. **Forward paper record + calibration** as it accrues (advisory, not a blocker — see Q6).

**Posture:** suspicious, not dismissive. A shaky single-source theory on a tiny account is **not impossible** —
it could be real alpha. We act, **smaller**, with a **hard stop-loss**, accepting we'll lose some capital to win
big elsewhere. "Single source / new account / low score" → recorded as caution in the agent's prompt + the
evidence bundle, **never an auto-kill**.

## 6. The LLM strategy "kit" + run modes
**Every strategy (both models) MUST have an exit** — stop-loss, take-profit, **trailing SL**, **trailing TP**,
and a sizing rule. (Cross-cutting: verify this is wired + visible in the UI for all strategies — tracked as a
check, not part of the LLM build.) An `AgentSpec` produces a typed `Decision{symbol, side, confidence, SL, TP,
trailing, size_request, rationale, trace}`; a **paper twin** always runs alongside a live agent.

Run modes (one model, a `mode` flag):
- **Autonomous live** — the LLM trades alone within caps + guardrails (the live consent the operator gives).
- **Slack human-in-the-loop** (activatable, **NOT default**) — the agent posts each intended trade to Slack
  (side, price window, TP/SL, brief reason) with **yes/no buttons**; a click executes. Best for ultra-risky /
  few-source / exploratory theses — keeps the alpha, lets the human veto big LLM mistakes. *(Backlog unless
  bandwidth allows.)*
- **Prompt-launch** — spin up a strategy from one or a few prompts.
- **Self-directed research agents** — agents that theorise, test, and propose new strategies on their own.

## 7. Cost & compute model (P4)
- **Flat Claude Code (subscription) for everything non-constant**: research, strategy creation, source forensics,
  summaries — ideally even some live loops, run locally. (⚠️ research caveat: *headless* Claude-Code/Agent-SDK is
  metered since 2026-06-15; **interactive** Claude Code is still flat.)
- **The recurring LIVE decision loop** (agent armed) = **cheap OpenRouter models, free tier first** (we have ~$10
  / ~1000 free-model requests — **verify**); test if free is strong enough, escalate to paid (xAI / OpenAI /
  Anthropic) only when it measurably wins. The model must **DO things** (memory, verify, spawn sub-agents) — not
  one-shot Q&A.
- **Hybrid human option** — an operator watching ~10h/day at first (feeds info, launches, while the LLM learns
  the human's operating style). Adopt if it clearly raises success per unit of human time.
- **Levers (research):** prompt caching −90% reads · Batch API −50% (→−95% stacked) for latency-insensitive work
  · model routing (Haiku cheap / Opus only on novel reasoning) · per-run turn/tool caps.
- **Hard LLM-spend cap** (see §8 rules): subscriptions > metered API wherever possible (API costs explode).
- **We will TEST** — real end-to-end calls to xAI/Anthropic/OpenAI, spend a little, measure what wins.

## 8. Caps, rules & risk (unified, on the front)
- **Trading caps (live $):** ONE unified per-strategy system — **global total**, **per-strategy default**, and a
  **per-strategy editable** cap, all visible + simply editable on the front (builds on the #260 operator caps).
- **NEW — LLM-spend "rules" on the strategy page** (like the live caps button, but for *spend*): a simple
  monthly $ ceiling for **automated LLM calls** across ALL strategies (live/backtest/paper). E.g. "$50/mo" =
  no strategy's LLM calls exceed that. **Distinct from the Costs page** (flat recurring tool costs) — these are
  recurring *automated-LLM* costs. Keep it simple.
- **Guardrails OUTSIDE the model (research):** caps enforced in the exec layer the agent can't reach · **kill-switch
  stored externally** (the agent can't read/flip its own off-switch) · **circuit breaker** (≥N consecutive losses
  or intraday drawdown) · **pre-trade slippage simulation** · order **rate limiter** · scraped content treated as
  **untrusted DATA, never instructions** (indirect prompt-injection is the #1 threat) · a **replay/audit log**
  (LLM input → typed output → verdict → fill).
- **Small-market reality:** account for rug / liquidity / volume risk, but **don't be over-safe** — bounded blast
  radius (tiny caps + stop-loss) is what lets us move fast on shaky-but-promising signals.

## 9. Observability & the human-as-guardrail (P5)
- **Both ASAP (Q12):** a **unified leaderboard** (Quant+LLM, one badge language, scannable for thousands) **+** the
  **agent-trace replay** (steps · analyst debate · sources · disconfirmers · admission · fill).
- **One visual language (Q13):** same badges where possible; LLM-only badges (confidence · #sources · debate
  result) added, not forced. NL summary per strategy is the primary human-readable surface.
- **Console = Claude Code** for speed. Idea (operator, fairly high priority): a **disposable, same-format status
  HTML** Claude Code emits on demand — "where we are · backlog · features · strategies · recommended next actions"
  — re-offered ~each message, **deprioritised if it clutters**.
- **What the human must learn** to be the guardrail: the vocabulary (kind/lane/status/confidence/source-score),
  the "proof ∝ capital" lane logic, why single-source ≠ kill, and how to read a Gate-B evidence bundle to decide
  a launch. (A short operator primer ships with the UI.)

## 10. Trading frequency (cross-cutting, both models)
Tune frequency per strategy. LLM strategies are likely **more frequent + more ephemeral** (less data, faster
markets); Quant may trade too rarely. Goal: **trade as much as profitably possible** without being eaten by fees
— bias toward **fast-in / fast-out**, keep longer holds where they earn. Make frequency a first-class, visible
per-strategy property and watch the net-of-fee number (the north star).

## 11. Build sequence (prioritised; start filling strats while building)
0. **Fix the web-taxonomy DEBT first** (in progress) — kill phantom `forward`, consolidate the duplicate stage
   maps; later export the engine vocab via `@cosmu/contracts-ts`. *Correct debt, create none.*
1. **`kind` discriminator + unified DB/UI** (Quant byte-identical) + the shared badge/lifecycle vocabulary.
2. **Observability** (leaderboard + agent-trace + NL summaries) — $0, immediate value, lets us *see* while building.
3. **Gate B** (critics + source forensics + disconfirmers + two passes → score + evidence bundle).
4. **AgentSpec + the Mind loop + paper twin + exit/trailing/sizing**; the **prompt-launch** mode.
5. **Cost/rules** (LLM-spend cap UI + cheap/free live-loop wiring + the end-to-end model tests).
6. **Live (capped, manual launch)** + guardrails; then the **Slack human-in-the-loop** mode.
Throughout: **parallel agents**, fill strategies now, Gate A untouched, live = manual human click.

## 12. Backlog / deferred (recorded, not built now)
- Event-quantification mini-backtest (news→price, leakage-checked) — *future feature*.
- Slack yes/no-button execution from the message.
- `@cosmu/contracts-ts` export of the full status/kind/lane vocab (kills the hand-maintained TS taxonomy).
- Self-directed research-agent fleet (theorise → test → propose).
- Cross-cutting verification that exit/trailing/sizing is wired + UI-visible for ALL existing strategies.
