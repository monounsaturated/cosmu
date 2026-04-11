# Global Context Document — Lean Autonomous Trading Platform (V1-first, future-ready)

## 1. Document purpose

This document is the **global product and architecture context** for building the app.

Its goal is to ensure the system is built in a way that is:

1. **lean at the beginning**,
2. **modular and adaptable**,
3. **fast to ship**,
4. **clear to operate**,
5. **low in avoidable technical debt**,
6. and **ready to grow later without requiring a rewrite**.

This is not a generic brainstorming note.
This document should be treated as the **source of truth for V1 product scope, architectural intent, priorities, and non-goals**.

---

## 2. Product in one sentence

This product is a **lean, prompt-driven autonomous spot trading platform** that runs bots on a schedule, lets an LLM make structured portfolio decisions, validates and executes those decisions on Binance, records everything clearly, and is designed so it can later support more workflows, more bots, and additional venues without collapsing into technical debt.

---

## 3. Core philosophy

The project should optimize for the following balance:

1. **Do it well, but do not overbuild**
2. **Avoid avoidable technical debt**
3. **Stay very lean at the beginning**
4. **Keep the architecture modular and adaptive**
5. **Ship a real autonomous loop quickly**
6. **Preserve clarity, auditability, and iteration speed**
7. **Build a reusable foundation, not a throwaway prototype**

The correct mindset is:

> Build the smallest serious system that can run live, remain understandable, and survive future extension.

This project should **not** become:

1. a giant architecture for hypothetical future needs,
2. an abstract framework with unnecessary layers,
3. a fragile one-off bot that must be rebuilt later,
4. a dashboard-heavy internal tool that neglects the core trading loop,
5. or a vague prompt experiment with poor execution discipline.

---

## 4. What matters most

The top priorities for V1 are:

1. **Time to first real autonomous bot**
2. **Auditability / clarity**
3. **Iteration speed**

This means V1 should be judged primarily by whether:

1. one bot can run autonomously in a real environment,
2. the operator can clearly understand what happened,
3. prompts and configs can be changed quickly,
4. the system is easy to improve without structural pain.

Financial performance matters later, but it is **not** the primary product success metric for the first serious version.

---

## 5. Strategic direction chosen

The intended direction is:

1. **V2-style simplicity as the backbone**
2. with **selected structural discipline from V1**
3. while avoiding both:

   * underbuilt chaos,
   * and overbuilt platform complexity.

In practical terms, this means:

1. the first version stays focused on a **single clean autonomous loop**,
2. but uses enough separation and modularity that later additions feel like extension, not reconstruction.

---

## 6. V1 scope and design posture

### 6.1 What V1 is

V1 is:

1. an **internal-use autonomous trading product**
2. with **one main bot structure**
3. designed around **one live-capable loop**
4. using **prompt-driven reasoning**
5. and **clear execution + recording discipline**

### 6.2 What V1 is not

V1 is not:

1. a full multi-venue platform,
2. a futures system,
3. a deep portfolio research engine,
4. a large signal normalization platform,
5. a sophisticated manual risk engine,
6. a multi-agent orchestration system,
7. or a polished end-user product.

---

## 7. Decisions already locked

These decisions are part of the official build direction.

### 7.1 Trading venue and asset type

1. **Binance first**
2. **Spot only**
3. Futures are **not planned for a long time**
4. However, the system should not incur technical debt that makes futures impossible later

This means the code should not assume that “spot-only Binance payloads” are the eternal truth of the product.

The correct approach is:

1. simple internal concepts,
2. Binance-specific translation isolated in an adapter,
3. and room for later expansion without overbuilding now.

---

### 7.2 Provider direction

1. **One provider first**
2. **Grok direct** is a valid starting assumption
3. No need to build OpenRouter or multi-provider support immediately
4. But prompts and model profiles must remain conceptually separate

The architecture should be **single-provider in implementation, provider-ready in structure**.

---

### 7.3 Bot and workflow complexity

1. **One bot at the beginning**
2. **One simple core structure**
3. But it must be **ready to welcome more later**
4. No watchdog loop in V1
5. No multi-step workflow in V1
6. No multi-bot orchestration in V1

