// module: Read queries that assemble the dashboard payload.
import {
  botSummarySchema,
  botPerformanceSeriesSchema,
  portfolioSnapshotSchema,
  type DashboardPayload
} from "@cosmu/shared";
import { sql } from "../../db.js";
import { parseJson, toIsoString } from "./helpers.js";

const getSampleQuality = (daysRunning: number, tradeCount: number) => {
  if (daysRunning >= 14 && tradeCount >= 50) return "high" as const;
  if (daysRunning >= 3 && tradeCount >= 10) return "medium" as const;
  return "low" as const;
};

export const getBotPrePromptContext = async (input: {
  botId: string;
  pastTradesLookback: number;
}) => {
  const executionLedger = await sql`
    select
      e.symbol, e.side,
      e.executed_quantity::float8 as "executedQuantity",
      e.executed_notional_usd::float8 as "executedNotionalUsd",
      e.fee_amount::float8 as "feeAmount",
      e.fee_asset as "feeAsset"
    from executions e
    join runs r on r.id = e.run_id
    where r.bot_id = ${input.botId}
      and r.status in ('success', 'uncertain')
      and e.status = 'success'
    order by e.created_at asc
  `;

  const openQuantityBySymbol = new Map<string, number>();
  for (const entry of executionLedger) {
    const current = openQuantityBySymbol.get(entry.symbol) ?? 0;
    const quantity = Number(entry.executedQuantity ?? 0);
    openQuantityBySymbol.set(
      entry.symbol,
      entry.side === "buy" ? current + quantity : current - quantity
    );
  }

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
      from runs where bot_id = ${input.botId} group by bot_id
    ),
    trade_stats as (
      select r.bot_id, count(e.id)::int as "tradeCount",
        coalesce(sum(e.fee_usd), 0)::float8 as "totalFeesUsd"
      from runs r left join executions e on e.run_id = r.id
      where r.bot_id = ${input.botId} group by r.bot_id
    ),
    first_snapshot as (
      select distinct on (r.bot_id) r.bot_id,
        ps.total_usd_value::float8 as "firstPortfolioUsd"
      from portfolio_snapshots ps join runs r on r.id = ps.run_id
      where r.bot_id = ${input.botId}
      order by r.bot_id, ps.created_at asc
    ),
    latest_snapshot as (
      select distinct on (r.bot_id) r.bot_id,
        ps.total_usd_value::float8 as "currentPortfolioUsd",
        ps.gross_pnl_usd::float8 as "grossPnlUsd",
        ps.net_pnl_usd::float8 as "netPnlUsd"
      from portfolio_snapshots ps join runs r on r.id = ps.run_id
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
      e.symbol, e.side, e.order_type as "orderType", e.status,
      e.executed_quantity as "executedQuantity",
      e.average_fill_price as "averageFillPrice",
      e.executed_notional_usd as "executedNotionalUsd",
      nullif(e.order_intent ->> 'stopLossPrice', 'null')::numeric as "stopLossPrice",
      nullif(e.order_intent ->> 'takeProfitPrice', 'null')::numeric as "takeProfitPrice",
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
      select distinct on (r.bot_id) r.bot_id,
        ps.net_pnl_usd::float8 as "netPnlUsd",
        ps.total_usd_value::float8 as "currentPortfolioUsd"
      from portfolio_snapshots ps join runs r on r.id = ps.run_id
      where ps.stage = 'after'
      order by r.bot_id, ps.created_at desc
    )
    select b.id, b.bot_number as "botNumber", b.name,
      latest_snapshot."netPnlUsd", latest_snapshot."currentPortfolioUsd"
    from bots b
    left join latest_snapshot on latest_snapshot.bot_id = b.id
    order by latest_snapshot."netPnlUsd" desc nulls last, b.bot_number asc
  `;

  return {
    performance:
      performance === undefined
        ? null
        : (() => {
            const startedAtRaw = performance.startedAt ?? (performance as { started_at?: Date | string }).started_at;
            const startedAtIso = toIsoString(startedAtRaw) ?? new Date().toISOString();
            const startedAtDate = startedAtRaw instanceof Date ? startedAtRaw : new Date(startedAtIso);
            return {
              startedAt: startedAtIso,
              daysRunning: (Date.now() - startedAtDate.getTime()) / (1000 * 60 * 60 * 24),
              runCount: Number(performance.runCount ?? 0),
              tradeCount: Number(performance.tradeCount ?? 0),
              totalFeesUsd: performance.totalFeesUsd === null ? null : Number(performance.totalFeesUsd),
              currentPortfolioUsd: performance.currentPortfolioUsd === null ? null : Number(performance.currentPortfolioUsd),
              grossPnlUsd: performance.grossPnlUsd === null ? null : Number(performance.grossPnlUsd),
              netPnlUsd: performance.netPnlUsd === null ? null : Number(performance.netPnlUsd),
              firstPortfolioUsd: performance.firstPortfolioUsd === null ? null : Number(performance.firstPortfolioUsd)
            };
          })(),
    pastTrades: (() => {
      const remainingBySymbol = new Map(openQuantityBySymbol);
      return pastTrades.map((trade: any) => {
        const executedQuantity = trade.executedQuantity === null ? null : Number(trade.executedQuantity);
        let isActive = false;
        if (trade.side === "buy" && trade.status === "success" && executedQuantity !== null) {
          const remaining = remainingBySymbol.get(trade.symbol) ?? 0;
          if (remaining > 1e-8) {
            isActive = true;
            remainingBySymbol.set(trade.symbol, Math.max(0, remaining - executedQuantity));
          }
        }
        return {
          ...trade,
          createdAt: toIsoString(trade.createdAt ?? trade.created_at) ?? new Date().toISOString(),
          executedQuantity,
          averageFillPrice: trade.averageFillPrice === null ? null : Number(trade.averageFillPrice),
          executedNotionalUsd: trade.executedNotionalUsd === null ? null : Number(trade.executedNotionalUsd),
          stopLossPrice: trade.stopLossPrice === null ? null : Number(trade.stopLossPrice),
          takeProfitPrice: trade.takeProfitPrice === null ? null : Number(trade.takeProfitPrice),
          feeUsd: trade.feeUsd === null ? null : Number(trade.feeUsd),
          isActive
        };
      });
    })(),
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
