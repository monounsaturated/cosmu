import { portfolioSnapshotSchema, type RuntimeConfig } from "@cosmu/shared";
import { isUsdcOnlyVenue } from "../adapters/binance.js";
import type { BotExecutionLedgerEntry } from "./store.js";

export type LogicalBalances = {
  // Combined USDT + USDC cash (1:1). Displayed as dollars.
  usdt: number;
  assets: Record<string, number>;
};

const STABLE_SUFFIXES = ["USDT", "USDC"] as const;
const STABLE_ASSETS = new Set<string>(["USDT", "USDC"]);

export const baseAssetFromSymbol = (symbol: string) => {
  const up = symbol.trim().toUpperCase();
  for (const suffix of STABLE_SUFFIXES) {
    if (up.endsWith(suffix) && up.length > suffix.length) {
      return up.slice(0, -suffix.length);
    }
  }
  return up.length > 0 ? up : null;
};

export const computeLogicalBalances = (
  budgetUsdt: number,
  ledger: BotExecutionLedgerEntry[]
): LogicalBalances => {
  const balances: LogicalBalances = { usdt: budgetUsdt, assets: {} };

  for (const execution of ledger) {
    const quantity = execution.executedQuantity ?? 0;
    const notionalUsd = execution.executedNotionalUsd ?? 0;
    const feeAmount = execution.feeAmount ?? 0;
    const feeAsset = execution.feeAsset?.toUpperCase() ?? null;
    const baseAsset = baseAssetFromSymbol(execution.symbol);
    if (!baseAsset || STABLE_ASSETS.has(baseAsset)) continue;

    if (!(baseAsset in balances.assets)) {
      balances.assets[baseAsset] = 0;
    }

    if (execution.side === "buy") {
      balances.assets[baseAsset] += quantity;
      balances.usdt -= notionalUsd;
    } else {
      balances.assets[baseAsset] -= quantity;
      balances.usdt += notionalUsd;
    }

    if (feeAmount > 0 && feeAsset) {
      if (STABLE_ASSETS.has(feeAsset)) {
        balances.usdt -= feeAmount;
      } else {
        balances.assets[feeAsset] = (balances.assets[feeAsset] ?? 0) - feeAmount;
      }
    }
  }

  return balances;
};

// Returns held-coin pairs the trader can re-price against. For each held base asset,
// include venue-allowed quote variants so the pricing loader can resolve them.
export const getHeldSymbols = (logical: LogicalBalances, runtimeConfig?: RuntimeConfig) => {
  const usdcOnly = runtimeConfig ? isUsdcOnlyVenue(runtimeConfig) : false;
  const quotes = usdcOnly ? ["USDC"] : ["USDT", "USDC"];
  return Object.entries(logical.assets)
    .filter(([asset, qty]) => asset.length > 0 && Math.abs(qty) > 1e-8)
    .flatMap(([asset]) => quotes.map((q) => `${asset}${q}`));
};

export const buildLogicalSnapshot = (input: {
  runtimeConfig: RuntimeConfig;
  logical: LogicalBalances;
  priceMap: Record<string, number>;
}) => {
  // Cash label: the logical layer carries combined stable-cash under `usdt`, but on
  // venues where USDT isn't tradable (binance live = USDC-only) labelling it "USDT"
  // makes the validator look for USDT free-balance and underflow. Use the actual
  // tradable stable for those venues.
  const cashAsset = isUsdcOnlyVenue(input.runtimeConfig) ? "USDC" : "USDT";
  const balances = [
    {
      asset: cashAsset,
      free: input.logical.usdt,
      locked: 0,
      usdValue: input.logical.usdt
    },
    ...Object.entries(input.logical.assets)
      .filter(([, qty]) => Math.abs(qty) > 1e-8)
      .map(([asset, quantity]) => {
        const price =
          input.priceMap[`${asset}USDT`] ?? input.priceMap[`${asset}USDC`] ?? null;
        return {
          asset,
          free: quantity,
          locked: 0,
          usdValue: price ? quantity * price : null
        };
      })
  ];

  const totalUsdValue = balances.reduce((sum, balance) => sum + (balance.usdValue ?? 0), 0);

  return portfolioSnapshotSchema.parse({
    assetClass: input.runtimeConfig.assetClass,
    totalUsdValue,
    grossPnlUsd: null,
    netPnlUsd: null,
    feeUsd: null,
    balances,
    prices: Object.entries(input.priceMap).map(([symbol, price]) => ({ symbol, price })),
    capturedAt: new Date().toISOString()
  });
};

export const computeAfterSnapshot = (input: {
  beforeSnapshot: { totalUsdValue: number };
  afterSnapshot: ReturnType<typeof buildLogicalSnapshot>;
  totalFeeUsd: number;
}) => ({
  ...input.afterSnapshot,
  grossPnlUsd: input.afterSnapshot.totalUsdValue - input.beforeSnapshot.totalUsdValue,
  netPnlUsd: input.afterSnapshot.totalUsdValue - input.beforeSnapshot.totalUsdValue - input.totalFeeUsd,
  feeUsd: input.totalFeeUsd
});