The app should not hardcode itself into “one eternal bot only,” but it should also not build the multi-bot future before it is needed.

---

### 7.4 Automation and live usage

1. **Live usage is the priority**
2. Paper mode is optional but should exist as a **toggle**
3. The system should support both **paper/live mode switching**
4. Live capability is part of V1 seriousness

This is important because the product is not meant to stay a purely simulated prototype.

---

### 7.5 Model autonomy

The model should have **broad freedom**.

Specifically:

1. it may choose assets broadly,
2. it may choose actions,
3. it may propose allocations,
4. it may propose stop loss / take profit logic,
5. and this should remain largely **prompt-governed**

The backend should **not** become a heavy rule engine in V1.

The division of responsibility should be:

1. **the model proposes**
2. **the backend validates**
3. **the exchange executes**

---

### 7.6 Asset universe philosophy

1. The model may choose **any tradable spot asset on Binance**
2. There should be **no heavy allowed-universe engine**
3. There should be **no large manual filtering system**
4. The server should simply verify whether the chosen asset is currently tradable

A synchronized venue catalog exists only to answer one key question:

> Can this asset actually be traded right now on the selected venue?

That is enough for V1.

---

### 7.7 Data ambition

The data model should be **lean but meaningful**.

The chosen posture is:

1. not minimal to the point of blindness,
2. not large and speculative,
3. but sufficient to support:

   * run clarity,
   * decision traceability,
   * execution understanding,
   * prompt versioning,
   * model swapping,
   * historical comparison.

---

### 7.8 Frontend posture

The frontend should be:

1. **internal**
2. **lean**
3. **simple**
4. **functional**
5. **framework-like in consistency**
6. not overdesigned,
7. and not a time sink

It exists to support:

1. observability,
2. control,
3. configuration,
4. debugging,
5. and fast iteration.

It is not the product center of gravity.

---

## 8. The single most important architectural rule

The most important architectural rule is:

> **The system must clearly separate what the model decided from what the exchange actually executed.**

This means the system must always preserve the difference between:

1. prompt and model configuration,
2. runtime context,
3. raw model output,
4. interpreted structured decision,
5. backend validation result,
6. order intent / order request,
7. venue execution result,
8. resulting portfolio state.

This separation is essential for:

1. auditability,
2. debugging,
3. comparison,
4. replay,
5. future improvements,
6. and avoiding hidden technical debt.

If this separation is lost, the project will quickly become hard to trust and hard to evolve.

---

## 9. V1 product model

The cleanest mental model is:

### 9.1 A bot

A bot is the thing that runs.

It represents:

1. a trading identity,
2. an operational unit,
3. a scheduled autonomous actor.

### 9.2 A prompt

A prompt defines **how the bot thinks**.

### 9.3 A prompt version

A prompt version is a **frozen historical instruction**.

It must be immutable once created.

### 9.4 A model profile

A model profile defines **which provider/model/settings** power the run.

### 9.5 A runtime config

A runtime config defines **how the bot lives operationally**, including:

1. venue,
2. frequency,
3. enabled/disabled state,
4. paper/live mode,
5. relevant execution options.

### 9.6 A run

A run is **one full decision cycle**.

### 9.7 A decision

A decision is **what the model proposed**, stored in structured form.

### 9.8 An execution

An execution is **what the venue actually did**.

This is factual and separate from model intent.

---

## 10. Lean V1 feature scope

The actual V1 heartbeat is simple.

### 10.1 Bot loop

1. scheduler checks active bots,
2. selected bot is due,
3. system loads active prompt version,
4. system loads model profile,
5. system loads runtime config,
6. system builds compact context,
7. model returns structured decision,
8. backend validates the decision,
9. Binance adapter translates to venue order(s),
10. execution is attempted,
11. run is recorded,
12. UI reflects the latest state.

That is the product core.

Everything else is extension.

---

## 11. Trading and decision shape for V1

### 11.1 Asset class

1. **Spot only**

### 11.2 Portfolio structure

