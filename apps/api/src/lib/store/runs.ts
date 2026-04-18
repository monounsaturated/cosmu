import {
  type RuntimeConfig,
  type TradingDecision,
  type ValidationResult
} from "@cosmu/shared";
import { sql } from "../../db.js";
import { parseJson, type JsonValue } from "./helpers.js";

export const createRun = async (input: {
  botId: string;
  promptVersionId: string;
  modelProfileId: string;
  runtimeConfig: RuntimeConfig;
  compactContext: Record<string, unknown>;
  promptSystem?: string;
  promptUser?: string;
  formatterPromptVersionId?: string | null;
}) => {
  const [row] = await sql<{ id: string }[]>`
    insert into runs (
      bot_id, prompt_version_id, model_profile_id, runtime_config,
      compact_context, prompt_system, prompt_user, formatter_prompt_version_id, status
    ) values (
      ${input.botId}, ${input.promptVersionId}, ${input.modelProfileId},
      ${sql.json(input.runtimeConfig)},
      ${sql.json(input.compactContext as JsonValue)},
      ${input.promptSystem ?? null}, ${input.promptUser ?? null},
      ${input.formatterPromptVersionId ?? null}, 'running'
    )
    returning id
  `;
  return row.id;
};

export const storeDecision = async (input: {
  runId: string;
  decision: TradingDecision;
  validationResult: ValidationResult;
}) => {
  await sql`
    update runs
    set parsed_decision = ${sql.json(input.decision)},
        validation_result = ${sql.json(input.validationResult)}
    where id = ${input.runId}
  `;
  await sql`
    insert into decisions (
      run_id, decision_mode, rationale_summary, global_rationale, confidence, payload
    ) values (
      ${input.runId}, ${input.decision.mode}, ${input.decision.rationaleSummary},
      ${input.decision.globalRationale}, ${input.decision.confidence},
      ${sql.json(input.decision)}
    )
    on conflict (run_id) do update set
      decision_mode = excluded.decision_mode,
      rationale_summary = excluded.rationale_summary,
      global_rationale = excluded.global_rationale,
      confidence = excluded.confidence,
      payload = excluded.payload
  `;
};

export const storeResearchOutput = async (runId: string, researchOutput: string) => {
  await sql`
    update runs
    set research_output = ${researchOutput}
    where id = ${runId}
  `;
};

export const storeTraderOutput = async (runId: string, traderOutput: string) => {
  await sql`
    update runs
    set trader_output = ${traderOutput}
    where id = ${runId}
  `;
};

export const updateRunPrompts = async (runId: string, promptSystem: string, promptUser: string) => {
  await sql`
    update runs
    set prompt_system = ${promptSystem},
        prompt_user = ${promptUser}
    where id = ${runId}
  `;
};

export const finishRun = async (input: {
  runId: string;
  runtimeConfigId: string;
  status: "success" | "failure" | "uncertain";
  errorState?: Record<string, JsonValue> | null;
}) => {
  await sql`
    update runs
    set status = ${input.status},
        error_state = ${sql.json(input.errorState ?? null)},
        finished_at = now()
    where id = ${input.runId}
  `;
  await sql`
    update bot_runtime_configs
    set last_run_finished_at = now(), updated_at = now()
    where id = ${input.runtimeConfigId}
  `;
};

export const recentTradeAlerts = async (runId: string) =>
  sql`
    select symbol, side, status
    from executions
    where run_id = ${runId}
    order by created_at asc
  `;

export const getRunDetail = async (runId: string) => {
  const [row] = await sql<
    {
      id: string;
      botName: string;
      status: string;
      promptSystem: string | null;
      promptUser: string | null;
      researchOutput: string | null;
      traderOutput: string | null;
      parsedDecision: unknown;
      validationResult: unknown;
      compactContext: unknown;
      startedAt: Date;
      finishedAt: Date | null;
    }[]
  >`
    select
      r.id, b.name as "botName", r.status,
      r.prompt_system as "promptSystem", r.prompt_user as "promptUser",
      r.research_output as "researchOutput",
      r.trader_output as "traderOutput",
      r.parsed_decision as "parsedDecision",
      r.validation_result as "validationResult",
      r.compact_context as "compactContext",
      r.started_at as "startedAt", r.finished_at as "finishedAt"
    from runs r
    join bots b on b.id = r.bot_id
    where r.id = ${runId}
  `;
  if (!row) return null;
  return {
    ...row,
    startedAt: row.startedAt.toISOString(),
    finishedAt: row.finishedAt?.toISOString() ?? null,
    parsedDecision: typeof row.parsedDecision === "string" ? JSON.parse(row.parsedDecision) : row.parsedDecision,
    validationResult: typeof row.validationResult === "string" ? JSON.parse(row.validationResult) : row.validationResult,
    compactContext: typeof row.compactContext === "string" ? JSON.parse(row.compactContext) : row.compactContext
  };
};

export const getBotRuns = async (botId: string) => {
  const rows = await sql<
    {
      id: string;
      botName: string;
      status: string;
      promptSystem: string | null;
      promptUser: string | null;
      researchOutput: string | null;
      traderOutput: string | null;
      parsedDecision: unknown;
      validationResult: unknown;
      compactContext: unknown;
      formatterVersion: number | null;
      startedAt: Date;
      finishedAt: Date | null;
    }[]
  >`
    select
      r.id, b.name as "botName", r.status,
      r.prompt_system as "promptSystem", r.prompt_user as "promptUser",
      r.research_output as "researchOutput",
      r.trader_output as "traderOutput",
      r.parsed_decision as "parsedDecision",
      r.validation_result as "validationResult",
      r.compact_context as "compactContext",
      vpv.version as "formatterVersion",
      r.started_at as "startedAt", r.finished_at as "finishedAt"
    from runs r
    join bots b on b.id = r.bot_id
    left join venue_prompt_versions vpv on vpv.id = r.formatter_prompt_version_id
    where r.bot_id = ${botId}
    order by r.created_at desc
    limit 20
  `;
  return rows.map((row) => ({
    ...row,
    startedAt: row.startedAt.toISOString(),
    finishedAt: row.finishedAt?.toISOString() ?? null,
    parsedDecision: typeof row.parsedDecision === "string" ? JSON.parse(row.parsedDecision) : row.parsedDecision,
    validationResult: typeof row.validationResult === "string" ? JSON.parse(row.validationResult) : row.validationResult,
    compactContext: typeof row.compactContext === "string" ? JSON.parse(row.compactContext) : row.compactContext
  }));
};
