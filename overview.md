# Global Context Document — Lean Autonomous Trading Platform (V1-first, future-ready)

## 1. Document purpose

This document is the **global product, architecture, and implementation context** for building the app.

It should be treated as the **source of truth** for:

1. product intent,
2. architectural direction,
3. implementation posture,
4. stack choices,
5. V1 scope,
6. non-goals,
7. practical constraints,
8. extension logic,
9. and anti-debt rules.

This is not a brainstorming note, not a vague vision statement, and not a speculative future roadmap disguised as present requirements.

The purpose of this document is to ensure the product is built in a way that is:

1. **lean at the beginning,**
2. **modular and adaptable,**
3. **fast to ship,**
4. **clear to operate,**
5. **low in avoidable technical debt,**
6. **observable enough to iterate confidently,**
7. and **ready to grow later without requiring a rebuild.**

---

## 2. Product in one sentence

This product is a **lean, prompt-driven autonomous spot trading platform** that runs bots on a schedule, lets an LLM make structured portfolio decisions, validates and executes those decisions on Binance, records what happened with clarity, and is designed so it can later support more bots, more providers, more venues, richer workflows, and future learning systems without collapsing into technical debt.

---

## 3. Global philosophy

The ultimate goal of this product is simple:

> **make money.**

This is not a research project for its own sake, and it is not an exercise in building an elegant AI platform disconnected from outcomes.

The purpose of the system is to generate trading performance by using LLMs as practical tools for:

1. reasoning,
2. adaptation,
3. experimentation,
4. and execution.

The edge of this product is **not** supposed to come from building:

1. the most complex infrastructure,
2. the most academic signal pipeline,
3. the heaviest architecture,
4. or the most rigid platform.

Its edge should come from:

1. **speed of iteration,**
2. **speed of deployment,**
3. **the ability to switch quickly between models, tools, and workflows,**
4. **the ability to test and compare prompts systematically,**
5. **the ability to adopt useful new tools quickly,**
6. **the ability to discard what does not work,**
7. and **the ability to learn faster than slower, more rigid competitors.**

The ambition is not to imitate traditional trading firms by copying their structure.
The ambition is to compete differently:

> **through rapidity.**

This means the platform should be built to make it easy to:

1. try new prompts,
2. compare prompt versions,
3. switch models quickly,
4. add or remove useful modules,
5. adopt new tools when they appear,
6. compare behaviors and outcomes over time,
7. and continuously improve the system through short feedback loops.

The product should therefore remain:

1. **lean**, so it can move quickly,
2. **modular**, so components can be replaced without rebuilding the whole system,
3. **interoperable**, so future models, tools, venues, and workflows can be added with limited friction,
4. **observable**, so it is always clear what the bot did and why,
5. and **disciplined enough that iteration creates knowledge instead of chaos.**

A core part of the product’s value is not only running bots, but being able to:

1. test different prompts and setups,
2. measure which ones work,
3. quantify how they behave,
4. and compare them over time.

The system must make it easy to identify:

1. what is producing useful outcomes,
2. what is producing noise,
3. what should be kept,
4. and what should be discarded.

In that sense, this product is both:

1. **a live trading engine**,
2. and **an iteration engine**.

The trading engine exists to act.
The iteration engine exists to improve what acts.

The platform should not overbuild for hypothetical future needs, but it must preserve the right foundations:

1. prompt versioning,
2. model interchangeability,
3. clear run history,
4. structured decisions,
5. execution traceability,
6. disciplined persistence,
7. and enough stored data to compare outcomes meaningfully.

In short, this product should be built as:

> **a lean autonomous trading system designed to make money by iterating faster, adapting faster, and learning faster than more rigid competitors.**

---

## 4. Core philosophy

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
5. a prompt experiment with poor execution discipline,
6. or a “future-proof” system so generalized that it becomes slow and annoying to build.

---

## 5. Practical implementation constraints

The following practical constraints should guide implementation decisions from the start.

### 5.1 TypeScript-first

The product should be **TypeScript-first**.

This is the default posture because it supports:

1. shared types across backend and frontend,
2. faster iteration,
3. clearer contracts,
4. less context switching,
5. and a more coherent codebase for a system that will evolve quickly.

