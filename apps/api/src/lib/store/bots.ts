// module: Bot CRUD, atomic run claiming (next_run_at), and scheduling queries.
import {
  assetClassSchema,
  type PrePromptConfig,
  type RuntimeConfig,
  type TraderConfig,
  traderConfigSchema
} from "@cosmu/shared";
import { sql } from "../../db.js";
import { netForVenue } from "../../adapters/binance.js";
import { buildRuntimeConfig, parseJson, parsePromptConfig, parseTraderConfig, type JsonValue } from "./helpers.js";

export type BotSetup = {
  id: string;
  botNumber: number;
  name: string;
  slug: string;
  promptVersionId: string;
  promptBody: string;
  promptVersionLabel: string;
  traderPromptVersionId: string | null;
  traderPromptBody: string | null;
  traderPromptVersionLabel: string | null;
  modelProfileId: string;
  modelProfileName: string;
  modelProvider: string;
  modelIdentifier: string;
  modelSettings: Record<string, JsonValue>;
  traderModelProfileId: string;
  traderModelProfileName: string;
  traderModelProvider: string;
  traderModelIdentifier: string;
  traderModelSettings: Record<string, JsonValue>;
  promptConfig: PrePromptConfig;
  traderConfig: TraderConfig;
  runtimeConfigId: string;
  runtimeConfig: RuntimeConfig;
};

export type BotExecutionLedgerEntry = {
  symbol: string;
  side: "buy" | "sell";
  executedQuantity: number | null;
  executedNotionalUsd: number | null;
  feeAmount: number | null;
  feeAsset: string | null;
};

const parseBotRow = (row: BotSetup): BotSetup => ({
  id: row.id,
  botNumber: row.botNumber,
  name: row.name,
  slug: row.slug,
  promptVersionId: row.promptVersionId,
  promptBody: row.promptBody,
  promptVersionLabel: row.promptVersionLabel,
  traderPromptVersionId: row.traderPromptVersionId ?? null,
  traderPromptBody: row.traderPromptBody ?? null,
  traderPromptVersionLabel: row.traderPromptVersionLabel ?? null,
  modelProfileId: row.modelProfileId,
  modelProfileName: row.modelProfileName,
  modelProvider: row.modelProvider,
  modelIdentifier: row.modelIdentifier,
  modelSettings: parseJson<Record<string, JsonValue>>(row.modelSettings),
  traderModelProfileId: row.traderModelProfileId ?? row.modelProfileId,
  traderModelProfileName: row.traderModelProfileName ?? row.modelProfileName,
  traderModelProvider: row.traderModelProvider ?? row.modelProvider,
  traderModelIdentifier: row.traderModelIdentifier ?? row.modelIdentifier,
  traderModelSettings: parseJson<Record<string, JsonValue>>(row.traderModelSettings ?? row.modelSettings),
  promptConfig: parsePromptConfig(row.promptConfig),
  traderConfig: parseTraderConfig(row.traderConfig),
  runtimeConfigId: row.runtimeConfigId,
  runtimeConfig: buildRuntimeConfig(row as never)
});

const BOT_SELECT_QUERY = `
  with prompt_order as (
    select id, row_number() over (order by created_at asc) as prompt_number
    from research_prompts
  ),
  trader_prompt_order as (
    select id, row_number() over (order by created_at asc) as prompt_number
    from trader_prompts
  )
  select
    b.id,
    b.bot_number as "botNumber",
    b.name,
    b.slug,
    pv.id as "promptVersionId",
    pv.body as "promptBody",
    concat('Research Prompt #', prompt_order.prompt_number) as "promptVersionLabel",
    tpv.id as "traderPromptVersionId",
    tpv.body as "traderPromptBody",
    case when tp.id is not null then concat('Trader Prompt #', trader_prompt_order.prompt_number) else null end as "traderPromptVersionLabel",
    mp.id as "modelProfileId",
    mp.name as "modelProfileName",
    mp.provider as "modelProvider",
    mp.model as "modelIdentifier",
    mp.settings as "modelSettings",
    coalesce(tmp.id, mp.id) as "traderModelProfileId",
    coalesce(tmp.name, mp.name) as "traderModelProfileName",
    coalesce(tmp.provider, mp.provider) as "traderModelProvider",
    coalesce(tmp.model, mp.model) as "traderModelIdentifier",
    coalesce(tmp.settings, mp.settings) as "traderModelSettings",
    b.prompt_config as "promptConfig",
    b.trader_config as "traderConfig",
    brc.id as "runtimeConfigId",
    brc.enabled,
    brc.venue,
    brc.frequency_minutes as "frequencyMinutes",
    brc.asset_class as "assetClass",
    brc.execution_config as "executionConfig",
    brc.context_symbols as "contextSymbols",
    brc.budget_usdt::float8 as "budgetUsdt"
  from bots b
  join research_prompt_versions pv on pv.id = b.active_prompt_version_id
  join research_prompts p on p.id = pv.prompt_id
  join prompt_order on prompt_order.id = p.id
  join model_profiles mp on mp.id = b.active_model_profile_id
  left join model_profiles tmp on tmp.id = b.active_trader_model_profile_id
  join bot_runtime_configs brc on brc.bot_id = b.id
  left join trader_prompt_versions tpv on tpv.id = b.active_trader_prompt_version_id
  left join trader_prompts tp on tp.id = tpv.prompt_id
  left join trader_prompt_order on trader_prompt_order.id = tp.id
`;

