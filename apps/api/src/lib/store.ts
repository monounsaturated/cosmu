import {
  assetClassSchema,
  botSummarySchema,
  dashboardSchema,
  executionRecordSchema,
  portfolioSnapshotSchema,
  runtimeConfigSchema,
  type DashboardPayload,
  type ExecutionRecord,
  type PortfolioSnapshot,
  type RuntimeConfig,
  type TradingDecision,
  type ValidationResult
} from "@cosmu/shared";
import { sql } from "../db.js";

type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

export type BotSetup = {
  id: string;
  name: string;
  slug: string;
  promptVersionId: string;
  promptBody: string;
  promptVersionLabel: string;
  modelProfileId: string;
  modelProfileName: string;
  modelProvider: string;
  modelIdentifier: string;
  modelSettings: Record<string, JsonValue>;
  runtimeConfigId: string;
  runtimeConfig: RuntimeConfig;
};

const parseJson = <T>(value: unknown): T => {
  if (typeof value === "string") {
    return JSON.parse(value) as T;
  }

  return value as T;
};

const buildRuntimeConfig = (row: {
  enabled: boolean;
  venue: "binance";
  frequency_minutes: number;
  mode: "testnet" | "live";
  asset_class: "spot";
  execution_config: unknown;
  context_symbols: unknown;
}): RuntimeConfig =>
  runtimeConfigSchema.parse({
    enabled: row.enabled,
    venue: row.venue,
    frequencyMinutes: row.frequency_minutes,
    mode: row.mode,
    assetClass: row.asset_class,
    execution: parseJson<Record<string, JsonValue>>(row.execution_config),
    contextSymbols: parseJson<string[]>(row.context_symbols)
  });

export const getDueBots = async (): Promise<BotSetup[]> => {
  const rows = await sql<BotSetup[]>`
    select
      b.id,
      b.name,
      b.slug,
      pv.id as "promptVersionId",
      pv.body as "promptBody",
      concat(p.name, ' v', pv.version) as "promptVersionLabel",
      mp.id as "modelProfileId",
      mp.name as "modelProfileName",
      mp.provider as "modelProvider",
      mp.model as "modelIdentifier",
      mp.settings as "modelSettings",
      brc.id as "runtimeConfigId",
      brc.enabled,
      brc.venue,
      brc.frequency_minutes,
      brc.mode,
      brc.asset_class,
      brc.execution_config,
      brc.context_symbols
    from bots b
    join prompt_versions pv on pv.id = b.active_prompt_version_id
    join prompts p on p.id = pv.prompt_id
    join model_profiles mp on mp.id = b.active_model_profile_id
    join bot_runtime_configs brc on brc.bot_id = b.id
    where brc.enabled = true
      and (
        brc.last_run_started_at is null
        or brc.last_run_started_at <= now() - make_interval(mins => brc.frequency_minutes)
      )
    order by b.created_at asc
  `;

  return rows.map((row) => ({
    id: row.id,
    name: row.name,
    slug: row.slug,
    promptVersionId: row.promptVersionId,
    promptBody: row.promptBody,
    promptVersionLabel: row.promptVersionLabel,
    modelProfileId: row.modelProfileId,
    modelProfileName: row.modelProfileName,
    modelProvider: row.modelProvider,
    modelIdentifier: row.modelIdentifier,
    modelSettings: parseJson<Record<string, JsonValue>>(row.modelSettings),
    runtimeConfigId: row.runtimeConfigId,
    runtimeConfig: buildRuntimeConfig(row as never)
  }));
};

export const getBotSetupById = async (botId: string): Promise<BotSetup | null> => {
  const rows = await sql<BotSetup[]>`
    select
      b.id,
      b.name,
      b.slug,
      pv.id as "promptVersionId",
      pv.body as "promptBody",
      concat(p.name, ' v', pv.version) as "promptVersionLabel",
      mp.id as "modelProfileId",
      mp.name as "modelProfileName",
      mp.provider as "modelProvider",
      mp.model as "modelIdentifier",
      mp.settings as "modelSettings",
      brc.id as "runtimeConfigId",
      brc.enabled,
      brc.venue,
      brc.frequency_minutes,
      brc.mode,
      brc.asset_class,
      brc.execution_config,
      brc.context_symbols
    from bots b
    join prompt_versions pv on pv.id = b.active_prompt_version_id
    join prompts p on p.id = pv.prompt_id
    join model_profiles mp on mp.id = b.active_model_profile_id
    join bot_runtime_configs brc on brc.bot_id = b.id
    where b.id = ${botId}
    limit 1
  `;

  const row = rows[0];
  if (!row) {
    return null;
  }

  return {
    id: row.id,
    name: row.name,
    slug: row.slug,
    promptVersionId: row.promptVersionId,
    promptBody: row.promptBody,
    promptVersionLabel: row.promptVersionLabel,
    modelProfileId: row.modelProfileId,
    modelProfileName: row.modelProfileName,
    modelProvider: row.modelProvider,
    modelIdentifier: row.modelIdentifier,
    modelSettings: parseJson<Record<string, JsonValue>>(row.modelSettings),
    runtimeConfigId: row.runtimeConfigId,
    runtimeConfig: buildRuntimeConfig(row as never)
  };
};