Python may later exist for specific workloads such as:

1. ML experiments,
2. compute-heavy analytics,
3. or specialized offline processing,

but Python should **not** define the main product architecture in V1.

---

### 5.2 Concrete stack

The exact stack to anchor around is:

1. **TypeScript-first**
2. **pnpm monorepo**
3. **Node backend**
4. **Next.js frontend**
5. **Supabase Postgres**
6. **Railway** for API / workers / scheduler
7. **Vercel** for the internal frontend
8. **GitHub** for versioning / workflow / deployment flow
9. **Python optional later**, only when justified

This means:

1. the main backend runtime is Node,
2. the main frontend is Next.js,
3. the main application database is Postgres through Supabase,
4. long-running backend and scheduled execution live on Railway,
5. the frontend deploys through Vercel,
6. and the operational build flow should feel natural inside a GitHub-centered workflow.

These choices are not ideological.
They are chosen because they support:

1. fast shipping,
2. low operational drag,
3. good developer ergonomics,
4. strong iteration loops,
5. and a practical internal-tooling workflow.

---

### 5.3 Deployment workflow

The practical product workflow should assume:

1. **Cursor → GitHub → Vercel preview → direct testing**
2. Railway for the backend always-on path
3. the frontend exists early because it helps test what the AI generated
4. the frontend serves as an **observability and control layer**, not as a polished final product

This matters because much of the code may be produced, revised, or accelerated by LLM tools.
A fast preview-and-check workflow is therefore strategically important.

---

### 5.4 Frontend posture

The frontend is:

1. an **internal admin / control interface**,
2. **not** a polished product UX for external users.

It should prioritize:

1. operational clarity,
2. observability,
3. configuration,
4. debugging,
5. and iteration speed.

It should not optimize for:

1. consumer polish,
2. onboarding flows,
3. marketing-style UX,
4. or complex end-user product behavior.

---

### 5.5 Internal frontend security

The frontend should be treated as **internal-only** at the beginning.

That means:

1. no need for full product-grade auth at first,
2. no need for multi-user permission complexity in V1,
3. and no need for Cursor to invent an entire authentication subsystem prematurely.

The intended early access posture is:

1. internal frontend only,
2. ideally only accessible to the intended operator,
3. protected through **Vercel Authentication / deployment protection** or equivalent lightweight access control,
4. with proper product auth deferred until it is actually needed.

The purpose is simple:

> make the internal dashboard safely usable without letting auth complexity distort V1.

---

### 5.6 Prompt editing and storage model

Prompts should be:

1. stored in the database,
2. editable from the internal frontend,
3. versioned through immutable prompt versions,
4. and never treated as mutable hidden strings in code.

This is a non-negotiable rule because prompt iteration is one of the core engines of product value.

It should be possible to:

1. create prompts,
2. create prompt versions,
3. inspect prompt history,
4. assign prompt versions to bots,
5. and edit prompts without redeploying code.

---

### 5.7 V1 shaping rule

If a future feature is **not needed for the first live autonomous loop**, then V1 should **not be shaped around it**.

This rule is extremely important.

It means:

1. do not distort the architecture for speculative features,
2. do not introduce large abstractions for workflows that do not exist yet,
3. do not create frameworks for optional future modules,
4. and do not let hypothetical expansion slow down the first serious autonomous loop.

Future readiness should come from:

1. good boundaries,
2. clean internal concepts,
3. modularity where it matters,
4. and disciplined persistence,

not from building tomorrow’s complexity today.

The anti-future-creep rule can be stated explicitly as:

> **If a future-oriented idea is not required for the first live autonomous loop, it should not shape the implementation of V1 beyond preserving clean boundaries.**

---

## 6. What matters most

The top priorities for V1 are:

1. **Time to first real autonomous bot**
2. **Auditability / clarity**
3. **Iteration speed**

This means V1 should be judged primarily by whether:

1. one bot can run autonomously in a real environment,
2. the operator can clearly understand what happened,
3. prompts and configs can be changed quickly,
4. the system is easy to improve without structural pain,
5. and each live run produces usable information for future comparison.