1. **Portfolio allocation thinking**
2. The bot may manage a **multi-position portfolio**
3. This is important: V1 is not limited to a single asset action only

### 11.3 Decision complexity

The system should support structured decisions rich enough for:

1. portfolio allocation intent,
2. buy / sell / hold style logic,
3. optional stop loss,
4. optional take profit,
5. rationale,
6. confidence / conviction,
7. optional time horizon.

This should remain **prompt-governed**, but the output must still be structured.

### 11.4 Order complexity

The system should support:

1. **market orders**
2. **limit orders**
3. **native stop-loss / take-profit capable structure**

This does add some complexity, but it is acceptable because it aligns with the desired prompt-driven richness.

Important: even with this complexity, V1 should not turn into a giant execution framework.
Support only what is clearly necessary for the intended first strategies.

---

## 12. Recommended structured decision format

The model should return a structured object, not vague prose.

A good V1 decision shape should support something conceptually like:

1. **decision mode**

   * rebalance / enter / exit / hold / adjust

2. **portfolio intent**

   * target allocations by asset

3. **per-asset action objects**

   * asset
   * action
   * target allocation or size intent
   * order preference
   * optional limit price
   * optional stop loss
   * optional take profit
   * confidence / conviction
   * rationale summary

4. **global rationale**

   * concise explanation of portfolio logic

This does **not** mean the system should expose raw unstructured thinking as execution truth.
The model may think broadly, but the backend must consume a strict schema.

---

## 13. Context philosophy

A central principle is:

> **Store more than you send.**

The system may preserve useful historical information in the database, but the model should receive **only compact, relevant context**.

### 13.1 Context should include, at minimum

1. wallet state,
2. current spot holdings / positions,
3. selected venue,
4. bot identity or role context,
5. active prompt version,
6. output schema / execution constraints,
7. compact internal state if useful.

### 13.2 Context should not include by default

1. giant logs,
2. huge raw histories,
3. bloated market data dumps,
4. large speculative memory payloads,
5. unnecessary JSON walls.

The context builder must remain disciplined.

---

## 14. Backend validator philosophy

The backend validator should remain **simple but strict**.

It should not become a giant manual risk engine in V1.

Its job is to verify practical correctness such as:

1. is the asset tradable on Binance spot,
2. are the order parameters valid,
3. does the wallet have sufficient funds,
4. is the requested order type valid,
5. does the chosen mode allow execution,
6. did submission succeed,
7. can exchange responses be tracked correctly.

That is enough for V1.

---

## 15. Venue architecture philosophy

The system should avoid raw Binance lock-in without building a heavy multi-venue framework.

The correct V1 design is:

1. **small internal business vocabulary**
2. **Binance adapter module**
3. **server-side tradability and validity checks**
4. **raw venue responses stored for debugging and audit**

This is sufficient to prevent avoidable technical debt while staying lean.

### 15.1 Internal concepts should be things like

1. Bot
2. PromptVersion
3. ModelProfile
4. RuntimeConfig
5. Run
6. PortfolioSnapshot
7. Decision
8. OrderIntent
9. Execution
10. ValidationResult

The core should think in those concepts.
The Binance adapter handles translation.

---

## 16. Prompt philosophy

Prompts are first-class assets.

They should not live as mutable strings hidden in code.

### 16.1 Prompt requirements

1. prompts must be stored in the database,
2. edits must create new prompt versions,
3. prompt versions must be immutable,
4. bots must reference prompt versions,
5. runs must record the exact prompt version used.

### 16.2 Why this matters

Because the platform must later be able to answer:

1. which prompt version produced this behavior,
2. whether prompt version B behaved better than version A,
3. what exact wording was used at the time of a decision.

This is a core anti-debt rule.

---

## 17. Model philosophy

Prompts and models must remain separate.

A model profile should capture:

1. provider,
2. model name,
3. settings / parameters,
4. invocation-related options.

This allows the system to compare:

1. same prompt, different model,
2. same bot, different model,
3. same structure, cheaper or faster model,
4. same strategy, different provider later.

Do not fuse model choice into prompt identity.

---

## 18. Runtime configuration philosophy