export const markRunStarted = async (runtimeConfigId: string) => {
  await sql`
    update bot_runtime_configs
    set last_run_started_at = now(),
        updated_at = now()
    where id = ${runtimeConfigId}
  `;
};

export const createRun = async (input: {
  botId: string;
  promptVersionId: string;
  modelProfileId: string;
  runtimeConfig: RuntimeConfig;
  compactContext: Record<string, JsonValue>;
}) => {
  const [row] = await sql<{ id: string }[]>`
    insert into runs (
      bot_id,
      prompt_version_id,
      model_profile_id,
      runtime_config,
      compact_context,
      status
    ) values (
      ${input.botId},
      ${input.promptVersionId},
      ${input.modelProfileId},
      ${sql.json(input.runtimeConfig)},
      ${sql.json(input.compactContext)},
      'running'
    )
    returning id
  `;

  return row.id;
};

export const storeDecision = async (input: {
  runId: string;
  rawModelOutput: string;
  decision: TradingDecision;
  validationResult: ValidationResult;
}) => {
  await sql`
    update runs
    set raw_model_output = ${input.rawModelOutput},
        parsed_decision = ${sql.json(input.decision)},
        validation_result = ${sql.json(input.validationResult)}
    where id = ${input.runId}
  `;

  await sql`
    insert into decisions (
      run_id,
      decision_mode,
      rationale_summary,
      global_rationale,
      confidence,
      payload
    ) values (
      ${input.runId},
      ${input.decision.mode},
      ${input.decision.rationaleSummary},
      ${input.decision.globalRationale},
      ${input.decision.confidence},
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

export const storeExecutionRecords = async (runId: string, executionRecords: ExecutionRecord[]) => {
  for (const execution of executionRecords) {
    const parsed = executionRecordSchema.parse(execution);
    await sql`
      insert into executions (
        run_id,
        asset_class,
        venue,
        status,
        symbol,
        side,
        order_type,
        requested_quantity,
        executed_quantity,
        requested_limit_price,
        average_fill_price,
        fee_amount,
        fee_asset,
        fee_usd,
        slippage_pct,
        order_intent,
        raw_venue_response
      ) values (
        ${runId},
        ${parsed.assetClass},
        ${parsed.venue},
        ${parsed.status},
        ${parsed.symbol},
        ${parsed.side},
        ${parsed.orderType},
        ${parsed.requestedQuantity},
        ${parsed.executedQuantity},
        ${parsed.requestedLimitPrice},
        ${parsed.averageFillPrice},
        ${parsed.feeAmount},
        ${parsed.feeAsset},
        ${parsed.feeUsd},
        ${parsed.slippagePct},
        ${sql.json(parsed.orderIntent)},
        ${sql.json(parsed.rawVenueResponse as JsonValue)}
      )
    `;
  }
};

export const storePortfolioSnapshot = async (runId: string, stage: "before" | "after", snapshot: PortfolioSnapshot) => {
  const parsed = portfolioSnapshotSchema.parse(snapshot);

  await sql`
    insert into portfolio_snapshots (
      run_id,
      asset_class,
      stage,
      total_usd_value,
      gross_pnl_usd,
      net_pnl_usd,
      fee_usd,
      balances,
      prices,
      raw_snapshot
    ) values (
      ${runId},
      ${parsed.assetClass},
      ${stage},
      ${parsed.totalUsdValue},
      ${parsed.grossPnlUsd},
      ${parsed.netPnlUsd},
      ${parsed.feeUsd},
      ${sql.json(parsed.balances)},
      ${sql.json(parsed.prices)},
      ${sql.json(parsed)}
    )
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
    set last_run_finished_at = now(),
        updated_at = now()
    where id = ${input.runtimeConfigId}
  `;
};

export const getDashboard = async (): Promise<DashboardPayload> => {
  const botRows = await sql`
    select
      b.id,
      b.name,
      b.slug,
      brc.enabled,
      brc.frequency_minutes as "frequencyMinutes",
      brc.mode,
      brc.asset_class as "assetClass",
      concat(p.name, ' v', pv.version) as "promptVersionLabel",
      mp.name as "modelProfileName",
      r.status as "lastRunStatus",
      d.rationale_summary as "latestDecisionSummary",
      cast(r.error_state ->> 'message' as text) as "latestError",
      brc.updated_at as "updatedAt"
    from bots b
    join bot_runtime_configs brc on brc.bot_id = b.id
    join prompt_versions pv on pv.id = b.active_prompt_version_id
    join prompts p on p.id = pv.prompt_id
    join model_profiles mp on mp.id = b.active_model_profile_id
    left join lateral (
      select *
      from runs
      where bot_id = b.id
      order by created_at desc
      limit 1
    ) r on true
    left join decisions d on d.run_id = r.id
    order by b.created_at asc
  `;

  const recentRuns = await sql`
    select
      r.id,
      b.name as "botName",
      r.status,
      r.started_at as "startedAt",
      r.finished_at as "finishedAt",
      d.decision_mode as "decisionMode",
      d.rationale_summary as "rationaleSummary"
    from runs r
    join bots b on b.id = r.bot_id
    left join decisions d on d.run_id = r.id
    order by r.created_at desc
    limit 20
  `;

  const recentExecutions = await sql`
    select
      e.run_id as "runId",
      e.asset_class as "assetClass",
      e.venue,
      e.status,
      e.symbol,
      e.side,
      e.order_type as "orderType",
      e.requested_quantity as "requestedQuantity",
      e.executed_quantity as "executedQuantity",
      e.requested_limit_price as "requestedLimitPrice",
      e.average_fill_price as "averageFillPrice",
      e.fee_amount as "feeAmount",
      e.fee_asset as "feeAsset",
      e.fee_usd as "feeUsd",
      e.slippage_pct as "slippagePct",
      e.order_intent as "orderIntent",
      e.raw_venue_response as "rawVenueResponse"
    from executions e
    order by e.created_at desc
    limit 20
  `;

  const latestSnapshots = await sql`
    select distinct on (b.id)
      b.name as "botName",
      ps.raw_snapshot as "snapshot"
    from portfolio_snapshots ps
    join runs r on r.id = ps.run_id
    join bots b on b.id = r.bot_id
    where ps.stage = 'after'
    order by b.id, ps.created_at desc
  `;

  const promptVersions = await sql`
    select
      p.name as "promptName",
      pv.version,
      concat(p.name, ' v', pv.version) as label,
      pv.created_at as "createdAt"
    from prompt_versions pv
    join prompts p on p.id = pv.prompt_id
    order by pv.created_at desc
    limit 20
  `;

  return dashboardSchema.parse({
    generatedAt: new Date().toISOString(),
    bots: botRows.map((row) =>
      botSummarySchema.parse({
        ...row,
        updatedAt: row.updatedAt.toISOString()
      })
    ),
    recentRuns: recentRuns.map((row) => ({
      ...row,
      startedAt: row.startedAt.toISOString(),
      finishedAt: row.finishedAt ? row.finishedAt.toISOString() : null
    })),
    recentExecutions: recentExecutions.map((row) => ({
      ...row,
      orderIntent: parseJson(row.orderIntent),
      rawVenueResponse: parseJson(row.rawVenueResponse)
    })),
    latestSnapshots: latestSnapshots.map((row) => ({
      botName: row.botName,
      snapshot: portfolioSnapshotSchema.parse(parseJson(row.snapshot))
    })),
    promptVersions: promptVersions.map((row) => ({
      ...row,
      createdAt: row.createdAt.toISOString()
    }))
  });
};

export const recentTradeAlerts = async (runId: string) =>
  sql`
    select
      symbol,
      side,
      status
    from executions
    where run_id = ${runId}
    order by created_at asc
  `;

export const getBotEnabledState = async (botId: string) => {
  const [row] = await sql<{ enabled: boolean; name: string }[]>`
    select b.name, brc.enabled
    from bots b
    join bot_runtime_configs brc on brc.bot_id = b.id
    where b.id = ${botId}
    limit 1
  `;

  return row ?? null;
};

export const toggleBotEnabled = async (botId: string) => {
  const [row] = await sql<{ enabled: boolean; name: string }[]>`
    update bot_runtime_configs
    set enabled = not enabled,
        updated_at = now()
    where bot_id = ${botId}
    returning enabled, (select name from bots where id = ${botId}) as name
  `;

  return row ?? null;
};

export const assetClass = assetClassSchema.parse("spot");