export const getDueBots = async (): Promise<BotSetup[]> => {
  const rows = await sql<BotSetup[]>`
    with prompt_order as (
      select id, row_number() over (order by created_at asc) as prompt_number
      from research_prompts
    ),
    trader_prompt_order as (
      select id, row_number() over (order by created_at asc) as prompt_number
      from trader_prompts
    )
    select
      b.id,
      b.bot_number as "botNumber",
      b.name,
      b.slug,
      pv.id as "promptVersionId",
      pv.body as "promptBody",
      concat('Research Prompt #', prompt_order.prompt_number) as "promptVersionLabel",
      tpv.id as "traderPromptVersionId",
      tpv.body as "traderPromptBody",
      case when tp.id is not null then concat('Trader Prompt #', trader_prompt_order.prompt_number) else null end as "traderPromptVersionLabel",
      mp.id as "modelProfileId",
      mp.name as "modelProfileName",
      mp.provider as "modelProvider",
      mp.model as "modelIdentifier",
      mp.settings as "modelSettings",
      coalesce(tmp.id, mp.id) as "traderModelProfileId",
      coalesce(tmp.name, mp.name) as "traderModelProfileName",
      coalesce(tmp.provider, mp.provider) as "traderModelProvider",
      coalesce(tmp.model, mp.model) as "traderModelIdentifier",
      coalesce(tmp.settings, mp.settings) as "traderModelSettings",
      b.prompt_config as "promptConfig",
      b.trader_config as "traderConfig",
      brc.id as "runtimeConfigId",
      brc.enabled,
      brc.venue,
      brc.frequency_minutes as "frequencyMinutes",
      brc.asset_class as "assetClass",
      brc.execution_config as "executionConfig",
      brc.context_symbols as "contextSymbols",
      brc.budget_usdt::float8 as "budgetUsdt"
    from bots b
    join research_prompt_versions pv on pv.id = b.active_prompt_version_id
    join research_prompts p on p.id = pv.prompt_id
    join prompt_order on prompt_order.id = p.id
    join model_profiles mp on mp.id = b.active_model_profile_id
    left join model_profiles tmp on tmp.id = b.active_trader_model_profile_id
    join bot_runtime_configs brc on brc.bot_id = b.id
    left join trader_prompt_versions tpv on tpv.id = b.active_trader_prompt_version_id
    left join trader_prompts tp on tp.id = tpv.prompt_id
    left join trader_prompt_order on trader_prompt_order.id = tp.id
    where brc.enabled = true
      and (
        brc.next_run_at is null
        or brc.next_run_at <= now()
      )
      and (
        brc.last_run_started_at is null
        or brc.last_run_finished_at >= brc.last_run_started_at
        or brc.last_run_started_at <= now() - interval '30 minutes'
      )
    order by b.created_at asc
  `;
  return rows.map(parseBotRow);
};