Financial performance matters later, but it is **not** the primary product success metric for the first serious version.

At the same time, the broader business logic remains true:

> the reason to build this system is ultimately to generate trading performance.

So V1 should optimize the preconditions for that outcome:

1. live capability,
2. disciplined execution,
3. clear run history,
4. high interpretability,
5. and fast iteration.

---

## 7. Strategic direction chosen

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

## 8. V1 scope and design posture

### 8.1 What V1 is

V1 is:

1. an **internal-use autonomous trading product**
2. with **one serious bot**
3. designed around **one live-capable loop**
4. using **prompt-driven reasoning**
5. and **clear execution + recording discipline**

### 8.2 What V1 is not

V1 is not:

1. a full multi-venue platform,
2. a futures system,
3. a deep portfolio research engine,
4. a broad signal normalization platform,
5. a sophisticated manual risk engine,
6. a multi-agent orchestration system,
7. or a polished external product.

### 8.3 Bot vs platform

It is important to keep the right ambition in mind:

1. V1 is **one serious bot**
2. but the product is also **the beginning of a platform**

This should **not** inflate V1 scope.
It should only influence the quality of boundaries.

In other words:

1. do not build the whole platform now,
2. but do build V1 in a way that the future platform does not require a restart.

---

## 9. Decisions already locked

These decisions are part of the official build direction.

### 9.1 Trading venue and asset type

1. **Binance first**
2. **Spot only**
3. Futures are **not planned for a long time**
4. However, the system should not incur technical debt that makes futures impossible later

This means the code should not assume that “spot-only Binance payloads” are the eternal truth of the product.

The correct approach is:

1. simple internal concepts,
2. Binance-specific translation isolated in an adapter,
3. and enough separation that futures or other venues can be added later without rewriting the core.

---

### 9.2 Provider direction

1. **One provider first**
2. **Grok direct** is a valid starting assumption
3. No need to build OpenRouter or multi-provider support immediately
4. But prompts and model profiles must remain conceptually separate

The architecture should be **single-provider in implementation, provider-ready in structure**.

---

### 9.3 Bot and workflow complexity

1. **One bot at the beginning**
2. **One simple core structure**
3. But it must be **ready to welcome more later**
4. No watchdog loop in V1
5. No multi-step workflow in V1
6. No multi-bot orchestration in V1

The app should not hardcode itself into “one eternal bot only,” but it should also not build the multi-bot future before it is needed.

---

### 9.4 Automation and live usage

1. **Live usage is the priority**
2. Testnet mode is optional but should exist as a **toggle**
3. Testnet mode should also exist as a practical integration mode
4. The system should support **testnet / live distinctions**
5. Live capability is part of V1 seriousness

This matters because the system is not meant to remain a purely simulated prototype.

---

### 9.5 Model autonomy

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

### 9.6 Asset universe philosophy

1. The model may choose **any tradable spot asset on Binance**
2. There should be **no heavy allowed-universe engine**
3. There should be **no large manual filtering system**
4. The server should simply verify whether the chosen asset is currently tradable

A synchronized venue catalog exists only to answer one key question:

> Can this asset actually be traded right now on the selected venue?

That is enough for V1.

---

### 9.7 Data ambition

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
   * historical comparison,
   * and future leverage.

---

### 9.8 Frontend posture

The frontend should be:

1. **internal**
2. **lean**
3. **simple**
4. **functional**
5. **consistent**
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

## 10. Trading engine + iteration engine

This product should always be understood as two tightly linked systems:

### 10.1 A trading engine

Its job is to:

1. make decisions,
2. place orders,
3. track execution,
4. and manage real trading behavior.

### 10.2 An iteration engine

Its job is to:

1. compare prompts,
2. compare models,
3. keep version history,
4. preserve run history,
5. identify what is working,
6. and improve the live system through feedback loops.

This distinction matters because the product is not valuable merely because a bot can trade.

It becomes strategically valuable when it can also:

1. compare different trading setups,
2. quantify differences,
3. learn faster,
4. and compound knowledge over time.

---

## 11. The single most important architectural rule

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

## 12. Internal business types and canonical product concepts

