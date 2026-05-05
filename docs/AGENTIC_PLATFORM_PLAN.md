# Cosmu Agentic Platform Plan

## North Star

Cosmu is evolving from a lean Binance spot bot into a modular autonomous research and trading platform:

- **Cosmu Light** keeps today's operational loop: research prompt, trader prompt, validator, Binance execution, guardian, dashboard.
- **Cosmu Research** is the autonomous research lab: natural-language hypotheses, data sources, backtests, skeptic review, paper bots, and lessons.
- **Cosmu Pro** is the future full agentic trader: multi-agent analysis, risk review, promotion from Research, live execution within strict limits, and post-trade learning.

The long-term goal is full autonomous Pro, but every step must remain observable, testable, and reversible.

## Non-Negotiables

- Light remains available and reliable even as Research and Pro grow.
- The frontend is the command center for observing and controlling agents, bots, data sources, experiments, approvals, and failures.
- Every agent/tool phase leaves an audit trail: input, output, tool calls, model, tokens, duration, status, and errors.
- Research can create paper bots autonomously. Live trading is approval-gated by default.
- Secrets stay in infrastructure env vars. The frontend may edit non-secret runtime configuration only.
- External repos inspire Cosmu, but Cosmu owns its runtime interfaces.

## First Useful Foundation

1. Store this plan and decisions in repo memory.
2. Add a cleaner Light / Research / Pro frontend shell.
3. Add `agent_steps` as the product-level observability trace.
4. Wire the existing Light pipeline into agent steps without changing trading behavior.
5. Add Research v1: natural-language experiment creation with observable planner, data scout, skeptic, and summary steps.

## End State

Cosmu should be able to autonomously:

- propose market hypotheses;
- find or configure data sources;
- run rigorous tests with leakage/overfit checks;
- reject noisy ideas;
- create paper bots;
- promote strong candidates for live approval;
- trade within limits when enabled;
- review outcomes and update scoped memory;
- let a human inspect, interrupt, approve, reject, or downgrade any part from the frontend.

