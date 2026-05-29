// module: Drawdown computation and guard helpers.
import type { RuntimeConfig } from "@cosmu/shared";

export const getMaxDrawdownLimitUsd = (runtimeConfig: RuntimeConfig) =>
  runtimeConfig.budgetUsdt * (1 - runtimeConfig.execution.maxDrawdownPct / 100);

export const isMaxDrawdownBreached = (runtimeConfig: RuntimeConfig, totalUsdValue: number) =>
  runtimeConfig.execution.maxDrawdownEnabled
  && Number.isFinite(totalUsdValue)
  && totalUsdValue <= getMaxDrawdownLimitUsd(runtimeConfig);

export const describeMaxDrawdownBreach = (runtimeConfig: RuntimeConfig, totalUsdValue: number) => {
  const limit = getMaxDrawdownLimitUsd(runtimeConfig);
  return `portfolio $${totalUsdValue.toFixed(2)} is at or below $${limit.toFixed(2)} (${runtimeConfig.execution.maxDrawdownPct}% max drawdown from $${runtimeConfig.budgetUsdt.toFixed(2)})`;
};
