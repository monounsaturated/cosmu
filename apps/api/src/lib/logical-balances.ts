import { portfolioSnapshotSchema, type RuntimeConfig } from "@cosmu/shared";
import type { BotExecutionLedgerEntry } from "./store.js";

export type LogicalBalances = {
  usdt: number;
  assets: Record<string, number>;
};

export const baseAssetFromSymbol = (symbol: string) => {
  const base = symbol.replace(/USDT$/i, "").trim().toUpperCase();
  return base.length > 0 ? base : null;
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
    if (!baseAsset) continue;

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
      if (feeAsset === "USDT") {
        balances.usdt -= feeAmount;
      } else {
        balances.assets[feeAsset] = (balances.assets[feeAsset] ?? 0) - feeAmount;
      }
    }
  }

  return balances;
};

export const getHeldSymbols = (logical: LogicalBalances) =>
  Object.entries(logical.assets)
    .filter(([asset, qty]) => asset.length > 0 && Math.abs(qty) > 1e-8)
    .map(([asset]) => `${asset}USDT`);

export const buildLogicalSnapshot = (input: {
  runtimeConfig: RuntimeConfig;
  logical: LogicalBalances;
  priceMap: Record<string, number>;
}) => {
  const balances = [
    {
      asset: "USDT",
      free: input.logical.usdt,
      locked: 0,
      usdValue: input.logical.usdt
    },
    ...Object.entries(input.logical.assets)
      .filter(([, qty]) => Math.abs(qty) > 1e-8)
      .map(([asset, quantity]) => {
        const price = input.priceMap[`${asset}USDT`];
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
