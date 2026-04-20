import { sql } from "../../db.js";

export type LLMCallRecord = {
  runId: string;
  phase: "research" | "trader";
  provider: string;
  model: string;
  inputMessages: unknown;
  outputText: string | null;
  inputTokens: number | null;
  outputTokens: number | null;
  latencyMs: number | null;
  attempt: number;
  strategy: string | null;
  error: string | null;
};

export const storeLLMCall = async (record: LLMCallRecord) => {
  try {
    await sql`
      insert into run_llm_calls (
        run_id, phase, provider, model, input_messages,
        output_text, input_tokens, output_tokens, latency_ms,
        attempt, strategy, error
      ) values (
        ${record.runId}, ${record.phase}, ${record.provider}, ${record.model},
        ${sql.json(record.inputMessages as any)},
        ${record.outputText}, ${record.inputTokens}, ${record.outputTokens},
        ${record.latencyMs}, ${record.attempt}, ${record.strategy}, ${record.error}
      )
    `;
  } catch (error) {
    // LLM call logging is best-effort — never block the pipeline
    console.warn("Failed to store LLM call record:", String(error));
  }
};

export const getLLMCallsForRun = async (runId: string) =>
  sql`
    select
      id, phase, provider, model,
      input_tokens as "inputTokens",
      output_tokens as "outputTokens",
      latency_ms as "latencyMs",
      attempt, strategy, error,
      created_at as "createdAt",
      input_messages -> 'toolCalls' as "toolCalls",
      input_messages -> 'iterations' as "iterations"
    from run_llm_calls
    where run_id = ${runId}
    order by created_at asc
  `;
