import type { RuntimeConfig } from "@cosmu/shared";
import { getAccountBalance, getAllTickerPrices } from "../adapters/binance.js";

type MarketMode = RuntimeConfig["mode"];
type TickerPrice = { symbol: string; price: string | number };
type AccountBalance = Awaited<ReturnType<typeof getAccountBalance>>;
type MarketDataTrigger = "startup" | "interval" | "manual" | "dashboard";

type CacheEntry<T> = {
  value: T | null;
  updatedAt: string | null;
  checkedAt: string | null;
  error: string | null;
  refreshing: boolean;
};

type ModeSnapshot = {
  prices: TickerPrice[];
  balance: AccountBalance | null;
  pricesUpdatedAt: string | null;
  balanceUpdatedAt: string | null;
  pricesError: string | null;
  balanceError: string | null;
  stale: boolean;
};

export const MARKET_DATA_REFRESH_INTERVAL_MS = 60 * 1000;
const MARKET_DATA_STALE_AFTER_MS = 5 * MARKET_DATA_REFRESH_INTERVAL_MS;
const MARKET_DATA_REQUEST_TIMEOUT_MS = 5000;

const makeEntry = <T>(): CacheEntry<T> => ({
  value: null,
  updatedAt: null,
  checkedAt: null,
  error: null,
  refreshing: false
});

const pricesCache: Record<MarketMode, CacheEntry<TickerPrice[]>> = {
  live: makeEntry<TickerPrice[]>(),
  testnet: makeEntry<TickerPrice[]>()
};

const balanceCache: Record<MarketMode, CacheEntry<AccountBalance>> = {
  live: makeEntry<AccountBalance>(),
  testnet: makeEntry<AccountBalance>()
};

const describeError = (error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  const binanceCodeMatch = message.match(/"code":(-?\d+)/);
  const binanceMessageMatch = message.match(/"msg":"([^"]+)"/);
  if (binanceCodeMatch || binanceMessageMatch) {
    return `Binance ${binanceCodeMatch?.[1] ?? "error"}: ${binanceMessageMatch?.[1] ?? message}`;
  }
  return message
    .replace(/signature=[^&\s]+/g, "signature=[redacted]")
    .replace(/timestamp=\d+/g, "timestamp=[redacted]");
};

const withTimeout = async <T>(label: string, loader: Promise<T>) => {
  let timeout: NodeJS.Timeout | null = null;
  try {
    return await Promise.race([
      loader,
      new Promise<never>((_, reject) => {
        timeout = setTimeout(
          () => reject(new Error(`${label} timed out after ${MARKET_DATA_REQUEST_TIMEOUT_MS}ms`)),
          MARKET_DATA_REQUEST_TIMEOUT_MS
        );
      })
    ]);
  } finally {
    if (timeout) clearTimeout(timeout);
  }
};

const refreshEntry = async <T>(
  entry: CacheEntry<T>,
  label: string,
  loader: () => Promise<T>
) => {
  if (entry.refreshing) {
    return {
      label,
      skipped: true,
      reason: "already_refreshing",
      updatedAt: entry.updatedAt,
      error: entry.error
    };
  }

  entry.refreshing = true;
  try {
    entry.value = await withTimeout(label, loader());
    entry.checkedAt = new Date().toISOString();
    entry.updatedAt = entry.checkedAt;
    entry.error = null;
    return {
      label,
      skipped: false,
      updatedAt: entry.updatedAt,
      error: null
    };
  } catch (error) {
    entry.checkedAt = new Date().toISOString();
    entry.error = describeError(error);
    return {
      label,
      skipped: false,
      updatedAt: entry.updatedAt,
      error: entry.error
    };
  } finally {
    entry.refreshing = false;
  }
};

const lastAttemptAt = (entry: CacheEntry<unknown>) => entry.updatedAt ?? entry.checkedAt;

const entryIsStale = (entry: CacheEntry<unknown>) => {
  if (!entry.updatedAt) return true;
  return Date.now() - new Date(entry.updatedAt).getTime() > MARKET_DATA_STALE_AFTER_MS;
};

const entryNeedsRefresh = (entry: CacheEntry<unknown>) => {
  if (entry.refreshing) return false;
  const attemptedAt = lastAttemptAt(entry);
  if (!attemptedAt) return true;
  return Date.now() - new Date(attemptedAt).getTime() > MARKET_DATA_REFRESH_INTERVAL_MS;
};

export const refreshMarketDataSnapshot = async (trigger: MarketDataTrigger = "manual") => {
  const results = await Promise.all([
    refreshEntry(pricesCache.testnet, "testnet prices", async () => getAllTickerPrices("testnet") as Promise<TickerPrice[]>),
    refreshEntry(balanceCache.testnet, "testnet balance", () => getAccountBalance("testnet")),
    refreshEntry(pricesCache.live, "live prices", async () => getAllTickerPrices("live") as Promise<TickerPrice[]>),
    refreshEntry(balanceCache.live, "live balance", () => getAccountBalance("live"))
  ]);

  return {
    refreshedAt: new Date().toISOString(),
    trigger,
    results
  };
};

export const refreshMarketDataMode = async (
  mode: MarketMode,
  trigger: MarketDataTrigger = "manual"
) => {
  const results = await Promise.all([
    refreshEntry(pricesCache[mode], `${mode} prices`, async () => getAllTickerPrices(mode) as Promise<TickerPrice[]>),
    refreshEntry(balanceCache[mode], `${mode} balance`, () => getAccountBalance(mode))
  ]);

  return {
    refreshedAt: new Date().toISOString(),
    trigger,
    mode,
    results
  };
};

const buildModeSnapshot = (mode: MarketMode): ModeSnapshot => ({
  prices: pricesCache[mode].value ?? [],
  balance: balanceCache[mode].value,
  pricesUpdatedAt: pricesCache[mode].updatedAt,
  balanceUpdatedAt: balanceCache[mode].updatedAt,
  pricesError: pricesCache[mode].error,
  balanceError: balanceCache[mode].error,
  stale: entryIsStale(pricesCache[mode]) || entryIsStale(balanceCache[mode])
});

export const getCachedMarketDataSnapshot = (options: { autoRefresh?: boolean } = {}) => {
  const autoRefresh = options.autoRefresh ?? true;
  const needsRefresh =
    entryNeedsRefresh(pricesCache.testnet) ||
    entryNeedsRefresh(balanceCache.testnet) ||
    entryNeedsRefresh(pricesCache.live) ||
    entryNeedsRefresh(balanceCache.live);

  if (autoRefresh && needsRefresh) {
    void refreshMarketDataSnapshot("dashboard").catch((error) => {
      console.warn("[market-data-cache] dashboard refresh failed:", describeError(error));
    });
  }

  return {
    live: buildModeSnapshot("live"),
    testnet: buildModeSnapshot("testnet")
  };
};
