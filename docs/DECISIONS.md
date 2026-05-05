# Architecture Decisions

## 2026-05-05: Three Modes, One Platform

Cosmu will use Light / Research / Pro modes in one app rather than separate products. This keeps operation simple and lets observability, memory, data sources, and approvals be shared.

## 2026-05-05: Workspaces Are Segregated, Not Layered

Each workspace lists its own bots. A bot's `workspace_mode` (`light` | `research` | `pro`) is the source of truth — Light bots are not visible in Research or Pro, research bots are not visible in Light, and Pro only shows bots that came through promotion. Research → Pro is the only promotion path, and it always passes through the approval inbox.

## 2026-05-05: Promotion Creates a Disabled Pro Bot

Approving a `live_promotion` request creates a Pro bot with `execution.enabled = false`. A human still has to flip on order placement on the bot detail page. This keeps approval and execution as two separate gates so an autonomous future scheduler still has a clean place to insert capped auto-live policies later.

## 2026-05-05: End State Is Full Autonomy, Not Magic

Cosmu Pro will eventually run the full loop autonomously. The path is incremental: Research stays paper-only until backtest, skeptic, and cost-realism evidence is mature; Pro stays human-approved until promotion thresholds and capped auto-live are configured from the frontend. Agents working on Cosmu must help us get there without bypassing the validator, kill switch, or approval gate.

## 2026-05-05: Preserve Light

The existing Light loop stays the production baseline. Research and Pro may evolve quickly, but Light must remain simple and live-capable.

## 2026-05-05: Product-Level Agent Observability

`run_llm_calls` remains low-level telemetry. `agent_steps` becomes the user-facing trace for agent phases, tool calls, errors, and outputs across Light, Research, paper bots, and Pro.

## 2026-05-05: Research Autonomy Before Live Autonomy

Research may create paper bots automatically. Live trading requires human approval by default until paper evidence, validators, kill paths, and promotion thresholds are mature.

## 2026-05-05: External Repos Are References

TradingAgents, autoresearch, MemPalace, and Hermes Agent are pinned references. Cosmu does not import their internals into live runtime unless wrapped behind a stable adapter.

## 2026-05-05: Secrets Stay in Infrastructure

Frontend-editable settings are non-secret runtime configuration only. API keys, private keys, webhooks, database URLs, and provider secrets remain in Railway/Vercel/Supabase-managed env vars.

## 2026-05-05: Railway/Vercel Stay Core Infra

Keep Railway for API/scheduler/guardian, Vercel for frontend, and Supabase/Postgres for state. Add RunPod or VPS workers only for Research compute; do not move the whole app to GPU infra.