export const getAllEnabledBotSetups = async (): Promise<BotSetup[]> => {
  const rows = await sql<BotSetup[]>`
    with prompt_order as (
      select id, row_number() over (order by created_at asc) as prompt_number
      from research_prompts
    ),
    trader_prompt_order as (
      select id, row_number() over (order by created_at asc) as prompt_number
      from trader_prompts
    )
    select
      b.id,
      b.bot_number as "botNumber",
      b.name,
      b.slug,
      pv.id as "promptVersionId",
      pv.body as "promptBody",
      concat('Research Prompt #', prompt_order.prompt_number) as "promptVersionLabel",
      tpv.id as "traderPromptVersionId",
      tpv.body as "traderPromptBody",
      case when tp.id is not null then concat('Trader Prompt #', trader_prompt_order.prompt_number) else null end as "traderPromptVersionLabel",
      mp.id as "modelProfileId",
      mp.name as "modelProfileName",
      mp.provider as "modelProvider",
      mp.model as "modelIdentifier",
      mp.settings as "modelSettings",
      coalesce(tmp.id, mp.id) as "traderModelProfileId",
      coalesce(tmp.name, mp.name) as "traderModelProfileName",
      coalesce(tmp.provider, mp.provider) as "traderModelProvider",
      coalesce(tmp.model, mp.model) as "traderModelIdentifier",
      coalesce(tmp.settings, mp.settings) as "traderModelSettings",
      b.prompt_config as "promptConfig",
      b.trader_config as "traderConfig",
      brc.id as "runtimeConfigId",
      brc.enabled,
      brc.venue,
      brc.frequency_minutes as "frequencyMinutes",
      brc.asset_class as "assetClass",
      brc.execution_config as "executionConfig",
      brc.context_symbols as "contextSymbols",
      brc.budget_usdt::float8 as "budgetUsdt"
    from bots b
    join research_prompt_versions pv on pv.id = b.active_prompt_version_id
    join research_prompts p on p.id = pv.prompt_id
    join prompt_order on prompt_order.id = p.id
    join model_profiles mp on mp.id = b.active_model_profile_id
    left join model_profiles tmp on tmp.id = b.active_trader_model_profile_id
    join bot_runtime_configs brc on brc.bot_id = b.id
    left join trader_prompt_versions tpv on tpv.id = b.active_trader_prompt_version_id
    left join trader_prompts tp on tp.id = tpv.prompt_id
    left join trader_prompt_order on trader_prompt_order.id = tp.id
    where brc.enabled = true
    order by b.created_at asc
  `;
  return rows.map(parseBotRow);
};

export const getBotSetupById = async (botId: string): Promise<BotSetup | null> => {
  const rows = await sql<BotSetup[]>`
    with prompt_order as (
      select id, row_number() over (order by created_at asc) as prompt_number
      from research_prompts
    ),
    trader_prompt_order as (
      select id, row_number() over (order by created_at asc) as prompt_number
      from trader_prompts
    )
    select
      b.id,
      b.bot_number as "botNumber",
      b.name,
      b.slug,
      pv.id as "promptVersionId",
      pv.body as "promptBody",
      concat('Research Prompt #', prompt_order.prompt_number) as "promptVersionLabel",
      tpv.id as "traderPromptVersionId",
      tpv.body as "traderPromptBody",
      case when tp.id is not null then concat('Trader Prompt #', trader_prompt_order.prompt_number) else null end as "traderPromptVersionLabel",
      mp.id as "modelProfileId",
      mp.name as "modelProfileName",
      mp.provider as "modelProvider",
      mp.model as "modelIdentifier",
      mp.settings as "modelSettings",
      coalesce(tmp.id, mp.id) as "traderModelProfileId",
      coalesce(tmp.name, mp.name) as "traderModelProfileName",
      coalesce(tmp.provider, mp.provider) as "traderModelProvider",
      coalesce(tmp.model, mp.model) as "traderModelIdentifier",
      coalesce(tmp.settings, mp.settings) as "traderModelSettings",
      b.prompt_config as "promptConfig",
      b.trader_config as "traderConfig",
      brc.id as "runtimeConfigId",
      brc.enabled,
      brc.venue,
      brc.frequency_minutes as "frequencyMinutes",
      brc.asset_class as "assetClass",
      brc.execution_config as "executionConfig",
      brc.context_symbols as "contextSymbols",
      brc.budget_usdt::float8 as "budgetUsdt"
    from bots b
    join research_prompt_versions pv on pv.id = b.active_prompt_version_id
    join research_prompts p on p.id = pv.prompt_id
    join prompt_order on prompt_order.id = p.id
    join model_profiles mp on mp.id = b.active_model_profile_id
    left join model_profiles tmp on tmp.id = b.active_trader_model_profile_id
    join bot_runtime_configs brc on brc.bot_id = b.id
    left join trader_prompt_versions tpv on tpv.id = b.active_trader_prompt_version_id
    left join trader_prompts tp on tp.id = tpv.prompt_id
    left join trader_prompt_order on trader_prompt_order.id = tp.id
    where b.id = ${botId}
    limit 1
  `;
  const row = rows[0];
  if (!row) return null;
  return parseBotRow(row);
};

