import crypto from "node:crypto";
import {
  ALL_SYMBOLS_TOKEN,
  executionRecordSchema,
  portfolioSnapshotSchema,
  type ExecutionRecord,
  type OrderIntent,
  type PortfolioSnapshot,
  type RuntimeConfig
} from "@cosmu/shared";
import { env } from "../env.js";

const LIVE_BASE_URL = "https://api.binance.com/api";
const TESTNET_BASE_URL = "https://testnet.binance.vision/api";

type SymbolRules = {
  symbol: string;
  status: string;
  orderTypes: string[];
  stepSize: number;
  minQty: number;
  minNotional: number;
  tickSize: number;
};

export type VenueContext = {
  snapshot: PortfolioSnapshot;
  priceMap: Record<string, number>;
  symbolRules: Record<string, SymbolRules>;
  rawAccountResponse: unknown;
};

let venueSymbolsCache: { expiresAt: number; symbols: string[] } | null = null;

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const getBaseUrl = (mode: RuntimeConfig["mode"]) => (mode === "live" ? LIVE_BASE_URL : TESTNET_BASE_URL);

const signParams = (params: URLSearchParams) =>
  crypto.createHmac("sha256", env.BINANCE_API_SECRET).update(params.toString()).digest("hex");

const requestWithQuery = async (
  mode: RuntimeConfig["mode"],
  path: string,
  params: URLSearchParams,
  signed: boolean
) => {
  const finalParams = new URLSearchParams(params);
  if (signed) {
    finalParams.set("timestamp", Date.now().toString());
    finalParams.set("recvWindow", "5000");
    finalParams.set("signature", signParams(finalParams));
  }

  const suffix = finalParams.toString();
  return binanceFetch(mode, `${path}${suffix ? `?${suffix}` : ""}`, { method: "GET" });
};

const binanceFetch = async (
  mode: RuntimeConfig["mode"],
  path: string,
  init?: RequestInit,
  signed?: boolean
) => {
  const url = new URL(`${getBaseUrl(mode)}${path}`);
  const headers = new Headers(init?.headers);
  headers.set("X-MBX-APIKEY", env.BINANCE_API_KEY);

  let body: string | undefined;
  if (signed && init?.body && typeof init.body === "string") {
    const params = new URLSearchParams(init.body);
    params.set("timestamp", Date.now().toString());
    params.set("recvWindow", "5000");
    params.set("signature", signParams(params));
    body = params.toString();
  } else if (typeof init?.body === "string") {
    body = init.body;
  }

  for (let attempt = 0; attempt < 3; attempt += 1) {
    const response = await fetch(url, {
      ...init,
      headers,
      body
    });

    if (response.status !== 429) {
      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Binance ${path} failed: ${response.status} ${errorText}`);
      }

      return response.json();
    }

    await wait(500 * 2 ** attempt);
  }

  throw new Error(`Binance ${path} exceeded retry budget`);
};

const normalizeSymbol = (value: string) => value.replace(/[^A-Z0-9]/gi, "").toUpperCase();

const toNumber = (value: string | number | undefined, fallback = 0) =>
  value === undefined ? fallback : Number(value);

const roundToStep = (value: number, step: number) => {
  if (!Number.isFinite(step) || step <= 0) {
    return value;
  }

  const precision = step.toString().includes(".") ? step.toString().split(".")[1]!.length : 0;
  const rounded = Math.floor(value / step) * step;
  return Number(rounded.toFixed(precision));
};

const parseSymbolRules = (exchangeInfo: any): SymbolRules => {
  const lotSize = exchangeInfo.filters.find((filter: any) => filter.filterType === "LOT_SIZE");
  const minNotional = exchangeInfo.filters.find((filter: any) => filter.filterType === "MIN_NOTIONAL");
  const priceFilter = exchangeInfo.filters.find((filter: any) => filter.filterType === "PRICE_FILTER");

  return {
    symbol: exchangeInfo.symbol,
    status: exchangeInfo.status,
    orderTypes: exchangeInfo.orderTypes ?? [],
    stepSize: toNumber(lotSize?.stepSize, 0.000001),
    minQty: toNumber(lotSize?.minQty, 0),
    minNotional: toNumber(minNotional?.minNotional, 0),
    tickSize: toNumber(priceFilter?.tickSize, 0.000001)
  };
};

const isTradableSpotUsdtSymbol = (exchangeSymbol: any) =>
  exchangeSymbol?.symbol &&
  exchangeSymbol?.status === "TRADING" &&
  exchangeSymbol?.isSpotTradingAllowed !== false &&
  exchangeSymbol?.quoteAsset === "USDT";

const requestPublicJson = async (path: string) => {
  const response = await fetch(`${LIVE_BASE_URL}${path}`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Binance public ${path} failed: ${response.status} ${errorText}`);
  }

  return response.json();
};

