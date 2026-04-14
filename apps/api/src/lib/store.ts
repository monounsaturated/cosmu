import {
  ALL_SYMBOLS_TOKEN,
  assetClassSchema,
  botSummarySchema,
  botPerformanceSeriesSchema,
  dashboardSchema,
  executionRecordSchema,
  portfolioSnapshotSchema,
  prePromptConfigSchema,
  runtimeConfigSchema,
  traderConfigSchema,
  type DashboardPayload,
  type ExecutionRecord,
  type PortfolioSnapshot,
  type PrePromptConfig,
  type RuntimeConfig,
  type TraderConfig,
  type TradingDecision,
  type ValidationResult
} from "@cosmu/shared";
import { sql } from "../db.js";

type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

export type BotSetup = {
  id: string;
  botNumber: number;
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
  promptConfig: PrePromptConfig;
  traderConfig: TraderConfig;
  runtimeConfigId: string;
  runtimeConfig: RuntimeConfig;
};

const parseJson = <T>(value: unknown): T => {
  if (typeof value === "string") {
    return JSON.parse(value) as T;
  }

  return value as T;
};

const parseStoredContextSymbols = (value: unknown) => {
  const rawSymbols = parseJson<string[]>(value);
  const symbolScope = rawSymbols.includes(ALL_SYMBOLS_TOKEN) ? "all" : "selected";

  return {
    symbolScope,
    contextSymbols: rawSymbols.filter((symbol) => symbol !== ALL_SYMBOLS_TOKEN)
  } as const;
};

const parsePromptConfig = (value: unknown) => prePromptConfigSchema.parse(parseJson(value));

const parseTraderConfig = (value: unknown) => traderConfigSchema.parse(parseJson(value));

const buildRuntimeConfig = (row: {
  enabled: boolean;
  venue: "binance";
  frequency_minutes: number;
  mode: "testnet" | "live";
  asset_class: "spot";
  execution_config: unknown;
  context_symbols: unknown;
}): RuntimeConfig => {
  const contextConfig = parseStoredContextSymbols(row.context_symbols);

  return runtimeConfigSchema.parse({
    enabled: row.enabled,
    venue: row.venue,
    frequencyMinutes: row.frequency_minutes,
    mode: row.mode,
    assetClass: row.asset_class,
    symbolScope: contextConfig.symbolScope,
    execution: parseJson<Record<string, JsonValue>>(row.execution_config),
    contextSymbols: contextConfig.contextSymbols
  });
};

