// module: Persist/read execution records (venue orders, fills, fees).
import { executionRecordSchema, type ExecutionRecord } from "@cosmu/shared";
import { sql } from "../../db.js";
import type { JsonValue } from "./helpers.js";

let executionColumnsMode: "full" | "legacy" | null = null;

const isLegacyExecutionColumnsError = (error: unknown) => {
  if (!(error instanceof Error)) return false;
  const message = error.message.toLowerCase();
  return (
    message.includes("column \"stop_loss_price\"") ||
    message.includes("column \"take_profit_price\"") ||
    message.includes("column \"oco_order_id\"")
  );
};

export type StoredExecution = { id: string; record: ExecutionRecord };

export const storeExecutionRecords = async (
  runId: string,
  executionRecords: ExecutionRecord[]
): Promise<StoredExecution[]> => {
  const stored: StoredExecution[] = [];

  for (const execution of executionRecords) {
    const parsed = executionRecordSchema.parse(execution);

    const insertWithFullColumns = async () =>
      sql<{ id: string }[]>`
        insert into executions (
          run_id, asset_class, venue, status, symbol, side, order_type,
          requested_quantity, executed_quantity, requested_limit_price,
          average_fill_price, executed_notional_usd, fee_amount, fee_asset,
          fee_asset_usd_price, fee_usd, slippage_pct,
          stop_loss_price, take_profit_price, oco_order_id,
          order_intent, raw_venue_response
        ) values (
          ${runId}, ${parsed.assetClass}, ${parsed.venue}, ${parsed.status},
          ${parsed.symbol}, ${parsed.side}, ${parsed.orderType},
          ${parsed.requestedQuantity}, ${parsed.executedQuantity},
          ${parsed.requestedLimitPrice}, ${parsed.averageFillPrice},
          ${parsed.executedNotionalUsd}, ${parsed.feeAmount}, ${parsed.feeAsset},
          ${parsed.feeAssetUsdPrice}, ${parsed.feeUsd}, ${parsed.slippagePct},
          ${parsed.stopLossPrice}, ${parsed.takeProfitPrice}, ${parsed.ocoOrderId},
          ${sql.json(parsed.orderIntent)},
          ${sql.json(parsed.rawVenueResponse as JsonValue)}
        )
        returning id
      `;

    const insertLegacy = async () =>
      sql<{ id: string }[]>`
        insert into executions (
          run_id, asset_class, venue, status, symbol, side, order_type,
          requested_quantity, executed_quantity, requested_limit_price,
          average_fill_price, executed_notional_usd, fee_amount, fee_asset,
          fee_asset_usd_price, fee_usd, slippage_pct,
          order_intent, raw_venue_response
        ) values (
          ${runId}, ${parsed.assetClass}, ${parsed.venue}, ${parsed.status},
          ${parsed.symbol}, ${parsed.side}, ${parsed.orderType},
          ${parsed.requestedQuantity}, ${parsed.executedQuantity},
          ${parsed.requestedLimitPrice}, ${parsed.averageFillPrice},
          ${parsed.executedNotionalUsd}, ${parsed.feeAmount}, ${parsed.feeAsset},
          ${parsed.feeAssetUsdPrice}, ${parsed.feeUsd}, ${parsed.slippagePct},
          ${sql.json(parsed.orderIntent)},
          ${sql.json(parsed.rawVenueResponse as JsonValue)}
        )
        returning id
      `;

    const runInsert = async () => {
      if (executionColumnsMode === "legacy") return insertLegacy();
      try {
        const rows = await insertWithFullColumns();
        executionColumnsMode = "full";
        return rows;
      } catch (error) {
        if (!isLegacyExecutionColumnsError(error)) throw error;
        executionColumnsMode = "legacy";
        return insertLegacy();
      }
    };

    const [row] = await runInsert();
    stored.push({ id: row.id, record: parsed });
  }

  return stored;
};
