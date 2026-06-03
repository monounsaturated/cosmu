# intent: cost-transparency writers — record LLM calls into llm_calls and infra lines into costs;
# inputs: a Store reference, per-call metadata, or nothing (infra seed is fully deterministic);
# outputs: persisted rows readable by GET /costs; invariants: all writes are best-effort and
# offline-safe (no external billing API calls), never block the main path, degrade honestly.
