---
name: dump-idea
description: Natural-language strategy intake — turn a loose idea (chat or .md) into a typed StrategySpec in `strategies/inbox/`. Use when the user describes a trading idea informally and wants it captured for the Gate.
---

# dump-idea

Capture a half-formed idea as a real spec without losing the thesis. Compose from named building blocks — **no magic numbers** (thresholds go in `param_space`). For a fully-specified strategy use `/create-strategy`; for Pine code use `/import-pine`.

## Steps
1. **Read the idea** — from chat, or a `.md` file the user points to.
2. **Extract:** asset/venue, signal type, direction (long/short/cross-sectional), thesis (the *why*), timeframe.
3. **Compose a `StrategySpec`** from named building blocks — `feature_registry` features + composable signal modules. Reuse, don't invent.
4. **Run `static_check`** — if any magic number is found, lift it into `param_space` (a fitted range, not a constant).
5. **Write** to `strategies/inbox/<name>.json`.
6. **Report:** "Spec written to `strategies/inbox/<name>.json`. Run `/run-gate` to test it, or let the autonomous tick pick it up on next deploy."

## Verify
- `static_check` + `compile_spec` pass on the written spec (no magic numbers, no inert signal).
- The spec file names a real venue and a feature that exists in `feature_registry`.