export const ensureBotSchedulerSchema = async () => {
  const [column] = await sql<{ exists: boolean }[]>`
    select exists (
      select 1
      from information_schema.columns
      where table_schema = 'public'
        and table_name = 'bot_runtime_configs'
        and column_name = 'next_run_at'
    ) as "exists"
  `;

  if (!column?.exists) {
    await sql`
      alter table bot_runtime_configs
        add column next_run_at timestamptz
    `;
  }

  await sql`
    update bot_runtime_configs
    set next_run_at = case
      when last_run_finished_at is not null then greatest(now(), last_run_finished_at + make_interval(secs => frequency_minutes * 60))
      when last_run_started_at is not null then greatest(now(), last_run_started_at + make_interval(secs => frequency_minutes * 60))
      else created_at
    end
    where enabled = true
      and next_run_at is null
  `;

  const [index] = await sql<{ exists: boolean }[]>`
    select exists (
      select 1
      from pg_indexes
      where schemaname = 'public'
        and tablename = 'bot_runtime_configs'
        and indexname = 'bot_runtime_configs_due_idx'
    ) as "exists"
  `;

  if (!index?.exists) {
    await sql`
      create index bot_runtime_configs_due_idx
        on bot_runtime_configs (enabled, next_run_at)
        where enabled = true
    `;
  }
};

/**
 * Atomically claim the current scheduled run for this bot.
 *
 * Returns true if the run should proceed, false if another source already
 * claimed this cycle or a scheduled run is not due yet. A claim clears
 * `next_run_at` while the run is active; `finishRun` schedules the next cadence
 * from the finish timestamp. If the process dies mid-run, the stale-start guard
 * below lets a later tick recover it after 30 minutes.
 */
export const claimRun = async (
  runtimeConfigId: string,
  options: { force?: boolean } = {}
): Promise<boolean> => {
  const force = options.force ?? false;
  const rows = await sql<{ id: string }[]>`
    update bot_runtime_configs
    set last_run_started_at = now(),
        next_run_at = null,
        updated_at = now()
    where id = ${runtimeConfigId}
      and enabled = true
      and (
        ${force}
        or
        next_run_at is null
        or next_run_at <= now()
      )
      and (
        last_run_started_at is null
        or last_run_finished_at >= last_run_started_at
        or last_run_started_at <= now() - interval '30 minutes'
      )
    returning id
  `;
  return rows.length > 0;
};

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

export const killBot = async (botId: string) => {
  await sql`
    update bot_runtime_configs
    set enabled = false,
        killed_at = now(),
        next_run_at = null,
        updated_at = now()
    where bot_id = ${botId}
  `;
};

export const createBot = async (input: {
  name: string;
  slug: string;
  promptVersionId: string;
  modelProfileId: string;
  traderModelProfileId?: string | null;
  promptConfig: PrePromptConfig;
  traderConfig?: TraderConfig;
  traderPromptVersionId?: string | null;
  parentBotId?: string | null;
  enabled?: boolean;
  runtimeConfig: Omit<RuntimeConfig, "enabled">;
}) => {
  const effectiveName = input.name.trim();
  const scheduledEnabled = input.enabled ?? true;
  const [bot] = await sql<{ id: string }[]>`
    insert into bots (
      name, slug, active_prompt_version_id, active_model_profile_id,
      active_trader_model_profile_id,
      active_trader_prompt_version_id, parent_bot_id, prompt_config, trader_config
    ) values (
      ${effectiveName}, ${input.slug}, ${input.promptVersionId}, ${input.modelProfileId},
      ${input.traderModelProfileId ?? input.modelProfileId},
      ${input.traderPromptVersionId ?? null}, ${input.parentBotId ?? null},
      ${sql.json(input.promptConfig)},
      ${sql.json(input.traderConfig ?? traderConfigSchema.parse({}))}
    )
    returning id
  `;

  await sql`
    insert into bot_runtime_configs (
      bot_id, enabled, venue, frequency_minutes, mode, asset_class,
      budget_usdt, execution_config, context_symbols, next_run_at
    ) values (
      ${bot.id}, ${scheduledEnabled}, ${input.runtimeConfig.venue}, ${input.runtimeConfig.frequencyMinutes},
      ${netForVenue(input.runtimeConfig.venue)}, ${input.runtimeConfig.assetClass},
      ${input.runtimeConfig.budgetUsdt ?? 1000},
      ${sql.json(input.runtimeConfig.execution)},
      ${sql.json(input.runtimeConfig.contextSymbols)},
      ${scheduledEnabled ? sql`now()` : null}
    )
  `;

  return bot.id;
};