export const getDueBots = async (): Promise<BotSetup[]> => {
  const rows = await sql<BotSetup[]>`
    select
      b.id,
      b.bot_number as "botNumber",
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
      b.prompt_config as "promptConfig",
      b.trader_config as "traderConfig",
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
    botNumber: row.botNumber,
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
    promptConfig: parsePromptConfig(row.promptConfig),
    traderConfig: parseTraderConfig(row.traderConfig),
    runtimeConfigId: row.runtimeConfigId,
    runtimeConfig: buildRuntimeConfig(row as never)
  }));
};

export const getBotSetupById = async (botId: string): Promise<BotSetup | null> => {
  const rows = await sql<BotSetup[]>`
    select
      b.id,
      b.bot_number as "botNumber",
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
      b.prompt_config as "promptConfig",
      b.trader_config as "traderConfig",
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
    botNumber: row.botNumber,
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
    promptConfig: parsePromptConfig(row.promptConfig),
    traderConfig: parseTraderConfig(row.traderConfig),
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
  compactContext: Record<string, unknown>;
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
      ${sql.json(input.compactContext as JsonValue)},
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
        executed_notional_usd,
        fee_amount,
        fee_asset,
        fee_asset_usd_price,
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
        ${parsed.executedNotionalUsd},
        ${parsed.feeAmount},
        ${parsed.feeAsset},
        ${parsed.feeAssetUsdPrice},
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

const getSampleQuality = (daysRunning: number, tradeCount: number) => {
  if (daysRunning >= 14 && tradeCount >= 50) {
    return "high" as const;
  }

  if (daysRunning >= 3 && tradeCount >= 10) {
    return "medium" as const;
  }

  return "low" as const;
};

export const getDashboard = async (): Promise<DashboardPayload> => {
  const botRows = await sql`
    with run_stats as (
      select
        bot_id,
        count(*)::int as "runCount"
      from runs
      group by bot_id
    ),
    trade_stats as (
      select
        r.bot_id,
        count(e.id)::int as "tradeCount",
        coalesce(sum(e.fee_usd), 0)::float8 as "totalFeesUsd"
      from runs r
      left join executions e on e.run_id = r.id
      group by r.bot_id
    ),
    latest_run as (
      select distinct on (r.bot_id)
        r.bot_id,
        r.status as "lastRunStatus",
        r.error_state as "errorState",
        d.rationale_summary as "latestDecisionSummary"
      from runs r
      left join decisions d on d.run_id = r.id
      order by r.bot_id, r.created_at desc
    ),
    latest_snapshot as (
      select distinct on (r.bot_id)
        r.bot_id,
        ps.total_usd_value::float8 as "currentPortfolioUsd",
        ps.gross_pnl_usd::float8 as "grossPnlUsd",
        ps.net_pnl_usd::float8 as "netPnlUsd"
      from portfolio_snapshots ps
      join runs r on r.id = ps.run_id
      order by r.bot_id, ps.created_at desc
    )
    select
      b.id,
      b.bot_number as "botNumber",
      b.name,
      b.slug,
      b.created_at as "startedAt",
      brc.enabled,
      brc.venue,
      brc.frequency_minutes as "frequencyMinutes",
      brc.mode,
      brc.asset_class as "assetClass",
      concat(p.name, ' v', pv.version) as "promptVersionLabel",
      mp.name as "modelProfileName",
      coalesce(run_stats."runCount", 0) as "runCount",
      coalesce(trade_stats."tradeCount", 0) as "tradeCount",
      coalesce(trade_stats."totalFeesUsd", 0) as "totalFeesUsd",
      latest_run."lastRunStatus",
      latest_run."latestDecisionSummary",
      cast(latest_run."errorState" ->> 'message' as text) as "latestError",
      latest_snapshot."grossPnlUsd",
      latest_snapshot."netPnlUsd",
      latest_snapshot."currentPortfolioUsd",
      brc.updated_at as "updatedAt"
    from bots b
    join bot_runtime_configs brc on brc.bot_id = b.id
    join prompt_versions pv on pv.id = b.active_prompt_version_id
    join prompts p on p.id = pv.prompt_id
    join model_profiles mp on mp.id = b.active_model_profile_id
    left join run_stats on run_stats.bot_id = b.id
    left join trade_stats on trade_stats.bot_id = b.id
    left join latest_run on latest_run.bot_id = b.id
    left join latest_snapshot on latest_snapshot.bot_id = b.id
    order by b.bot_number asc
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
      e.executed_notional_usd as "executedNotionalUsd",
      e.fee_amount as "feeAmount",
      e.fee_asset as "feeAsset",
      e.fee_asset_usd_price as "feeAssetUsdPrice",
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
      concat('Bot #', b.bot_number, ' ', b.name) as "botName",
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

  const performanceRows = await sql<
    {
      botId: string;
      botNumber: number;
      botName: string;
      at: Date;
      totalUsdValue: number;
    }[]
  >`
    select
      b.id as "botId",
      b.bot_number as "botNumber",
      b.name as "botName",
      ps.created_at as "at",
      ps.total_usd_value::float8 as "totalUsdValue"
    from portfolio_snapshots ps
    join runs r on r.id = ps.run_id
    join bots b on b.id = r.bot_id
    where ps.stage = 'after'
    order by b.bot_number asc, ps.created_at asc
  `;

  const performanceSeriesMap = new Map<
    string,
    { botId: string; botName: string; botNumber: number; points: { at: string; totalUsdValue: number; normalizedValue: number }[] }
  >();

  for (const row of performanceRows) {
    const existing = performanceSeriesMap.get(row.botId);
    const point = {
      at: row.at.toISOString(),
      totalUsdValue: Number(row.totalUsdValue),
      normalizedValue: 100
    };

    if (existing) {
      existing.points.push(point);
    } else {
      performanceSeriesMap.set(row.botId, {
        botId: row.botId,
        botName: row.botName,
        botNumber: row.botNumber,
        points: [point]
      });
    }
  }

  const performanceSeries = Array.from(performanceSeriesMap.values()).map((series) => {
    const firstValue = series.points[0]?.totalUsdValue ?? null;

    return botPerformanceSeriesSchema.parse({
      ...series,
      points: series.points.map((point) => ({
        ...point,
        normalizedValue: firstValue && firstValue > 0 ? (point.totalUsdValue / firstValue) * 100 : 100
      }))
    });
  });

  return dashboardSchema.parse({
    generatedAt: new Date().toISOString(),
    bots: botRows.map((row) => {
      const startedAt = row.startedAt.toISOString();
      const daysRunning = Math.max(
        0,
        (Date.now() - row.startedAt.getTime()) / (1000 * 60 * 60 * 24)
      );
      const tradeCount = Number(row.tradeCount ?? 0);

      return botSummarySchema.parse({
        ...row,
        startedAt,
        daysRunning,
        tradeCount,
        avgTradesPerDay: tradeCount / Math.max(daysRunning, 1),
        totalFeesUsd: row.totalFeesUsd === null ? null : Number(row.totalFeesUsd),
        grossPnlUsd: row.grossPnlUsd === null ? null : Number(row.grossPnlUsd),
        netPnlUsd: row.netPnlUsd === null ? null : Number(row.netPnlUsd),
        currentPortfolioUsd: row.currentPortfolioUsd === null ? null : Number(row.currentPortfolioUsd),
        sampleQuality: getSampleQuality(daysRunning, tradeCount),
        updatedAt: row.updatedAt.toISOString()
      });
    }),
    performanceSeries,
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

export const getBotPrePromptContext = async (input: {
  botId: string;
  pastTradesLookback: number;
}) => {
  const [performance] = await sql<
    {
      startedAt: Date;
      runCount: number;
      tradeCount: number;
      totalFeesUsd: number | null;
      currentPortfolioUsd: number | null;
      grossPnlUsd: number | null;
      netPnlUsd: number | null;
      firstPortfolioUsd: number | null;
    }[]
  >`
    with run_stats as (
      select bot_id, count(*)::int as "runCount"
      from runs
      where bot_id = ${input.botId}
      group by bot_id
    ),
    trade_stats as (
      select
        r.bot_id,
        count(e.id)::int as "tradeCount",
        coalesce(sum(e.fee_usd), 0)::float8 as "totalFeesUsd"
      from runs r
      left join executions e on e.run_id = r.id
      where r.bot_id = ${input.botId}
      group by r.bot_id
    ),
    first_snapshot as (
      select distinct on (r.bot_id)
        r.bot_id,
        ps.total_usd_value::float8 as "firstPortfolioUsd"
      from portfolio_snapshots ps
      join runs r on r.id = ps.run_id
      where r.bot_id = ${input.botId}
      order by r.bot_id, ps.created_at asc
    ),
    latest_snapshot as (
      select distinct on (r.bot_id)
        r.bot_id,
        ps.total_usd_value::float8 as "currentPortfolioUsd",
        ps.gross_pnl_usd::float8 as "grossPnlUsd",
        ps.net_pnl_usd::float8 as "netPnlUsd"
      from portfolio_snapshots ps
      join runs r on r.id = ps.run_id
      where r.bot_id = ${input.botId}
      order by r.bot_id, ps.created_at desc
    )
    select
      b.created_at as "startedAt",
      coalesce(run_stats."runCount", 0) as "runCount",
      coalesce(trade_stats."tradeCount", 0) as "tradeCount",
      coalesce(trade_stats."totalFeesUsd", 0)::float8 as "totalFeesUsd",
      latest_snapshot."currentPortfolioUsd",
      latest_snapshot."grossPnlUsd",
      latest_snapshot."netPnlUsd",
      first_snapshot."firstPortfolioUsd"
    from bots b
    left join run_stats on run_stats.bot_id = b.id
    left join trade_stats on trade_stats.bot_id = b.id
    left join first_snapshot on first_snapshot.bot_id = b.id
    left join latest_snapshot on latest_snapshot.bot_id = b.id
    where b.id = ${input.botId}
    limit 1
  `;

  const pastTrades = await sql`
    select
      e.symbol,
      e.side,
      e.order_type as "orderType",
      e.status,
      e.executed_quantity as "executedQuantity",
      e.average_fill_price as "averageFillPrice",
      e.executed_notional_usd as "executedNotionalUsd",
      e.fee_usd as "feeUsd",
      e.created_at as "createdAt"
    from executions e
    join runs r on r.id = e.run_id
    where r.bot_id = ${input.botId}
    order by e.created_at desc
    limit ${input.pastTradesLookback}
  `;

  const rankingRows = await sql`
    with latest_snapshot as (
      select distinct on (r.bot_id)
        r.bot_id,
        ps.net_pnl_usd::float8 as "netPnlUsd",
        ps.total_usd_value::float8 as "currentPortfolioUsd"
      from portfolio_snapshots ps
      join runs r on r.id = ps.run_id
      where ps.stage = 'after'
      order by r.bot_id, ps.created_at desc
    )
    select
      b.id,
      b.bot_number as "botNumber",
      b.name,
      latest_snapshot."netPnlUsd",
      latest_snapshot."currentPortfolioUsd"
    from bots b
    left join latest_snapshot on latest_snapshot.bot_id = b.id
    order by latest_snapshot."netPnlUsd" desc nulls last, b.bot_number asc
  `;

  return {
    performance:
      performance === undefined
        ? null
        : {
            startedAt: performance.startedAt.toISOString(),
            daysRunning:
              (Date.now() - performance.startedAt.getTime()) / (1000 * 60 * 60 * 24),
            runCount: Number(performance.runCount ?? 0),
            tradeCount: Number(performance.tradeCount ?? 0),
            totalFeesUsd: performance.totalFeesUsd === null ? null : Number(performance.totalFeesUsd),
            currentPortfolioUsd:
              performance.currentPortfolioUsd === null ? null : Number(performance.currentPortfolioUsd),
            grossPnlUsd: performance.grossPnlUsd === null ? null : Number(performance.grossPnlUsd),
            netPnlUsd: performance.netPnlUsd === null ? null : Number(performance.netPnlUsd),
            firstPortfolioUsd:
              performance.firstPortfolioUsd === null ? null : Number(performance.firstPortfolioUsd)
          },
    pastTrades: pastTrades.map((trade: any) => ({
      ...trade,
      createdAt: trade.createdAt.toISOString(),
      executedQuantity: trade.executedQuantity === null ? null : Number(trade.executedQuantity),
      averageFillPrice: trade.averageFillPrice === null ? null : Number(trade.averageFillPrice),
      executedNotionalUsd: trade.executedNotionalUsd === null ? null : Number(trade.executedNotionalUsd),
      feeUsd: trade.feeUsd === null ? null : Number(trade.feeUsd)
    })),
    ranking: rankingRows.map((row: any, index: number) => ({
      rank: index + 1,
      botId: row.id,
      botNumber: row.botNumber,
      botName: row.name,
      netPnlUsd: row.netPnlUsd === null ? null : Number(row.netPnlUsd),
      currentPortfolioUsd: row.currentPortfolioUsd === null ? null : Number(row.currentPortfolioUsd)
    }))
  };
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

export const listPrompts = async () =>
  sql`
    select
      p.id,
      p.name,
      p.slug,
      p.created_at as "createdAt",
      max(pv.created_at) as "latestVersionCreatedAt",
      coalesce(
        json_agg(
          json_build_object(
            'id', pv.id,
            'version', pv.version,
            'createdAt', pv.created_at
          ) order by pv.version desc
        ) filter (where pv.id is not null),
        '[]'::json
      ) as versions
    from prompts p
    left join prompt_versions pv on pv.prompt_id = p.id
    group by p.id, p.name, p.slug, p.created_at
    order by max(pv.created_at) desc nulls last, p.created_at desc
  `;

export const listModelProfiles = async (provider?: string) => {
  if (provider) {
    return sql`
      select
        id,
        name,
        provider,
        model,
        settings,
        created_at as "createdAt"
      from model_profiles
      where provider = ${provider}
      order by created_at desc
    `;
  }

  return sql`
    select
      id,
      name,
      provider,
      model,
      settings,
      created_at as "createdAt"
    from model_profiles
    order by created_at desc
  `;
};

export const getPromptVersionBody = async (versionId: string) => {
  const [row] = await sql<{ id: string; body: string; version: number; promptId: string; promptName: string }[]>`
    select
      pv.id,
      pv.body,
      pv.version,
      p.id as "promptId",
      p.name as "promptName"
    from prompt_versions pv
    join prompts p on p.id = pv.prompt_id
    where pv.id = ${versionId}
    limit 1
  `;
  return row ?? null;
};

export const addPromptVersion = async (input: { promptId: string; body: string }) => {
  const [maxRow] = await sql<{ maxVersion: number }[]>`
    select coalesce(max(version), 0) as "maxVersion"
    from prompt_versions
    where prompt_id = ${input.promptId}
  `;
  const nextVersion = (maxRow?.maxVersion ?? 0) + 1;
  const [promptVersion] = await sql<{ id: string }[]>`
    insert into prompt_versions (prompt_id, version, body)
    values (${input.promptId}, ${nextVersion}, ${input.body})
    returning id
  `;
  return { promptVersionId: promptVersion.id, version: nextVersion };
};

export const createPrompt = async (input: { name: string; slug: string; initialBody: string }) => {
  const [prompt] = await sql<{ id: string }[]>`
    insert into prompts (name, slug)
    values (${input.name}, ${input.slug})
    returning id
  `;

  const [promptVersion] = await sql<{ id: string }[]>`
    insert into prompt_versions (prompt_id, version, body)
    values (${prompt.id}, 1, ${input.initialBody})
    returning id
  `;

  return { promptId: prompt.id, promptVersionId: promptVersion.id };
};

export const createModelProfile = async (input: {
  name: string;
  provider: string;
  model: string;
  settings: Record<string, JsonValue>;
}) => {
  const [row] = await sql<{ id: string }[]>`
    insert into model_profiles (name, provider, model, settings)
    values (${input.name}, ${input.provider}, ${input.model}, ${sql.json(input.settings)})
    returning id
  `;

  return row.id;
};

export const createBot = async (input: {
  name: string;
  slug: string;
  promptVersionId: string;
  modelProfileId: string;
  promptConfig: PrePromptConfig;
  traderConfig?: TraderConfig;
  parentBotId?: string | null;
  runtimeConfig: Omit<RuntimeConfig, "enabled">;
}) => {
  const [bot] = await sql<{ id: string }[]>`
    insert into bots (
      name,
      slug,
      active_prompt_version_id,
      active_model_profile_id,
      parent_bot_id,
      prompt_config,
      trader_config
    )
    values (
      ${input.name},
      ${input.slug},
      ${input.promptVersionId},
      ${input.modelProfileId},
      ${input.parentBotId ?? null},
      ${sql.json(input.promptConfig)},
      ${sql.json(input.traderConfig ?? traderConfigSchema.parse({}))}
    )
    returning id
  `;

  await sql`
    insert into bot_runtime_configs (
      bot_id,
      enabled,
      venue,
      frequency_minutes,
      mode,
      asset_class,
      execution_config,
      context_symbols
    ) values (
      ${bot.id},
      false,
      ${input.runtimeConfig.venue},
      ${input.runtimeConfig.frequencyMinutes},
      ${input.runtimeConfig.mode},
      ${input.runtimeConfig.assetClass},
      ${sql.json(input.runtimeConfig.execution)},
      ${sql.json(input.runtimeConfig.contextSymbols)}
    )
  `;

  return bot.id;
};

export const updateBotConfig = async (
  botId: string,
  input: {
    name?: string;
    enabled?: boolean;
  }
) => {
  if (input.name) {
    await sql`
      update bots
      set name = ${input.name}
      where id = ${botId}
    `;
  }

  const runtimeUpdates: Record<string, unknown> = {};
  if (input.enabled !== undefined) runtimeUpdates.enabled = input.enabled;

  if (Object.keys(runtimeUpdates).length > 0) {
    await sql`
      update bot_runtime_configs
      set ${sql(runtimeUpdates)},
          updated_at = now()
      where bot_id = ${botId}
    `;
  }
};

export const assetClass = assetClassSchema.parse("spot");
