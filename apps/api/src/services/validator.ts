/**
 * Cosmu v2 Deterministic Validator
 *
 * Non-LLM validation of trading decisions. Checks:
 * 1. Venue authorization
 * 2. Authorized pairs (if symbol scope is "selected")
 * 3. Budget limits
 * 4. Balance sufficiency
 * 5. Tradability (symbol rules, lot sizes, min notional)
 * 6. SL/TP enforcement for buys
 * 7. Order count / notional limits
 */

import { validationResultSchema, type RuntimeConfig, type TradingDecision } from "@cosmu/shared";
import { isUsdcOnlyVenue, validateTradability, type VenueContext } from "../adapters/binance.js";

const getBaseAsset = (symbol: string) => symbol.replace(/USD[TC]$/i, "");

// Always-on safety buffer for buys: market slippage, taker fees, and rounding all
// drain real cash beyond the validator's predicted spend. Without this, runs with
// `execution.enabled=false` (the default) burn straight through `budgetUsdt` and
// leave bots with negative logical balance once fills + fees settle.
// 1.5% covers Binance taker fee (0.1%) + a generous slippage allowance for thin pairs.
const SAFETY_BUFFER_PCT = 0.015;
// Floor on the minimum cash reserve: even when the user has not enabled execution
// rules, we keep at least $1 of headroom so successive runs cannot zero the account.
const FALLBACK_MIN_CASH_RESERVE_USD = 1;

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

  // ── 1. Venue authorization ───────────────────────────────────────
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

        // 4. Budget check — pad by SAFETY_BUFFER_PCT so fees + slippage cannot
        // push the realized spend over `budgetUsdt` after fills settle.
        const baseUsd = referencePrice ? normalized.quantity * referencePrice : Infinity;
        const requiredUsd = Number.isFinite(baseUsd) ? baseUsd * (1 + SAFETY_BUFFER_PCT) : baseUsd;
        if (spentUsd + requiredUsd > budget) {
          throw new Error(`Buy ${normalized.symbol} ($${requiredUsd.toFixed(2)} incl. buffer) would exceed bot budget of $${budget} (already spent $${spentUsd.toFixed(2)})`);
        }

        // 5. Balance sufficiency.
        // - Cash pool: USDC-only on live binance (no USDT pairs in FR), combined USDT+USDC elsewhere.
        // - Reserve: always enforce a minimum (rules enabled → user value, else FALLBACK_MIN_CASH_RESERVE_USD).
        //   Without an always-on reserve, runs with `execution.enabled=false` could spend the wallet
        //   to zero and end up negative once fees post (the bug in production).
        // - `spentUsd` accumulates buffered amounts so back-to-back buys in one run cannot
        //   each see the full snapshot cash (bot #57 regression).
        const usdcOnly = isUsdcOnlyVenue(input.runtimeConfig);
        const cashFree = usdcOnly
          ? balances.get("USDC")?.free ?? 0
          : (balances.get("USDT")?.free ?? 0) + (balances.get("USDC")?.free ?? 0);
        const reserve = rulesEnabled
          ? Math.max(input.runtimeConfig.execution.minCashReserveUsd, FALLBACK_MIN_CASH_RESERVE_USD)
          : FALLBACK_MIN_CASH_RESERVE_USD;
        const cashAvailable = cashFree - reserve;
        if (spentUsd + requiredUsd > cashAvailable) {
          const cashLabel = usdcOnly ? "USDC" : "USDT/USDC";
          throw new Error(
            `Insufficient ${cashLabel} cash for ${normalized.symbol} (have $${cashAvailable.toFixed(2)} after $${reserve.toFixed(2)} reserve, already queued $${spentUsd.toFixed(2)}, need $${requiredUsd.toFixed(2)})`
          );
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