The product core should depend on **internal business types**, not on raw Binance payloads.

This is important because:

1. Binance is not the canonical product model,
2. Binance is only one venue implementation,
3. the product should reason in its own concepts,
4. and venue adapters should handle translation.

The core should think in concepts such as:

1. `Bot`
2. `Prompt`
3. `PromptVersion`
4. `ModelProfile`
5. `RuntimeConfig`
6. `Run`
7. `Decision`
8. `ValidationResult`
9. `OrderIntent`
10. `Execution`
11. `PortfolioSnapshot`

This matters because later the system may support:

1. different venues,
2. different execution models,
3. futures,
4. richer workflows,
5. and additional internal modules.

If the core depends directly on Binance payload structure everywhere, extension later becomes much more painful.

The correct relationship is:

1. the **core depends on internal types**
2. the **Binance adapter translates to and from Binance**
3. Binance is an implementation detail of the venue layer, not the whole product’s truth

---

## 13. V1 product model

The cleanest mental model is:

### 13.1 A bot

A bot is the thing that runs.

It represents:

1. a trading identity,
2. an operational unit,
3. a scheduled autonomous actor.

### 13.2 A prompt

A prompt defines **how the bot thinks**.

### 13.3 A prompt version

A prompt version is a **frozen historical instruction**.

It must be immutable once created.

### 13.4 A model profile

A model profile defines **which provider/model/settings** power the run.

### 13.5 A runtime config

A runtime config defines **how the bot lives operationally**, including:

1. venue,
2. frequency,
3. enabled/disabled state,
4. mode,
5. relevant execution options.

### 13.6 A run

A run is **one full decision cycle**.

### 13.7 A decision

A decision is **what the model proposed**, stored in structured form.

### 13.8 An execution

An execution is **what the venue actually did**.

This is factual and separate from model intent.

---

## 14. Lean V1 feature scope

The actual V1 heartbeat is simple.

### 14.1 Bot loop

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
12. UI reflects the latest state,
13. notifications may be sent for important events.

That is the product core.

Everything else is extension.

---

## 15. Trading and decision shape for V1

### 15.1 Asset class

1. **Spot only**

### 15.2 Portfolio structure

1. **Portfolio allocation thinking**
2. The bot may manage a **multi-position portfolio**
3. V1 is not limited to a single asset action only

### 15.3 Decision complexity

The system should support structured decisions rich enough for:

1. portfolio allocation intent,
2. buy / sell / hold logic,
3. optional stop loss,
4. optional take profit,
5. rationale,
6. confidence / conviction,
7. optional time horizon.

This should remain **prompt-governed**, but the output must still be structured.

### 15.4 Order complexity

The system should support:

1. **market orders**
2. **limit orders**
3. **native stop-loss / take-profit-capable structure**, where appropriate

This adds some complexity, but it is acceptable because it aligns with the desired prompt-driven richness.

V1 should still avoid turning into a giant execution framework.
Support only what is actually needed for the intended first strategies.

---

## 16. Recommended structured decision format

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

## 17. Context philosophy

A central principle is:

> **Store more than you send.**

The system may preserve useful historical information in the database, but the model should receive **only compact, relevant context**.

### 17.1 Context should include, at minimum

1. wallet state,
2. current spot holdings / positions,
3. selected venue,
4. bot identity or role context,
5. active prompt version,
6. output schema / execution constraints,
7. compact internal state if useful.

### 17.2 Context should not include by default

1. giant logs,
2. huge raw histories,
3. bloated market data dumps,
4. large speculative memory payloads,
5. unnecessary JSON walls.

The context builder must remain disciplined.

---

## 18. Backend validator philosophy

The backend validator should remain **simple but strict**.

Its role is **not** to do strategy.
Its role is **not** to become a real risk engine in V1.

Its job is to validate **practical correctness** and transform a structured decision into something safely executable.

That means it should verify things such as:

1. is the asset tradable on Binance spot,
2. are the order parameters valid,
3. does the wallet have sufficient funds,
4. is the requested order type valid,
5. is the selected mode compatible with execution,
6. did submission succeed,
7. can exchange responses be tracked correctly.

That is enough for V1.

The validator should not try to become:

1. a heavy rule engine,
2. a strategic decision-maker,
3. or a complex policy subsystem.

---

## 19. Venue architecture philosophy

The system should avoid raw Binance lock-in without building a heavy multi-venue framework.

The correct V1 design is:

1. **small internal business vocabulary**
2. **Binance adapter module**
3. **server-side tradability and validity checks**
4. **raw venue responses stored for debugging and audit**

This is sufficient to prevent avoidable technical debt while staying lean.

### 19.1 Binance implementation best practices

The Binance integration should follow practical best practices:

1. **WebSocket-first where appropriate**
2. REST for:

   * bootstrap,
   * fallback,
   * reconciliation,
   * and resync
3. light caching for:

   * symbol metadata,
   * balances,
   * recent prices if needed,
   * trading constraints,
   * exchange metadata
4. robust handling of:

   * API failures,
   * resync cases,
   * partial state uncertainty,
   * and rate-limit awareness
5. persistence of raw venue responses for audit and debugging

The point is not to build a giant market-data subsystem.
The point is to build a robust enough Binance integration for a real autonomous loop.

---

## 20. Mode distinctions: testnet and live

These modes must be treated as distinct.

### 20.2 Testnet mode

Testnet mode means:

1. orders are sent to an exchange test environment,
2. integration behavior is exercised,
3. but real funds are not used.

### 20.3 Live mode

Live mode means:

1. real exchange orders are sent,
2. real funds are affected,
3. execution is real.

These concepts must not be collapsed into one vague mode flag.

For V1, the system should support:

1. **testnet/live toggle** as product functionality,
2. and a practical **testnet/live environment distinction** at the exchange integration layer.

The initial implementation may expose testnet/live via environment configuration first, and potentially later via dashboard controls.

---

## 21. Scheduling decision

The scheduling layer should stay simple and generic.

Its job is to:

1. determine which bots are due,
2. trigger runs,
3. record success/failure,
4. stay out of strategy logic.

### 21.1 Default V1 frequency decision

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
4. and avoiding unnecessary churn too early.

Refresh frequency belongs in runtime config, not in prompt text and not hardcoded into the scheduler.

---

## 22. Prompt philosophy

Prompts are first-class assets.

They should not live as mutable strings hidden in code.

### 22.1 Prompt requirements

1. prompts must be stored in the database,
2. edits must create new prompt versions,
3. prompt versions must be immutable,
4. bots must reference prompt versions,
5. runs must record the exact prompt version used.

### 22.2 Prompt operations

The frontend should allow the operator to:

1. create prompts,
2. create new prompt versions,
3. inspect prompt version history,
4. assign prompt versions to bots,
5. switch active versions,
6. and compare outcomes across versions later.

### 22.3 Why this matters

Because the platform must later be able to answer:

1. which prompt version produced this behavior,
2. whether prompt version B behaved better than version A,
3. what exact wording was used at the time of a decision.

This is a core anti-debt rule.

---

## 23. Model philosophy

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

Future providers may later include:

1. OpenAI,
2. Claude,
3. OpenRouter,
4. and other tools as they become relevant.

These are future possibilities, not V1 obligations.

---

## 24. Runtime configuration philosophy

Runtime behavior belongs in runtime config, not inside prompt text and not hardcoded in the scheduler.

The runtime config should include at least:

1. enabled / disabled,
2. venue,
3. refresh frequency,
4. mode,
5. relevant execution toggles,
6. possibly future optional flags.

This keeps prompt reasoning and operational behavior properly separated.

---

## 25. Data model philosophy

The database should be **small, serious, and useful**.

It should store enough to make the system understandable, replayable, and comparable, but not speculative structures for distant future ideas.

### 25.1 The database is a strategic asset

The database is **not just storage**.

It is:

1. the memory of the system,
2. the audit trail,
3. the foundation for comparison,
4. the basis for replay,
5. a future retrieval substrate,
6. a future ML substrate,
7. and one of the long-term moats of the product.

Every run should create **historical leverage**.

That means each run should leave behind usable structure that helps answer questions like:

1. what did the model see,
2. what did it propose,
3. what was actually executed,
4. what happened after,
5. which prompt version was used,
6. which model was used,
7. which setups worked better over time.

This is one of the biggest long-term strategic assets of the platform.

---

### 25.2 Minimum serious entities for V1

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

## 26. What should be stored per run

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
4. future comparison,
5. and avoiding useless data sprawl.

---

## 27. Fee tracking, PnL, and execution realism

The system must track execution economics properly.

This is not optional, because otherwise the platform may falsely classify a strategy as profitable.

The execution layer should track, as accurately as possible:

1. **fees per fill**
2. **fee asset**
3. **gross PnL**
4. **net PnL**
5. **slippage**, where reasonably possible
6. fee aggregation by:

   * execution,
   * trade,
   * run,
   * bot

This matters because a strategy that appears profitable before costs may be weak or negative after fees and slippage.

---

## 28. Future learning, retrieval, and ML posture

Memory, retrieval, and learning are **not V1 features**.

But they are **architectural considerations**.

That means the system should preserve the right hooks without implementing the full future subsystems.

V1 should preserve enough structure for future learning-oriented use cases by storing things like:

1. raw model output,
2. parsed structured decision,
3. compact context sent,
4. prompt version used,
5. model profile used,
6. before/after portfolio snapshots,
7. execution outcomes,
8. useful metadata for future comparison.

The point is:

1. do not build retrieval now,
2. do not build ML pipelines now,
3. but do preserve the historical ingredients that would make them possible later.

---

## 29. Modules should be activatable, replaceable, or ignorable

The product should be modular in a practical way.

This means some future modules should be capable of being:

1. activated,
2. deactivated,
3. replaced,
4. or left unused,

without breaking the core system.

Examples of future modules that should fit this pattern include:

1. policy layer,
2. watchdog / review loop,
3. retrieval,
4. multi-provider support,
5. multi-venue support,
6. learning-oriented modules,
7. richer comparison systems.

This does **not** mean these should be fully implemented in V1.

It means the product should avoid being structured in a way that makes them awkward or destructive later.

---

## 30. Technical debt to actively avoid

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

## 31. Observability as a major product requirement

Observability is not a luxury.
It is one of the major product requirements.

This matters especially because:

1. much of the product may be accelerated by LLM-generated code,
2. the system is autonomous,
3. and opaque behavior would make iteration slow and risky.

The operator must be able to see quickly:

1. what the bot did,
2. why it did it,
3. what was sent to the model,
4. what came back,
5. what the backend accepted or rejected,
6. what the exchange executed,
7. and what the resulting state became.

The frontend therefore matters not just as an admin screen, but as a **rapid validation interface** for newly built or AI-generated features.

It allows the operator to inspect the system without constantly rerunning everything from the terminal.

---

## 32. Notifications

Notifications should exist as a practical part of the system, even if they begin very simply.

Possible channels include:

1. Slack,
2. Telegram,
3. or equivalent lightweight notification destinations.

Important notification types may include:

1. trade opened,
2. trade closed,
3. run success,
4. run failure,
5. critical errors,
6. PnL summaries,
7. bot status summaries.

This does not need to become a giant V1 subsystem.
But notifications should be recognized as part of the practical operating framework.

---

## 33. Dashboard philosophy and minimum scope

The dashboard should be a **lean internal control tower**.

It should not be a product rabbit hole.

### 33.1 Why the dashboard exists early

The dashboard exists early because it improves:

1. observability,
2. debugging,
3. confidence,
4. control,
5. and iteration speed.

It is especially important because terminal-only validation is not enough for a fast-moving autonomous system whose code may be heavily assisted by LLMs.

---

### 33.2 Minimum V1 dashboard capabilities

The dashboard should allow the operator to view:

1. list of bots
2. bot enabled/disabled status
3. refresh frequency
4. active prompt version
5. active model profile
6. mode
7. last run status
8. latest decision summary
9. latest orders / executions
10. current holdings / positions
11. recent PnL / portfolio state
12. logs / recent errors
13. prompt version history

---

### 33.3 Minimum V1 editing capabilities

The dashboard should allow the operator to manage:

