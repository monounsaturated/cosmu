# External Repo Notes

Cosmu borrows patterns from these repos without coupling the live runtime to their internal code.

Current implementation status: these repos are pinned references in `external-repos.lock.json`. They are not cloned into the repo, imported by the API, or allowed to own live trading behavior.

## TradingAgents

- Repo: https://github.com/TauricResearch/TradingAgents
- Use: analyst roles, bull/bear debate, risk committee, structured decision logs.
- Avoid: replacing Cosmu's operational TypeScript/Binance path with Python/LangGraph.

## autoresearch

- Repo: https://github.com/karpathy/autoresearch
- Use: bounded autonomous experiment loops, fixed metric, keep/discard discipline, compute-worker mindset.
- Avoid: letting agents mutate production code or promote noisy ideas without evidence.

## MemPalace

- Repo: https://github.com/MemPalace/mempalace
- Use: scoped memory, agent diaries, retrieval discipline.
- Avoid: opaque memory that silently changes live behavior.

## Hermes Agent

- Repo: https://github.com/NousResearch/hermes-agent
- Use: skills, toolsets, scheduled automations, self-improving agent patterns.
- Avoid: replacing Cosmu's product-specific workflows with a general agent framework.

## Nous Portal

- Models page: https://portal.nousresearch.com/models
- Use: optional OpenAI-compatible LLM provider via `provider = 'nous'` model profiles.
- Avoid: making Nous/Hermes a required runtime dependency for Light. Start in Research, then promote only after local QA.

## Reference Workflow

- Pin references in `external-repos.lock.json`.
- Clone/fetch into `.external/`, which is ignored by git.
- Review upstream changes before adopting patterns.
- Reimplement useful patterns behind stable Cosmu interfaces.