const getAccount = (mode: RuntimeConfig["mode"]) =>
  requestWithQuery(mode, "/v3/account", new URLSearchParams(), true);

const getAllTickerPrices = (mode: RuntimeConfig["mode"]) =>
  binanceFetch(mode, "/v3/ticker/price", {
    method: "GET"
  });

const getTickerPrice = (mode: RuntimeConfig["mode"], symbol: string) =>
  binanceFetch(mode, `/v3/ticker/price?symbol=${encodeURIComponent(symbol)}`, {
    method: "GET"
  });

const getAllExchangeInfo = (mode: RuntimeConfig["mode"]) =>
  binanceFetch(mode, "/v3/exchangeInfo", {
    method: "GET"
  });

export const listVenueSymbols = async () => {
  if (venueSymbolsCache && venueSymbolsCache.expiresAt > Date.now()) {
    return venueSymbolsCache.symbols;
  }

  const response = await requestPublicJson("/v3/exchangeInfo");
  const symbols = (response.symbols ?? [])
    .filter(isTradableSpotUsdtSymbol)
    .map((symbol: any) => normalizeSymbol(symbol.symbol))
    .sort((left: string, right: string) => left.localeCompare(right));

  venueSymbolsCache = {
    expiresAt: Date.now() + 24 * 60 * 60 * 1000,
    symbols
  };

  return symbols;
};

export const loadVenueContext = async (
  runtimeConfig: RuntimeConfig,
  contextSymbols: string[]
): Promise<VenueContext> => {
  const rawAccountResponse = await getAccount(runtimeConfig.mode);
  const balances = (rawAccountResponse.balances ?? []).filter(
    (balance: any) => Number(balance.free) > 0 || Number(balance.locked) > 0
  );

  const balanceSymbols = balances
    .map((balance: any) => normalizeSymbol(`${balance.asset}USDT`))
    .filter((symbol: string) => symbol !== "USDTUSDT");
  const selectedSymbols = contextSymbols
    .map(normalizeSymbol)
    .filter((symbol) => symbol !== ALL_SYMBOLS_TOKEN && symbol !== "USDTUSDT");

  const exchangeInfoResponse = await getAllExchangeInfo(runtimeConfig.mode);
  const exchangeSymbols = exchangeInfoResponse.symbols ?? [];
  const allTradableSpotSymbols = exchangeSymbols
    .filter(isTradableSpotUsdtSymbol)
    .map((symbol: any) => normalizeSymbol(symbol.symbol));

  const derivedSymbols = new Set(
    runtimeConfig.symbolScope === "all"
      ? [...allTradableSpotSymbols, ...balanceSymbols]
      : [...balanceSymbols, ...selectedSymbols]
  );

  const allPrices = await getAllTickerPrices(runtimeConfig.mode);
  const priceMap = Object.fromEntries(
    (Array.isArray(allPrices) ? allPrices : [])
      .filter((price: any) => derivedSymbols.has(normalizeSymbol(price.symbol)))
      .map((price: any) => [normalizeSymbol(price.symbol), Number(price.price)])
  );

  const symbolRules = Object.fromEntries(
    exchangeSymbols
      .filter((symbol: any) => derivedSymbols.has(normalizeSymbol(symbol.symbol)))
      .map((symbol: any) => [normalizeSymbol(symbol.symbol), parseSymbolRules(symbol)])
  );

  const normalizedBalances = balances.map((balance: any) => {
    const asset = balance.asset;
    const quoteSymbol = normalizeSymbol(`${asset}USDT`);
    const usdPrice = asset === "USDT" ? 1 : priceMap[quoteSymbol] ?? null;
    const total = Number(balance.free) + Number(balance.locked);

    return {
      asset,
      free: Number(balance.free),
      locked: Number(balance.locked),
      usdValue: usdPrice === null ? null : total * usdPrice
    };
  });

  const totalUsdValue = normalizedBalances.reduce(
    (sum: number, balance: { usdValue: number | null }) => sum + (balance.usdValue ?? 0),
    0
  );

  return {
    rawAccountResponse,
    priceMap,
    symbolRules,
    snapshot: portfolioSnapshotSchema.parse({
      assetClass: runtimeConfig.assetClass,
      totalUsdValue,
      grossPnlUsd: null,
      netPnlUsd: null,
      feeUsd: null,
      balances: normalizedBalances,
      prices: Object.entries(priceMap).map(([symbol, price]) => ({ symbol, price })),
      capturedAt: new Date().toISOString()
    })
  };
};

