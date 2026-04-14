import { validationResultSchema, type RuntimeConfig, type TradingDecision } from "@cosmu/shared";
import { validateTradability, type VenueContext } from "../adapters/binance.js";

const getBaseAsset = (symbol: string) => symbol.replace(/USDT$/i, "");

type SnapshotBalance = VenueContext["snapshot"]["balances"][number];

export const validateDecision = async (input: {
  decision: TradingDecision;
  runtimeConfig: RuntimeConfig;
  venueContext: VenueContext;
}) => {
  const issues: string[] = [];
  const normalizedOrders = [];
  const rulesEnabled = input.runtimeConfig.execution.enabled;
  const effectiveMaxOrders = rulesEnabled ? input.runtimeConfig.execution.maxOrdersPerRun : input.decision.orders.length;
  const balances = new Map<string, SnapshotBalance>(
    input.venueContext.snapshot.balances.map((balance: SnapshotBalance) => [
      balance.asset.toUpperCase(),
      balance
    ])
  );

  if (rulesEnabled && input.decision.orders.length > input.runtimeConfig.execution.maxOrdersPerRun) {
    issues.push("Decision exceeds maxOrdersPerRun");
  }

  for (const order of input.decision.orders.slice(0, effectiveMaxOrders)) {
    try {
      if (rulesEnabled && order.type === "market" && !input.runtimeConfig.execution.allowMarketOrders) {
        throw new Error("Runtime config disallows market orders");
      }

      if (rulesEnabled && order.type === "limit" && !input.runtimeConfig.execution.allowLimitOrders) {
        throw new Error("Runtime config disallows limit orders");
      }

      const normalized = await validateTradability(input.runtimeConfig, order, input.venueContext);
      const referencePrice =
        input.venueContext.priceMap[normalized.symbol] ?? normalized.limitPrice ?? null;

      if (normalized.side === "buy") {
        if (!normalized.stopLossPrice || !normalized.takeProfitPrice) {
          throw new Error(`Buy order for ${normalized.symbol} must include both stopLossPrice and takeProfitPrice`);
        }

        if (referencePrice) {
          if (normalized.stopLossPrice >= referencePrice) {
            throw new Error(`stopLossPrice (${normalized.stopLossPrice}) must be below current price (${referencePrice}) for ${normalized.symbol}`);
          }
          if (normalized.takeProfitPrice <= referencePrice) {
            throw new Error(`takeProfitPrice (${normalized.takeProfitPrice}) must be above current price (${referencePrice}) for ${normalized.symbol}`);
          }
        }

        const cash = balances.get("USDT");
        const cashAvailable = rulesEnabled
          ? (cash?.free ?? 0) - input.runtimeConfig.execution.minCashReserveUsd
          : cash?.free ?? 0;
        const requiredUsd = referencePrice ? normalized.quantity * referencePrice : Infinity;

        if (requiredUsd > cashAvailable) {
          throw new Error(`Insufficient USDT for ${normalized.symbol}`);
        }
      }

      if (normalized.side === "sell") {
        const baseAsset = getBaseAsset(normalized.symbol);
        const balance = balances.get(baseAsset);
        if (!balance || balance.free < normalized.quantity) {
          throw new Error(`Insufficient ${baseAsset} balance to sell ${normalized.symbol}`);
        }
      }

      normalizedOrders.push(normalized);
    } catch (error) {
      issues.push(error instanceof Error ? error.message : "Unknown validation error");
    }
  }

  return validationResultSchema.parse({
    accepted: issues.length === 0,
    issues,
    normalizedOrders
  });
};