Runtime behavior belongs in runtime config, not inside prompt text and not hardcoded in the scheduler.

The runtime config should include at least:

1. enabled / disabled,
2. venue,
3. refresh frequency,
4. live / paper mode,
5. relevant execution toggles,
6. possibly future optional flags.

This keeps prompt reasoning and operational behavior properly separated.

---

## 19. Scheduling decision

The scheduling layer should stay simple and generic.

Its job is to:

1. determine which bots are due,
2. trigger runs,
3. record success/failure,
4. stay out of strategy logic.

### 19.1 Default V1 frequency decision

Because frequency was intentionally left undecided, the recommended V1 assumption is:

1. **default to 15 minutes**
2. support configurable values such as:

   * 5 minutes
   * 15 minutes
   * 30 minutes
   * 60 minutes

This gives a strong balance between:

1. iteration speed,
2. operational visibility,
3. live usefulness,
4. and not creating unnecessary churn too early.

---

## 20. Data model philosophy

The database should be **small, serious, and useful**.

It should store enough to make the system understandable and comparable, but not speculative structures for distant future ideas.

### 20.1 Minimum serious entities for V1

A lean but strong V1 schema should include at least:

1. **prompts**
2. **prompt_versions**
3. **model_profiles**
4. **bots**
5. **bot_runtime_configs**
6. **runs**
7. **decisions**
8. **executions**
9. **portfolio_snapshots**

That is already enough to support:

1. versioning,
2. traceability,
3. comparison,
4. clear UI views,
5. and future extension.

---

## 21. What should be stored per run

The recommended “lean but serious” run record should preserve:

1. bot identity
2. runtime config used
3. prompt version used
4. model profile used
5. compact context sent
6. raw model output
7. parsed structured decision
8. backend validation result
9. order intent(s)
10. exchange submission/result
11. portfolio snapshot before run
12. portfolio snapshot after run
13. error state if any
14. timestamps and statuses

This is the right balance between:

1. observability,
2. replayability,
3. debugging,
4. and avoiding useless data sprawl.

---

## 22. Technical debt to actively avoid

The most important forms of technical debt to avoid are:

1. **business logic tightly mixed with Binance-specific logic**
2. **model output and execution result being fused together**
3. **prompts not being versioned**
4. **runtime config hardcoded into code paths**
5. **poor run/execution traceability**
6. **scheduler logic mixed with strategy logic**
7. **a database model too weak to support comparison**
8. **UI logic becoming the place where core business rules live**

These are the debts most likely to make the project painful later.

---

## 23. Dashboard philosophy and minimum scope

The dashboard should be a **lean internal control tower**.

It should not be a product rabbit hole.

### 23.1 Minimum V1 dashboard capabilities

The dashboard should allow the operator to view:

1. list of bots
2. bot enabled/disabled status
3. refresh frequency
4. active prompt version
5. active model profile
6. live/paper mode
7. last run status
8. latest decision summary
9. latest orders / executions
10. current holdings / positions
11. recent PnL / portfolio state
12. logs / recent errors
13. prompt version history

### 23.2 Minimum V1 editing capabilities

The dashboard should allow the operator to manage:

1. prompts
2. prompt versions
3. model selection
4. refresh frequency
5. enabled / disabled state
6. live / paper toggle
7. bot assignment of prompt/model/config

Venue selection may still exist conceptually, but with Binance as the only real V1 implementation.

The key principle is:

> Make iteration fast, but keep the UI simple and operational.

---

## 24. What is deliberately out of scope in V1

To protect speed and maintain clarity, the following should remain out of scope initially:

1. futures trading,
2. real multi-venue support,
3. multi-bot orchestration,
4. watchdog / review loop,
5. multi-step research workflows,
6. large signal standardization systems,
7. tweet normalization pipelines,
8. advanced memory retrieval systems,
9. heavy manual risk/policy engines,
10. deep backtesting systems,
11. automated strategy generation,
12. large-scale ML infrastructure,
13. enterprise auth/permissions complexity,
14. consumer-grade product polish.

These are future possibilities, not V1 requirements.

---