export const validateTradability = async (
  runtimeConfig: RuntimeConfig,
  order: OrderIntent,
  venueContext: VenueContext
) => {
  const symbol = normalizeSymbol(order.symbol);
  const rules = venueContext.symbolRules[symbol] ?? null;

  if (!rules) {
    throw new Error(`Symbol ${symbol} is not tradable on Binance spot right now`);
  }

  if (rules.status !== "TRADING") {
    throw new Error(`Symbol ${symbol} is not in TRADING status`);
  }

  const normalizedType = order.type.toUpperCase();
  if (!rules.orderTypes.includes(normalizedType)) {
    throw new Error(`Order type ${normalizedType} is not allowed for ${symbol}`);
  }

  const quantity = roundToStep(order.quantity, rules.stepSize);
  if (quantity < rules.minQty) {
    throw new Error(`Quantity ${quantity} is below minQty for ${symbol}`);
  }

  const markPrice = venueContext.priceMap[symbol] ?? order.limitPrice ?? 0;
  const notional = quantity * markPrice;
  if (notional < rules.minNotional) {
    throw new Error(`Notional ${notional} is below minNotional for ${symbol}`);
  }

  if (notional > runtimeConfig.execution.maxNotionalPerOrderUsd) {
    throw new Error(`Notional ${notional} exceeds runtime maxNotionalPerOrderUsd`);
  }

  return {
    ...order,
    symbol,
    quantity,
    limitPrice: order.limitPrice ? roundToStep(order.limitPrice, rules.tickSize) : null
  };
};

const getUsdPriceForAsset = async (
  mode: RuntimeConfig["mode"],
  asset: string | null,
  venueContext: VenueContext
) => {
  if (!asset) {
    return null;
  }

  const normalizedAsset = normalizeSymbol(asset);
  if (normalizedAsset === "USDT") {
    return 1;
  }

  const cachedPrice = venueContext.priceMap[`${normalizedAsset}USDT`];
  if (cachedPrice) {
    return cachedPrice;
  }

  try {
    const ticker = await getTickerPrice(mode, `${normalizedAsset}USDT`);
    const usdPrice = Number(ticker.price);
    if (Number.isFinite(usdPrice) && usdPrice > 0) {
      return usdPrice;
    }
  } catch {
    return null;
  }

  return null;
};