export const updateBotConfig = async (
  botId: string,
  input: {
    name?: string;
    enabled?: boolean;
    promptVersionId?: string;
    traderPromptVersionId?: string | null;
    modelProfileId?: string;
    traderModelProfileId?: string | null;
    promptConfig?: PrePromptConfig;
    traderConfig?: TraderConfig;
    runtimeConfig?: RuntimeConfig;
  }
) => {
  const botUpdates: Record<string, unknown> = {};
  if (input.name !== undefined) botUpdates.name = input.name.trim();
  if (input.promptVersionId !== undefined) botUpdates.active_prompt_version_id = input.promptVersionId;
  if (input.traderPromptVersionId !== undefined) botUpdates.active_trader_prompt_version_id = input.traderPromptVersionId;
  if (input.modelProfileId !== undefined) botUpdates.active_model_profile_id = input.modelProfileId;
  if (input.traderModelProfileId !== undefined) botUpdates.active_trader_model_profile_id = input.traderModelProfileId;
  if (input.promptConfig !== undefined) botUpdates.prompt_config = sql.json(input.promptConfig);
  if (input.traderConfig !== undefined) botUpdates.trader_config = sql.json(input.traderConfig);

  if (Object.keys(botUpdates).length > 0) {
    await sql`
      update bots
      set ${sql(botUpdates)}
      where id = ${botId}
    `;
  }

  const runtimeUpdates: Record<string, unknown> = {};
  if (input.enabled !== undefined) runtimeUpdates.enabled = input.enabled;
  if (input.runtimeConfig !== undefined) {
    runtimeUpdates.venue = input.runtimeConfig.venue;
    runtimeUpdates.frequency_minutes = input.runtimeConfig.frequencyMinutes;
    runtimeUpdates.mode = netForVenue(input.runtimeConfig.venue);
    runtimeUpdates.asset_class = input.runtimeConfig.assetClass;
    runtimeUpdates.budget_usdt = input.runtimeConfig.budgetUsdt;
    runtimeUpdates.execution_config = sql.json(input.runtimeConfig.execution);
    runtimeUpdates.context_symbols = sql.json(input.runtimeConfig.contextSymbols);
  }

  if (Object.keys(runtimeUpdates).length > 0) {
    await sql`
      update bot_runtime_configs
      set ${sql(runtimeUpdates)}, updated_at = now()
      where bot_id = ${botId}
    `;
  }

  if (input.runtimeConfig !== undefined) {
    await sql`
      update bot_runtime_configs
      set next_run_at = now(),
          updated_at = now()
      where bot_id = ${botId}
        and enabled = true
    `;
  }
};

export const listBotExecutionLedger = async (botId: string): Promise<BotExecutionLedgerEntry[]> => {
  const rows = await sql<BotExecutionLedgerEntry[]>`
    select
      e.symbol,
      e.side,
      e.executed_quantity::float8 as "executedQuantity",
      e.executed_notional_usd::float8 as "executedNotionalUsd",
      e.fee_amount::float8 as "feeAmount",
      e.fee_asset as "feeAsset"
    from executions e
    join runs r on r.id = e.run_id
    where r.bot_id = ${botId}
      and r.status in ('success', 'uncertain')
      and e.status = 'success'
    order by e.created_at asc
  `;
  return rows.map((row) => ({
    ...row,
    executedQuantity: row.executedQuantity === null ? null : Number(row.executedQuantity),
    executedNotionalUsd: row.executedNotionalUsd === null ? null : Number(row.executedNotionalUsd),
    feeAmount: row.feeAmount === null ? null : Number(row.feeAmount)
  }));
};

export const assetClass = assetClassSchema.parse("spot");