## 25. Future-readiness without overbuilding

Future-proofing in this project does **not** mean maximum abstraction.

It means maintaining the correct boundaries:

1. prompt vs model,
2. bot vs runtime config,
3. decision vs execution,
4. platform core vs Binance adapter,
5. stored history vs sent context.

That is enough.

If these boundaries are respected, the system can later extend into:

1. more bots,
2. more providers,
3. more venues,
4. futures support,
5. staged workflows,
6. richer comparison tools.

But none of that should distort V1.

---

## 26. Recommended build order

### Phase 0 — Foundation

Build:

1. monorepo structure,
2. internal types,
3. database schema,
4. model provider integration,
5. Binance spot adapter,
6. scheduler,
7. run recording system,
8. dashboard skeleton.

Goal:

> A lean but durable product skeleton.

---

### Phase 1 — First real autonomous loop

Build:

1. one bot,
2. prompt versioning,
3. model profile support,
4. runtime config support,
5. compact context builder,
6. structured decision schema,
7. backend validator,
8. order translation and execution,
9. run / decision / execution persistence,
10. basic dashboard visibility.

Goal:

> Get one real autonomous bot running clearly.

---

### Phase 1.5 — Operator control and iteration speed

Build:

1. prompt version management from UI,
2. model switching from UI,
3. frequency editing,
4. live / paper toggle,
5. improved logs and run inspection,
6. better execution visibility.

Goal:

> Make the system fast to operate and fast to iterate.

---

### Phase 2 — Comparison layer

Build:

1. easier prompt-to-prompt comparison,
2. easier model-to-model comparison,
3. better performance views,
4. cleaner history navigation.

Goal:

> Turn the product into a useful iteration platform.

---

### Phase 3+ — Optional future expansion

Possible later additions:

1. more bots,
2. more providers,
3. richer workflow roles,
4. futures,
5. more venues,
6. policy layers,
7. memory and retrieval,
8. advanced strategy comparison.

Only build these if the core loop proves valuable.

---

## 27. Rules Cursor should follow while building

Cursor should treat the following as implementation rules:

1. **Do not overbuild**
2. **Do not create heavy abstractions for future features that are not being implemented yet**
3. **Do keep boundaries clean where they matter**
4. **Do separate model decision from execution result**
5. **Do keep Binance-specific translation isolated**
6. **Do make prompts versioned and immutable once created**
7. **Do keep runtime config separate from prompt logic**
8. **Do store enough for auditability and comparison**
9. **Do keep the dashboard lean and operational**
10. **Do avoid putting business logic in the frontend**
11. **Do keep the scheduler generic**
12. **Do prefer simple, composable modules over giant framework layers**
13. **Do not build a giant policy engine in V1**
14. **Do not build speculative signal systems in V1**
15. **Do not optimize for perfect future generality at the expense of present clarity**
16. **Do build code that can survive extension later**

---

## 28. Success definition for V1

A successful V1 is one where:

1. a bot can run autonomously on schedule,
2. it uses a prompt version and model profile cleanly,
3. it produces structured decisions,
4. the backend validates correctly,
5. it executes properly on Binance spot,
6. the operator can run in live or paper mode,
7. the system records each run clearly,
8. the UI makes the system understandable,
9. prompt and config iteration are fast,
10. and the codebase remains lean, modular, and adaptable.

The first success condition is **not** exceptional returns.
The first success condition is a **real, understandable, extensible autonomous trading loop**.

---

## 29. Final synthesis

This product should be built as a **lean, live-capable, prompt-driven autonomous spot trading platform** with one clear goal:

> Launch one serious autonomous bot quickly, without creating the kind of technical debt that would force a rebuild later.

The system should therefore:

1. stay narrow in scope,
2. stay disciplined in structure,
3. separate thinking from execution,
4. keep prompts and models versionable and swappable,
5. keep the UI lean but operational,
6. preserve strong run history,
7. and remain ready for future growth without pretending to be a giant platform from day one.

That is the correct balance between:

1. speed,
2. modularity,
3. clarity,
4. future adaptability,
5. and disciplined technical execution.
