// module: Persist/read bot positions.
import { sql } from "../../db.js";

export type PositionCloseReason =
  | "take_profit"
  | "stop_loss"
  | "safety_stop"
  | "run_sell"
  | "manual";

export type BotPosition = {
  id: string;
  botId: string;
  symbol: string;
  quantity: number;
  avgEntryPrice: number;
  costBasisUsd: number;
  stopLossPrice: number;
  takeProfitPrice: number;
  safetyStopPrice: number | null;
  safetyStopOrderId: string | null;
  status: "active" | "closed";
  openedAt: string;
  closedAt: string | null;
  closeReason: PositionCloseReason | null;
  realizedPnlUsd: number | null;
  realizedFeesUsd: number | null;
  buyExecutionId: string | null;
  closeExecutionId: string | null;
};

type PositionRow = {
  id: string;
  botId: string;
  symbol: string;
  quantity: string | number;
  avgEntryPrice: string | number;
  costBasisUsd: string | number;
  stopLossPrice: string | number;
  takeProfitPrice: string | number;
  safetyStopPrice: string | number | null;
  safetyStopOrderId: string | null;
  status: "active" | "closed";
  openedAt: Date | string;
  closedAt: Date | string | null;
  closeReason: PositionCloseReason | null;
  realizedPnlUsd: string | number | null;
  realizedFeesUsd: string | number | null;
  buyExecutionId: string | null;
  closeExecutionId: string | null;
};

const num = (v: string | number | null | undefined): number | null => {
  if (v === null || v === undefined) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
};

const numReq = (v: string | number): number => {
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) throw new Error(`Invalid numeric value: ${v}`);
  return n;
};

const parseRow = (row: PositionRow): BotPosition => ({
  id: row.id,
  botId: row.botId,
  symbol: row.symbol,
  quantity: numReq(row.quantity),
  avgEntryPrice: numReq(row.avgEntryPrice),
  costBasisUsd: numReq(row.costBasisUsd),
  stopLossPrice: numReq(row.stopLossPrice),
  takeProfitPrice: numReq(row.takeProfitPrice),
  safetyStopPrice: num(row.safetyStopPrice),
  safetyStopOrderId: row.safetyStopOrderId,
  status: row.status,
  openedAt: row.openedAt instanceof Date ? row.openedAt.toISOString() : row.openedAt,
  closedAt: row.closedAt
    ? row.closedAt instanceof Date
      ? row.closedAt.toISOString()
      : row.closedAt
    : null,
  closeReason: row.closeReason,
  realizedPnlUsd: num(row.realizedPnlUsd),
  realizedFeesUsd: num(row.realizedFeesUsd),
  buyExecutionId: row.buyExecutionId,
  closeExecutionId: row.closeExecutionId
});

const SELECT_COLS = sql`
  id,
  bot_id as "botId",
  symbol,
  quantity,
  avg_entry_price as "avgEntryPrice",
  cost_basis_usd as "costBasisUsd",
  stop_loss_price as "stopLossPrice",
  take_profit_price as "takeProfitPrice",
  safety_stop_price as "safetyStopPrice",
  safety_stop_order_id as "safetyStopOrderId",
  status,
  opened_at as "openedAt",
  closed_at as "closedAt",
  close_reason as "closeReason",
  realized_pnl_usd as "realizedPnlUsd",
  realized_fees_usd as "realizedFeesUsd",
  buy_execution_id as "buyExecutionId",
  close_execution_id as "closeExecutionId"
`;

export const openPosition = async (input: {
  botId: string;
  symbol: string;
  quantity: number;
  avgEntryPrice: number;
  costBasisUsd: number;
  stopLossPrice: number;
  takeProfitPrice: number;
  buyExecutionId: string | null;
}): Promise<BotPosition> => {
  const [row] = await sql<PositionRow[]>`
    insert into bot_positions (
      bot_id, symbol, quantity, avg_entry_price, cost_basis_usd,
      stop_loss_price, take_profit_price, buy_execution_id
    ) values (
      ${input.botId}, ${input.symbol}, ${input.quantity}, ${input.avgEntryPrice},
      ${input.costBasisUsd}, ${input.stopLossPrice}, ${input.takeProfitPrice},
      ${input.buyExecutionId}
    )
    returning ${SELECT_COLS}
  `;
  return parseRow(row);
};

export const listActivePositions = async (botId?: string): Promise<BotPosition[]> => {
  const rows = botId
    ? await sql<PositionRow[]>`
        select ${SELECT_COLS} from bot_positions
        where status = 'active' and bot_id = ${botId}
        order by opened_at asc
      `
    : await sql<PositionRow[]>`
        select ${SELECT_COLS} from bot_positions
        where status = 'active'
        order by opened_at asc
      `;
  return rows.map(parseRow);
};

export const listActivePositionsForBotSymbol = async (
  botId: string,
  symbol: string
): Promise<BotPosition[]> => {
  const rows = await sql<PositionRow[]>`
    select ${SELECT_COLS} from bot_positions
    where status = 'active' and bot_id = ${botId} and symbol = ${symbol}
    order by opened_at asc
  `;
  return rows.map(parseRow);
};