1. prompts
2. prompt versions
3. model selection
4. refresh frequency
5. enabled / disabled state
6. testnet / live controls
7. bot assignment of prompt/model/config

Venue selection may still exist conceptually, but with Binance as the only real V1 implementation.

The key principle is:

> Make iteration fast, but keep the UI simple and operational.

---

## 34. What is deliberately out of scope in V1

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

## 35. Future possibilities to leave room for

The following are legitimate future possibilities, but should remain future-facing unless clearly needed later:

1. additional venues such as **Hyperliquid**
2. additional venues such as **KuCoin**
3. later expansion into **Polymarket** or other non-standard venues
4. later expansion into other asset classes
5. later providers such as **OpenAI**
6. later providers such as **Claude**
7. future learning loops
8. future comparison layers
9. future strategy generation
10. community indicators / TradingView-style integrations later
11. ML-heavy experiments later

These should influence **boundaries**, not **V1 scope**.

---

## 36. Future-readiness without overbuilding

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
4. futures,
5. staged workflows,
6. richer comparison tools,
7. retrieval,
8. learning-oriented layers.

But none of that should distort V1.

---

## 37. Recommended build order

### Phase 0 — Foundation

Build:

1. pnpm monorepo structure,
2. shared internal types,
3. initial database schema,
4. provider integration,
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
4. testnet / live controls,
5. improved logs and run inspection,
6. better execution visibility,
7. simple notifications.

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
7. retrieval,
8. learning-oriented systems,
9. advanced strategy comparison.

Only build these if the core loop proves valuable.

---

## 38. Rules Cursor should follow while building

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
17. **Do follow the practical stack assumptions unless there is a strong reason not to**
18. **Do treat the frontend as an internal admin tool, not a consumer product**
19. **Do not shape V1 around future features that are not required for the first live loop**
20. **Do preserve the product’s main edge: iteration speed**
21. **Do keep the backend validator narrow and practical**
22. **Do keep the DB useful for future replay and comparison**
23. **Do track fees and execution economics properly**
24. **Do preserve future hooks without implementing future systems prematurely**

---

## 39. Success definition for V1

A successful V1 is one where:

1. a bot can run autonomously on schedule,
2. it uses a prompt version and model profile cleanly,
3. it produces structured decisions,
4. the backend validates correctly,
5. it executes properly on Binance spot,
6. the operator can run in test, or live-oriented modes appropriately,
7. the system records each run clearly,
8. the UI makes the system understandable,
9. prompt and config iteration are fast,
10. and the codebase remains lean, modular, and adaptable.

The first success condition is **not** exceptional returns.
The first success condition is a **real, understandable, extensible autonomous trading loop**.

### 39.1 Second-level success condition

The second-level success condition is:

> **historical leverage.**

Every run should leave behind a trace that is useful later.

That means the system should accumulate:

1. comparable decisions,
2. comparable prompts,
3. comparable model behavior,
4. interpretable execution history,
5. and structured evidence of what worked and what did not.

This is how the product compounds.

---

## 40. Final synthesis

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

This product is not supposed to win by being heavier than incumbents.
It is supposed to win by being:

1. faster to adapt,
2. faster to iterate,
3. faster to deploy,
4. faster to learn,
5. and better at turning each live run into reusable knowledge.

That is the correct balance between:

1. speed,
2. modularity,
3. clarity,
4. future adaptability,
5. disciplined technical execution,
6. practical business intent,
7. and compounding historical leverage.

In final terms, this should be understood as:

> **a lean autonomous trading system built to make money by iterating faster than slower, more rigid competitors, while preserving enough structural discipline that every improvement compounds instead of creating chaos.**

# Additional Information

First, the frontend exists early not only as an internal admin panel, but as a rapid validation layer. It should help test quickly what the AI coded, reduce dependence on terminal-only validation, and make it easier to inspect runs, decisions, and system behavior visually.

Second, future-oriented modules should not only be easy to add later, but also easy to remove later without breaking the core. The platform should support clean reversibility, not only extensibility.

Finally, V1 does not build ML, but the data model should avoid losing the opportunity to support ML later. The product should preserve enough structured historical data so that future learning-oriented systems remain possible without requiring a rebuild of the core data layer.