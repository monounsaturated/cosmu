/**
 * Cosmu v2 Deterministic Validator
 *
 * Non-LLM validation of trading decisions. Checks:
 * 1. Global kill switch
 * 2. Venue authorization
 * 3. Authorized pairs (if symbol scope is "selected")
 * 4. Budget limits
 * 5. Balance sufficiency
 * 6. Tradability (symbol rules, lot sizes, min notional)
 * 7. SL/TP enforcement for buys
 * 8. Order count / notional limits
 */

import { validationResultSchema, type RuntimeConfig, type TradingDecision } from "@cosmu/shared";
import { validateTradability, type VenueContext } from "../adapters/binance.js";
import { isGlobalKillSwitchOn } from "../lib/store/settings.js";

const getBaseAsset = (symbol: string) => symbol.replace(/USD[TC]$/i, "");

type SnapshotBalance = VenueContext["snapshot"]["balances"][number];

export const validateDecision = async (input: {
  decision: TradingDecision;
  runtimeConfig: RuntimeConfig;
  venueContext: VenueContext;
}) => {
  const issues: string[] = [];
  const droppedOrders: string[] = [];
  const normalizedOrders = [];
  const rulesEnabled = input.runtimeConfig.execution.enabled;
  const effectiveMaxOrders = rulesEnabled ? input.runtimeConfig.execution.maxOrdersPerRun : input.decision.orders.length;

  // ── 1. Global kill switch ────────────────────────────────────────
  const killSwitchOn = await isGlobalKillSwitchOn();
  if (killSwitchOn) {
    return validationResultSchema.parse({
      accepted: false,
      issues: ["Global kill switch is ON — all executions are blocked"],
      normalizedOrders: []
    });
  }

  // ── 2. Venue authorization ───────────────────────────────────────
  // Bot venue must be a recognized venue
  const validVenues = ["binance", "binance-testnet"];
  if (!validVenues.includes(input.runtimeConfig.venue)) {
    return validationResultSchema.parse({
      accepted: false,
      issues: [`Venue "${input.runtimeConfig.venue}" is not authorized`],
      normalizedOrders: []
    });
  }

  // ── 3-8. Per-order validation ────────────────────────────────────
  const balances = new Map<string, SnapshotBalance>(
    input.venueContext.snapshot.balances.map((balance: SnapshotBalance) => [
      balance.asset.toUpperCase(),
      balance
    ])
  );

  const budget = input.runtimeConfig.budgetUsdt;
  let spentUsd = 0;

  // Authorized pairs check
  const authorizedPairs = input.runtimeConfig.symbolScope === "selected" && input.runtimeConfig.contextSymbols.length > 0
    ? new Set(input.runtimeConfig.contextSymbols.map(s => s.toUpperCase()))
    : null;

  if (rulesEnabled && input.decision.orders.length > input.runtimeConfig.execution.maxOrdersPerRun) {
    droppedOrders.push(
      `Truncated ${input.decision.orders.length - input.runtimeConfig.execution.maxOrdersPerRun} order(s) exceeding maxOrdersPerRun`
    );
  }

  for (const order of input.decision.orders.slice(0, effectiveMaxOrders)) {
    try {
      // 3. Authorized pairs
      if (authorizedPairs && !authorizedPairs.has(order.symbol.toUpperCase())) {
        throw new Error(`Symbol ${order.symbol} is not in the authorized pairs list`);
      }

      // Order type checks
      if (rulesEnabled && order.type === "market" && !input.runtimeConfig.execution.allowMarketOrders) {
        throw new Error("Runtime config disallows market orders");
      }
      if (rulesEnabled && order.type === "limit" && !input.runtimeConfig.execution.allowLimitOrders) {
        throw new Error("Runtime config disallows limit orders");
      }

      // 6. Tradability (symbol rules, lot sizes, min notional, max notional)
      const normalized = await validateTradability(input.runtimeConfig, order, input.venueContext);
      const referencePrice =
        input.venueContext.priceMap[normalized.symbol] ?? normalized.limitPrice ?? null;

      if (normalized.side === "buy") {
        // 7. SL/TP enforcement
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

        // 4. Budget check
        const requiredUsd = referencePrice ? normalized.quantity * referencePrice : Infinity;
        if (spentUsd + requiredUsd > budget) {
          throw new Error(`Buy ${normalized.symbol} ($${requiredUsd.toFixed(2)}) would exceed bot budget of $${budget} (already spent $${spentUsd.toFixed(2)})`);
        }

        // 5. Balance sufficiency — combined USDT + USDC (peg-guarded swap happens at execution)
        const cashFree =
          (balances.get("USDT")?.free ?? 0) + (balances.get("USDC")?.free ?? 0);
        const cashAvailable = rulesEnabled
          ? cashFree - input.runtimeConfig.execution.minCashReserveUsd
          : cashFree;
        if (requiredUsd > cashAvailable) {
          throw new Error(`Insufficient USDT/USDC cash for ${normalized.symbol}`);
        }

        spentUsd += requiredUsd;
      }

      if (normalized.side === "sell") {
        if (normalized.stopLossPrice !== null || normalized.takeProfitPrice !== null) {
          throw new Error(`Sell order for ${normalized.symbol} must set stopLossPrice/takeProfitPrice to null`);
        }
        const baseAsset = getBaseAsset(normalized.symbol);
        const balance = balances.get(baseAsset);
        if (!balance || balance.free < normalized.quantity) {
          throw new Error(`Insufficient ${baseAsset} balance to sell ${normalized.symbol}`);
        }
      }

      normalizedOrders.push(normalized);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown validation error";
      droppedOrders.push(`Dropped ${order.symbol} ${order.side}: ${message}`);
    }
  }

  return validationResultSchema.parse({
    accepted: issues.length === 0,
    issues: [...issues, ...droppedOrders],
    normalizedOrders
  });
};