export const closePosition = async (input: {
  id: string;
  closeReason: PositionCloseReason;
  closeExecutionId: string | null;
  realizedPnlUsd: number;
  realizedFeesUsd: number;
}): Promise<void> => {
  await sql`
    update bot_positions
    set status = 'closed',
        closed_at = now(),
        close_reason = ${input.closeReason},
        close_execution_id = ${input.closeExecutionId},
        realized_pnl_usd = ${input.realizedPnlUsd},
        realized_fees_usd = ${input.realizedFeesUsd}
    where id = ${input.id}
  `;
};

export const updateSafetyStop = async (
  id: string,
  safetyStopPrice: number | null,
  safetyStopOrderId: string | null
): Promise<void> => {
  await sql`
    update bot_positions
    set safety_stop_price = ${safetyStopPrice},
        safety_stop_order_id = ${safetyStopOrderId}
    where id = ${id}
  `;
};

/**
 * Reduce an active position's quantity in-place (partial close). Used when a
 * sell consumes only part of a position — we keep the row open with the
 * remaining qty + pro-rated cost basis, same SL/TP, same safety stop.
 */
const reducePositionQuantity = async (
  id: string,
  newQuantity: number,
  newCostBasisUsd: number
): Promise<void> => {
  await sql`
    update bot_positions
    set quantity = ${newQuantity},
        cost_basis_usd = ${newCostBasisUsd}
    where id = ${id}
  `;
};

/**
 * Apply a sell fill to the bot's open positions using FIFO attribution.
 * Walks positions in opened_at ASC order; fully closes each until the sell
 * quantity is consumed, partially reducing the last one if needed.
 *
 * Returns the positions that were touched (closed or reduced) so callers can
 * cancel safety stops and compute realized P&L.
 */
export const applySellToOpenPositions = async (input: {
  botId: string;
  symbol: string;
  sellQuantity: number;
  sellPrice: number;
  sellFeeUsd: number;
  closeExecutionId: string | null;
  closeReason: PositionCloseReason;
}): Promise<{
  fullyClosed: BotPosition[];
  partiallyReduced: { position: BotPosition; closedQuantity: number } | null;
  unmatchedQuantity: number;
}> => {
  const open = await listActivePositionsForBotSymbol(input.botId, input.symbol);
  const fullyClosed: BotPosition[] = [];
  let partiallyReduced: { position: BotPosition; closedQuantity: number } | null = null;

  let remainingSellQty = input.sellQuantity;
  const totalSellFee = input.sellFeeUsd;
  const totalSellQty = input.sellQuantity;

  for (const position of open) {
    if (remainingSellQty <= 1e-12) break;

    // Fee is pro-rated by the share of this position's qty within the total sell qty.
    if (position.quantity <= remainingSellQty + 1e-12) {
      // Full close
      const closedQty = position.quantity;
      const proceedsUsd = closedQty * input.sellPrice;
      const feeShareUsd = totalSellQty > 0 ? totalSellFee * (closedQty / totalSellQty) : 0;
      const realizedPnl = proceedsUsd - position.costBasisUsd - feeShareUsd;

      await closePosition({
        id: position.id,
        closeReason: input.closeReason,
        closeExecutionId: input.closeExecutionId,
        realizedPnlUsd: realizedPnl,
        realizedFeesUsd: feeShareUsd
      });

      fullyClosed.push(position);
      remainingSellQty -= closedQty;
    } else {
      // Partial close — reduce in place
      const closedQty = remainingSellQty;
      const remainingQty = position.quantity - closedQty;
      const closedCostBasis = position.costBasisUsd * (closedQty / position.quantity);
      const remainingCostBasis = position.costBasisUsd - closedCostBasis;
      const proceedsUsd = closedQty * input.sellPrice;
      const feeShareUsd = totalSellQty > 0 ? totalSellFee * (closedQty / totalSellQty) : 0;
      const realizedPnl = proceedsUsd - closedCostBasis - feeShareUsd;

      await reducePositionQuantity(position.id, remainingQty, remainingCostBasis);

      // We can't attach realized P&L directly to the position row (it stays open),
      // so callers should log this via run-level accounting. Return enough info
      // for the caller to do so.
      partiallyReduced = { position, closedQuantity: closedQty };
      remainingSellQty = 0;

      // Also emit a "child" closed row so realized P&L is captured somewhere.
      // We insert a zero-qty closed snapshot row representing the closed slice.
      await sql`
        insert into bot_positions (
          bot_id, symbol, quantity, avg_entry_price, cost_basis_usd,
          stop_loss_price, take_profit_price,
          status, opened_at, closed_at, close_reason,
          realized_pnl_usd, realized_fees_usd,
          buy_execution_id, close_execution_id
        ) values (
          ${position.botId}, ${position.symbol}, 0, ${position.avgEntryPrice},
          ${closedCostBasis}, ${position.stopLossPrice}, ${position.takeProfitPrice},
          'closed', ${position.openedAt}, now(), ${input.closeReason},
          ${realizedPnl}, ${feeShareUsd},
          ${position.buyExecutionId}, ${input.closeExecutionId}
        )
      `;
      // NB: realizedPnl/feeShareUsd used in the insert above
      void realizedPnl;
      void feeShareUsd;
    }
  }

  return {
    fullyClosed,
    partiallyReduced,
    unmatchedQuantity: remainingSellQty
  };
};
