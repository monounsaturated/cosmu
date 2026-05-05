# Architecture Decisions

## 2026-05-05: Three Modes, One Platform

Cosmu will use Light / Research / Pro modes in one app rather than separate products. This keeps operation simple and lets observability, memory, data sources, and approvals be shared.

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

