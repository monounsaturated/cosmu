# COSMU — Product Vision & User Profile (tailor the build to THIS operator)

The north-star UX, so every agent builds toward how the operator actually wants to use it.

## 👤 Who the operator is
A **trend-spotter** (social media, tweets, Reddit, narratives) who wants to drive a **deep quant machine by talking
to it in Claude Code** — not by writing code. They think in ideas/vibes ("test funding-contrarian on small caps",
"does Reddit buzz lead price?") and want the machine to turn that into a rigorously-tested answer. They want to
**make money**, with something that's **actually used** — functional, not a tech demo.

## 🎯 What it must feel like (inspired by a Hermes-style agent: fast · capable · tool-using · well-behaved)
1. **Natural-language front door (Claude Code).** "Backtest / stress-test this idea" → typed StrategySpec → the Gate →
   an honest verdict, conversationally. The operator never hand-writes specs; they *describe*, the agent authors.
2. **Tons of well-behaved skills.** A rich verb set (`strategize`, `scan-signals`, `add-data-source`, `run-gate`,
   `debug-strategy`, `evolve-strategy`, `manage-data`, …) the operator invokes in plain language. Skills = the hands.
3. **Clean cross-data + the LLM's vibing ability.** Easy access to clean, point-in-time data across many sources
   (social, price, funding, on-chain, macro), so the agent can *try a ton of things* and cross-correlate — fast,
   cheap, honest. The data dictionary (`lunarcrush-data-dictionary.md`) is the model: every source legible to human+LLM.
4. **A real dashboard.** Overview-led, mobile-first, digestible (top-N previews → dedicated sortable pages), shows the
   machine thinking + the lifecycle (Backtest→Simulation→Live) + the money. Built ✅ (#119/#121/#122/#124) — keep refining.
5. **Easy to maintain · no bugs · learning.** Lean modular code agents can manage; the Gate + forward-test prevent
   self-deception; memory + reports make it learn across sessions. QA UI before claiming done (the live-checkbox lesson).
6. **Simple to drive, deep underneath.** The operator's actions are simple ("find me an edge in X"); the *machine's*
   actions are deep + technical (deflated Sharpe, CSCV-PBO, FDR cohorts, PIT joins) — hidden behind the conversation.

## 🧭 The non-negotiables that keep it honest (don't drift)
- **Profit, net of fees, is the only score.** LLM proposes; the deterministic Gate disposes; LLM never touches money.
- **No oracle → no graduation** (finance is the proving ground; other domains wait behind their own incorruptible scorer).
- **Trustworthy measurement before breadth** (this session's lesson — fix the harness before adding markets/sources).

## ✅ What's already true vs the vision
- NL front door + skills: **mostly built** (Claude Code + 21 skills + the strategize/scan-signals flow).
- Clean cross-data: **the pipeline exists**; the harness fix + bar backbone make it trustworthy.
- Dashboard: **built + mobile-first** (refine: data-viz overlay charts, the "cohort" tooltip).
- Honest, learning, no-bug: **the Gate + memory + reports + QA discipline** are the mechanisms; keep tightening.
- **The gap to "used + makes money":** one strategy through the honest Gate + a 30-day forward-test. Everything points there.
