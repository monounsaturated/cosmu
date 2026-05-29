import { sql } from "../db.js";
import { dashboardSchema, botSummarySchema, portfolioSnapshotSchema } from "@cosmu/shared";
import { getLlmSpendEstimate } from "./llm-spend.js";
import { getCachedMarketDataSnapshot } from "./market-data-cache.js";

const parseJson = <T>(value: unknown): T => {
  if (typeof value === "string") {
    return JSON.parse(value) as T;
  }
  return value as T;
};

const getSampleQuality = (daysRunning: number, tradeCount: number) => {
  if (daysRunning >= 14 && tradeCount >= 50) return "high" as const;
  if (daysRunning >= 3 && tradeCount >= 10) return "medium" as const;
  return "low" as const;
};

export const getDashboard = async () => {
  const botRows = await sql`
    with run_stats as (
      select bot_id, count(*)::int as "runCount"
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
        ps.net_pnl_usd::float8 as "netPnlUsd",
        ps.fee_usd::float8 as "snapshotFeeUsd",
        ps.raw_snapshot as "rawSnapshot"
      from portfolio_snapshots ps
      join runs r on r.id = ps.run_id
      where ps.stage = 'after'
      order by r.bot_id, ps.created_at desc
    )
    select
      b.id,
      b.bot_number as "botNumber",
      b.name,
      b.slug,
      b.created_at as "startedAt",
      coalesce(b.workspace_mode, 'light') as "workspaceMode",
      brc.enabled,
      brc.venue,
      brc.frequency_minutes as "frequencyMinutes",
      brc.mode,
      brc.asset_class as "assetClass",
      concat(p.name, ' v', pv.version) as "promptVersionLabel",
      case when tp.id is not null then concat(tp.name, ' v', tpv.version) else null end as "traderPromptVersionLabel",
      mp.name as "modelProfileName",
      mp.name as "researchModelName",
      mp.provider as "researchModelProvider",
      coalesce(tmp.name, mp.name) as "traderModelName",
      coalesce(tmp.provider, mp.provider) as "traderModelProvider",
      coalesce(run_stats."runCount", 0) as "runCount",
      coalesce(trade_stats."tradeCount", 0) as "tradeCount",
      coalesce(trade_stats."totalFeesUsd", 0) as "totalFeesUsd",
      latest_run."lastRunStatus",
      latest_run."latestDecisionSummary",
      cast(latest_run."errorState" ->> 'message' as text) as "latestError",
      latest_snapshot."currentPortfolioUsd",
      latest_snapshot."grossPnlUsd",
      latest_snapshot."netPnlUsd",
      latest_snapshot."snapshotFeeUsd",
      latest_snapshot."rawSnapshot",
      brc.budget_usdt::float8 as "budgetUsdt",
      brc.updated_at as "updatedAt"
    from bots b
    join bot_runtime_configs brc on brc.bot_id = b.id
    join research_prompt_versions pv on pv.id = b.active_prompt_version_id
    join research_prompts p on p.id = pv.prompt_id
    join model_profiles mp on mp.id = b.active_model_profile_id
    left join model_profiles tmp on tmp.id = b.active_trader_model_profile_id
    left join trader_prompt_versions tpv on tpv.id = b.active_trader_prompt_version_id
    left join trader_prompts tp on tp.id = tpv.prompt_id
    left join run_stats on run_stats.bot_id = b.id
    left join trade_stats on trade_stats.bot_id = b.id
    left join latest_run on latest_run.bot_id = b.id
    left join latest_snapshot on latest_snapshot.bot_id = b.id
    order by brc.enabled desc, b.created_at desc
  `;

  const marketData = getCachedMarketDataSnapshot();
  const testnetBalance: any = marketData.testnet.balance;
  const liveBalance: any = marketData.live.balance;

  const allocatedByMode = new Map<string, number>([
    ["live", 0],
    ["testnet", 0]
  ]);

  const bots = botRows.map((row) => {
    const startedAt = row.startedAt.toISOString();
    const daysRunning = Math.max(0, (Date.now() - row.startedAt.getTime()) / (1000 * 60 * 60 * 24));
    const tradeCount = Number(row.tradeCount ?? 0);
    const budgetUsdt = Number(row.budgetUsdt ?? 1000);
    const currentPortfolioUsd = row.currentPortfolioUsd === null ? budgetUsdt : Number(row.currentPortfolioUsd);
    const netPnlUsd = row.netPnlUsd === null ? currentPortfolioUsd - budgetUsdt : Number(row.netPnlUsd);

    if (row.enabled) {
      allocatedByMode.set(row.mode, (allocatedByMode.get(row.mode) ?? 0) + currentPortfolioUsd);
    }

    return botSummarySchema.parse({
      ...row,
      startedAt,
      daysRunning,
      tradeCount,
      avgTradesPerDay: tradeCount / Math.max(daysRunning, 1),
      totalFeesUsd: row.totalFeesUsd === null ? null : Number(row.totalFeesUsd),
      grossPnlUsd: row.grossPnlUsd === null ? null : Number(row.grossPnlUsd),
      netPnlUsd,
      currentPortfolioUsd,
      sampleQuality: getSampleQuality(daysRunning, tradeCount),
      updatedAt: row.updatedAt.toISOString()
    });
  });

  const liveAccountBalance = (liveBalance?.totalFreeUsdt ?? 0) + (liveBalance?.totalLockedUsdt ?? 0);
  const testnetAccountBalance = (testnetBalance?.totalFreeUsdt ?? 0) + (testnetBalance?.totalLockedUsdt ?? 0);
  const accountConfigs = [
    {
      id: "binance-live",
      label: "Binance Live",
      venue: "binance",
      mode: "live",
      balance: liveAccountBalance,
      connected: Boolean(liveBalance)
    },
    {
      id: "binance-testnet",
      label: "Binance Testnet",
      venue: "binance-testnet",
      mode: "testnet",
      balance: testnetAccountBalance,
      connected: Boolean(testnetBalance)
    }
  ];
  const accounts = accountConfigs.map((account) => {
    const configuredAgents = bots.filter((bot) => bot.mode === account.mode).length;
    const activeAgents = bots.filter((bot) => bot.mode === account.mode && bot.enabled).length;
    const allocatedAmount = allocatedByMode.get(account.mode) ?? 0;
    const spareAmount = account.connected
      ? Math.max(0, account.balance - allocatedAmount)
      : 0;
    const status = account.connected
      ? "connected"
      : configuredAgents > 0
        ? "configured"
        : "unconfigured";
    return {
      id: account.id,
      label: account.label,
      venue: account.venue,
      mode: account.mode,
      accountBalance: account.balance,
      allocatedAmount,
      spareAmount,
      connected: account.connected,
      configuredAgents,
      activeAgents,
      status
    };
  });
  const liveAccount = accounts.find((account) => account.mode === "live") ?? null;
  const testnetAccount = accounts.find((account) => account.mode === "testnet") ?? null;
  const llmSpendEstimate = await getLlmSpendEstimate();

  // Recent Runs
  const recentRuns = await sql`
    select
      r.id,
      case when b.name is not null and b.name != ''
        then concat('Bot #', b.bot_number, ' - ', b.name)
        else concat('Bot #', b.bot_number)
      end as "botName",
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

  // Recent Executions
  const recentExecutions = await sql`
    select
      e.run_id as "runId",
      e.asset_class as "assetClass",
      e.venue,
      e.status,
      e.symbol,
      e.side,
      e.order_type as "orderType",
      e.requested_quantity::float8 as "requestedQuantity",
      e.executed_quantity::float8 as "executedQuantity",
      e.requested_limit_price::float8 as "requestedLimitPrice",
      e.average_fill_price::float8 as "averageFillPrice",
      e.executed_notional_usd::float8 as "executedNotionalUsd",
      e.fee_amount::float8 as "feeAmount",
      e.fee_asset as "feeAsset",
      e.fee_asset_usd_price::float8 as "feeAssetUsdPrice",
      e.fee_usd::float8 as "feeUsd",
      e.slippage_pct::float8 as "slippagePct",
      e.oco_order_id as "ocoOrderId",
      e.order_intent as "orderIntent",
      e.raw_venue_response as "rawVenueResponse"
    from executions e
    order by e.created_at desc
    limit 20
  `;

  const promptVersions = await sql`
    select
      p.name as "promptName",
      pv.version,
      concat(p.name, ' v', pv.version) as label,
      pv.created_at as "createdAt"
    from research_prompt_versions pv
    join research_prompts p on p.id = pv.prompt_id
    order by pv.created_at desc
    limit 20
  `;

  const latestSnapshots = bots.map((bot) => {
    const row = botRows.find((candidate) => candidate.id === bot.id);
    const rawSnapshot = row?.rawSnapshot ? parseJson(row.rawSnapshot) : null;
    if (rawSnapshot) {
      return {
        botId: bot.id,
        botName: bot.name?.trim()
          ? `Bot #${bot.botNumber} — ${bot.name.trim()}`
          : `Bot #${bot.botNumber}`,
        snapshot: portfolioSnapshotSchema.parse(rawSnapshot)
      };
    }

    const cashAsset = bot.mode === "live" ? "USDC" : "USDT";
    return {
      botId: bot.id,
      botName: bot.name?.trim()
        ? `Bot #${bot.botNumber} — ${bot.name.trim()}`
        : `Bot #${bot.botNumber}`,
      snapshot: portfolioSnapshotSchema.parse({
        assetClass: bot.assetClass,
        totalUsdValue: bot.currentPortfolioUsd ?? 0,
        grossPnlUsd: bot.grossPnlUsd,
        netPnlUsd: bot.netPnlUsd ?? 0,
        feeUsd: bot.totalFeesUsd ?? 0,
        balances: [{ asset: cashAsset, free: bot.currentPortfolioUsd ?? bot.budgetUsdt, locked: 0, usdValue: bot.currentPortfolioUsd ?? bot.budgetUsdt }],
        prices: [],
        capturedAt: new Date().toISOString()
      })
    };
  });

  return dashboardSchema.parse({
    generatedAt: new Date().toISOString(),
    marketDataStatus: {
      live: {
        pricesUpdatedAt: marketData.live.pricesUpdatedAt,
        balanceUpdatedAt: marketData.live.balanceUpdatedAt,
        pricesError: marketData.live.pricesError,
        balanceError: marketData.live.balanceError,
        stale: marketData.live.stale
      },
      testnet: {
        pricesUpdatedAt: marketData.testnet.pricesUpdatedAt,
        balanceUpdatedAt: marketData.testnet.balanceUpdatedAt,
        pricesError: marketData.testnet.pricesError,
        balanceError: marketData.testnet.balanceError,
        stale: marketData.testnet.stale
      }
    },
    venueOverview: {
      live: liveAccount ? {
        accountBalance: liveAccount.accountBalance,
        allocatedAmount: liveAccount.allocatedAmount,
        spareAmount: liveAccount.spareAmount
      } : null,
      testnet: testnetAccount ? {
        accountBalance: testnetAccount.accountBalance,
        allocatedAmount: testnetAccount.allocatedAmount,
        spareAmount: testnetAccount.spareAmount
      } : null
    },
    accounts,
    bots,
    llmSpendEstimate,
    performanceSeries: [], // Simplify: skip historical performance chart points or reconstruct them later
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
    latestSnapshots,
    promptVersions: promptVersions.map((row) => ({
      ...row,
      createdAt: row.createdAt.toISOString()
    }))
  });
};