export const executeOrders = async (input: {
  runId: string;
  runtimeConfig: RuntimeConfig;
  orders: OrderIntent[];
  venueContext: VenueContext;
}): Promise<ExecutionRecord[]> => {
  const executions: ExecutionRecord[] = [];

  for (const [index, rawOrder] of input.orders.entries()) {
    const order = await validateTradability(input.runtimeConfig, rawOrder, input.venueContext);

    const params = new URLSearchParams({
      symbol: order.symbol,
      side: order.side.toUpperCase(),
      type: order.type.toUpperCase(),
      quantity: order.quantity.toString(),
      newClientOrderId: `${input.runId.replace(/-/g, "").slice(0, 20)}-${index + 1}`,
      newOrderRespType: "FULL"
    });

    if (order.type === "limit") {
      if (!order.limitPrice) {
        throw new Error(`Limit order for ${order.symbol} is missing limitPrice`);
      }

      params.set("price", order.limitPrice.toString());
      params.set("timeInForce", "GTC");
    }

    try {
      const rawVenueResponse = await binanceFetch(
        input.runtimeConfig.mode,
        "/v3/order",
        {
          method: "POST",
          headers: {
            "content-type": "application/x-www-form-urlencoded"
          },
          body: params.toString()
        },
        true
      );

      const fills = rawVenueResponse.fills ?? [];
      const feeAmount = fills.reduce((sum: number, fill: any) => sum + Number(fill.commission ?? 0), 0);
      const feeAsset = fills[0]?.commissionAsset ?? null;
      const averageFillPrice =
        fills.length > 0
          ? fills.reduce((sum: number, fill: any) => sum + Number(fill.price) * Number(fill.qty), 0) /
            fills.reduce((sum: number, fill: any) => sum + Number(fill.qty), 0)
          : rawVenueResponse.price
            ? Number(rawVenueResponse.price)
            : null;
      const benchmarkPrice = input.venueContext.priceMap[order.symbol] ?? order.limitPrice ?? null;
      const slippagePct =
        benchmarkPrice && averageFillPrice
          ? ((averageFillPrice - benchmarkPrice) / benchmarkPrice) * 100
          : null;
      const executedQuantity = Number(rawVenueResponse.executedQty ?? order.quantity);
      const executedNotionalUsd =
        averageFillPrice === null ? null : Number((executedQuantity * averageFillPrice).toFixed(8));
      const feeAssetUsdPrice = await getUsdPriceForAsset(input.runtimeConfig.mode, feeAsset, input.venueContext);
      const feeUsd =
        feeAmount && feeAssetUsdPrice !== null ? Number((feeAmount * feeAssetUsdPrice).toFixed(8)) : feeAmount === 0 ? 0 : null;

      executions.push(
        executionRecordSchema.parse({
          assetClass: input.runtimeConfig.assetClass,
          venue: input.runtimeConfig.venue,
          status: "success",
          symbol: order.symbol,
          side: order.side,
          orderType: order.type,
          requestedQuantity: order.quantity,
          executedQuantity,
          requestedLimitPrice: order.limitPrice,
          averageFillPrice,
          executedNotionalUsd,
          feeAmount,
          feeAsset,
          feeAssetUsdPrice,
          feeUsd,
          slippagePct,
          orderIntent: order,
          rawVenueResponse
        })
      );
    } catch (error) {
      executions.push(
        executionRecordSchema.parse({
          assetClass: input.runtimeConfig.assetClass,
          venue: input.runtimeConfig.venue,
          status: "uncertain",
          symbol: order.symbol,
          side: order.side,
          orderType: order.type,
          requestedQuantity: order.quantity,
          executedQuantity: null,
          requestedLimitPrice: order.limitPrice,
          averageFillPrice: null,
          executedNotionalUsd: null,
          feeAmount: null,
          feeAsset: null,
          feeAssetUsdPrice: null,
          feeUsd: null,
          slippagePct: null,
          orderIntent: order,
          rawVenueResponse: {
            error: error instanceof Error ? error.message : "Unknown Binance execution error"
          }
        })
      );
    }
  }

  return executions;
};
