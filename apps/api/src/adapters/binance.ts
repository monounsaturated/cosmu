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
  // `ocoAllowed` (Binance exchangeInfo flag) tells us whether we can attach
  // a post-buy OCO SELL for SL/TP. Some symbols (esp. newer meme/leveraged
  // pairs) lack it — we must refuse buys on those since the NON_NEGOTIABLE
  // contract says every buy gets SL/TP protection.
  ocoAllowed: boolean;
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

const accountPermissionsCache = new Map<RuntimeConfig["mode"], { expiresAt: number; perms: Set<string> }>();

const getAccountPermissions = async (mode: RuntimeConfig["mode"]): Promise<Set<string>> => {
  const cached = accountPermissionsCache.get(mode);
  if (cached && cached.expiresAt > Date.now()) return cached.perms;
  try {
    const acct = await getAccount(mode);
    const perms = new Set<string>(
      Array.isArray(acct?.permissions) ? acct.permissions.filter((p: unknown) => typeof p === "string") : []
    );
    // Binance omits SPOT when permissions is non-empty for some regional accounts, but canTrade
    // implies spot access — add SPOT so baseline pairs (no TRD_GRP_* restriction) still pass.
    if (acct?.canTrade) perms.add("SPOT");
    accountPermissionsCache.set(mode, { expiresAt: Date.now() + 10 * 60 * 1000, perms });
    return perms;
  } catch (err) {
    console.warn(`[binance] getAccountPermissions(${mode}) failed:`, err instanceof Error ? err.message : err);
    return new Set<string>();
  }
};

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

const getBaseUrl = (mode: RuntimeConfig["mode"]) => (mode === "live" ? LIVE_BASE_URL : TESTNET_BASE_URL);

const getApiKey = (mode: RuntimeConfig["mode"]) => {
  if (mode === "testnet" && env.BINANCE_TESTNET_API_KEY) {
    return env.BINANCE_TESTNET_API_KEY;
  }
  if (env.BINANCE_API_KEY) return env.BINANCE_API_KEY;
  throw new Error(`${mode === "testnet" ? "BINANCE_TESTNET_API_KEY or " : ""}BINANCE_API_KEY is not configured`);
};

const getApiSecret = (mode: RuntimeConfig["mode"]) => {
  if (mode === "testnet" && env.BINANCE_TESTNET_API_SECRET) {
    return env.BINANCE_TESTNET_API_SECRET;
  }
  if (env.BINANCE_API_SECRET) return env.BINANCE_API_SECRET;
  throw new Error(`${mode === "testnet" ? "BINANCE_TESTNET_API_SECRET or " : ""}BINANCE_API_SECRET is not configured`);
};

const signParams = (params: URLSearchParams, mode: RuntimeConfig["mode"]) =>
  crypto.createHmac("sha256", getApiSecret(mode)).update(params.toString()).digest("hex");

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
    finalParams.set("signature", signParams(finalParams, mode));
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
  headers.set("X-MBX-APIKEY", getApiKey(mode));

  let body: string | undefined;
  if (signed && init?.body && typeof init.body === "string") {
    const params = new URLSearchParams(init.body);
    params.set("timestamp", Date.now().toString());
    params.set("recvWindow", "5000");
    params.set("signature", signParams(params, mode));
    body = params.toString();
  } else if (typeof init?.body === "string") {
    body = init.body;
  }

  for (let attempt = 0; attempt < 3; attempt += 1) {
    const response = await fetch(url, {
      ...init,
      headers,
      body,
      signal: AbortSignal.timeout(8000)
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

export const normalizeSymbol = (value: string) => value.replace(/[^A-Z0-9]/gi, "").toUpperCase();

const toNumber = (value: string | number | undefined, fallback = 0) =>
  value === undefined ? fallback : Number(value);

export const roundToStep = (value: number, step: number) => {
  if (!Number.isFinite(step) || step <= 0) {
    return value;
  }

  const precision = step.toString().includes(".") ? step.toString().split(".")[1]!.length : 0;
  const rounded = Math.floor(value / step) * step;
  return Number(rounded.toFixed(precision));
};

export const roundToTick = (value: number, tickSize: number) => {
  if (!Number.isFinite(tickSize) || tickSize <= 0) return value;
  const precision = tickSize.toString().includes(".") ? tickSize.toString().split(".")[1]!.length : 0;
  const rounded = Math.round(value / tickSize) * tickSize;
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
    ocoAllowed: Boolean(exchangeInfo.ocoAllowed ?? exchangeInfo.otoAllowed ?? false),
    stepSize: toNumber(lotSize?.stepSize, 0.000001),
    minQty: toNumber(lotSize?.minQty, 0),
    minNotional: toNumber(minNotional?.minNotional, 0),
    tickSize: toNumber(priceFilter?.tickSize, 0.000001)
  };
};

const STABLE_QUOTES = ["USDT", "USDC"] as const;
type StableQuote = (typeof STABLE_QUOTES)[number];

const isStableQuote = (asset: string): asset is StableQuote =>
  (STABLE_QUOTES as readonly string[]).includes(asset);

// Binance France (live) no longer offers USDT pairs — restrict to USDC only.
// Testnet keeps both quotes since dev/sim flows still need USDT pairs.
// Other venues (when added) keep dual-stable behavior.
export const isUsdcOnlyVenue = (cfg: { venue: RuntimeConfig["venue"]; mode: RuntimeConfig["mode"] }) =>
  cfg.venue === "binance" && cfg.mode === "live";

const allowedStableQuotesFor = (cfg: {
  venue: RuntimeConfig["venue"];
  mode: RuntimeConfig["mode"];
}): readonly StableQuote[] => (isUsdcOnlyVenue(cfg) ? ["USDC"] : STABLE_QUOTES);

// Binance intersection rule: account can trade a symbol iff `accountPermissions`
// has at least one permission in common with at least one `permissionSets` subArray.
// When `accountPermissions` is undefined, skip the check (public calls, testnet baseline).
const accountCanTrade = (exchangeSymbol: any, accountPermissions?: Set<string>) => {
  if (!accountPermissions) return true;
  const sets: unknown = exchangeSymbol?.permissionSets;
  if (!Array.isArray(sets) || sets.length === 0) return true;
  for (const set of sets) {
    if (!Array.isArray(set)) continue;
    for (const perm of set) {
      if (typeof perm === "string" && accountPermissions.has(perm)) return true;
    }
  }
  return false;
};

const isTradableSpotStableSymbol = (exchangeSymbol: any, accountPermissions?: Set<string>) =>
  exchangeSymbol?.symbol &&
  exchangeSymbol?.status === "TRADING" &&
  exchangeSymbol?.isSpotTradingAllowed !== false &&
  typeof exchangeSymbol?.quoteAsset === "string" &&
  isStableQuote(exchangeSymbol.quoteAsset) &&
  accountCanTrade(exchangeSymbol, accountPermissions);

// Kept as an alias for any call sites that still expect USDT-only semantics.
// Prefer `isTradableSpotStableSymbol` for new code.
const isTradableSpotUsdtSymbol = isTradableSpotStableSymbol;

const splitBaseAndQuote = (symbol: string): { base: string; quote: StableQuote | null } => {
  const normalized = normalizeSymbol(symbol);
  for (const quote of STABLE_QUOTES) {
    if (normalized.endsWith(quote) && normalized.length > quote.length) {
      return { base: normalized.slice(0, -quote.length), quote };
    }
  }
  return { base: normalized, quote: null };
};

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

export const getAccountBalance = async (mode: RuntimeConfig["mode"]) => {
  const account = await getAccount(mode);
  const balances = (account.balances ?? [])
    .filter((b: { free: string; locked: string }) => Number(b.free) > 0 || Number(b.locked) > 0)
    .map((b: { asset: string; free: string; locked: string }) => ({
      asset: b.asset,
      free: Number(b.free),
      locked: Number(b.locked)
    }));
  const usdt = balances.find((b: { asset: string }) => b.asset === "USDT");
  const usdc = balances.find((b: { asset: string }) => b.asset === "USDC");
  const freeUsdt = usdt?.free ?? 0;
  const lockedUsdt = usdt?.locked ?? 0;
  const freeUsdc = usdc?.free ?? 0;
  const lockedUsdc = usdc?.locked ?? 0;
  return {
    // Cash is USDT + USDC at 1:1 (display as dollars — actual peg guard happens at swap time)
    totalFreeUsdt: freeUsdt + freeUsdc,
    totalLockedUsdt: lockedUsdt + lockedUsdc,
    freeUsdt,
    lockedUsdt,
    freeUsdc,
    lockedUsdc,
    balances
  };
};

export const getAllTickerPrices = (mode: RuntimeConfig["mode"]) =>
  binanceFetch(mode, "/v3/ticker/price", { method: "GET" });

const getTickerPrice = (mode: RuntimeConfig["mode"], symbol: string) =>
  binanceFetch(mode, `/v3/ticker/price?symbol=${encodeURIComponent(symbol)}`, { method: "GET" });

export const getTickerPricesForSymbols = async (
  mode: RuntimeConfig["mode"],
  symbolsInput: string[]
): Promise<Record<string, number>> => {
  const symbols = Array.from(new Set(symbolsInput.map(normalizeSymbol).filter(Boolean)));
  if (symbols.length === 0) return {};
  const encoded = encodeURIComponent(JSON.stringify(symbols));
  const data = (await binanceFetch(mode, `/v3/ticker/price?symbols=${encoded}`, { method: "GET" })) as
    | Array<{ symbol: string; price: string }>
    | { symbol: string; price: string };
  const arr = Array.isArray(data) ? data : [data];
  const out: Record<string, number> = {};
  for (const t of arr) out[normalizeSymbol(String(t.symbol ?? ""))] = Number(t.price);
  return out;
};

const getAllExchangeInfo = (mode: RuntimeConfig["mode"]) =>
  binanceFetch(mode, "/v3/exchangeInfo", { method: "GET" });

export const cancelAllOpenOrdersForSymbol = async (
  mode: RuntimeConfig["mode"],
  symbolInput: string
) => {
  const symbol = normalizeSymbol(symbolInput);
  const params = new URLSearchParams({
    symbol,
    timestamp: Date.now().toString(),
    recvWindow: "5000"
  });
  params.set("signature", signParams(params, mode));

  const response = await fetch(`${getBaseUrl(mode)}/v3/openOrders?${params.toString()}`, {
    method: "DELETE",
    headers: {
      "X-MBX-APIKEY": getApiKey(mode)
    }
  });

  if (!response.ok) {
    const text = await response.text();
    let code: number | undefined;
    try {
      code = JSON.parse(text)?.code;
    } catch {
      // ignore
    }
    // Invalid symbol — nothing to cancel.
    if (response.status === 400 && code === -1121) {
      return [];
    }
    // No matching open orders (Binance returns this when there is nothing to cancel).
    if (response.status === 400 && code === -2011) {
      return [];
    }
    throw new Error(`Binance cancel open orders failed for ${symbol}: ${response.status} ${text}`);
  }

  return response.json();
};

export type SymbolLookupEntry =
  | {
      tradable: true;
      symbol: string;
      quoteAsset: StableQuote;
      currentPrice: number | null;
      minQty: number;
      minNotional: number;
      tickSize: number;
      stepSize: number;
      orderTypes: string[];
    }
  | {
      tradable: false;
      currentPrice: null;
      reason: string;
    };

/**
 * Targeted lookup: for a small set of base tickers, return the best tradable stable-quoted
 * spot pair on Binance (USDT preferred, USDC fallback). Input can be a bare base ("NEIRO"),
 * a USDT pair ("NEIROUSDT"), or a USDC pair ("NEIROUSDC") — the query key in the returned
 * record always matches the caller's input verbatim (after normalization).
 * Does NOT fetch account data. Cheap to call mid-agent-loop.
 */
export const lookupBinanceSymbols = async (
  mode: RuntimeConfig["mode"],
  rawSymbols: string[]
): Promise<Record<string, SymbolLookupEntry>> => {
  const queries = rawSymbols
    .map((s) => normalizeSymbol(String(s ?? "")))
    .filter((s) => s.length > 0 && s !== "USDTUSDT" && s !== "USDCUSDC");

  const uniqueQueries = Array.from(new Set(queries));
  if (uniqueQueries.length === 0) return {};

  // Candidate pairs to probe: respect venue-allowed quotes (USDC-only on live binance).
  const allowedQuotes = allowedStableQuotesFor({ venue: "binance", mode });
  const candidatePairs = new Set<string>();
  for (const q of uniqueQueries) {
    const { base } = splitBaseAndQuote(q);
    if (!base) continue;
    for (const quote of allowedQuotes) {
      candidatePairs.add(`${base}${quote}`);
    }
  }

  // In testnet mode, we ALSO fetch live exchangeInfo and intersect: testnet
  // has a broader / different symbol universe than live, so a testnet run can
  // pick symbols that don't exist on live Binance (e.g., TAOUSDT exists on
  // testnet but only TAOUSDC on live in some regions). Intersecting means
  // testnet sims mirror what live would allow.
  const needLiveCheck = mode === "testnet";
  const [exchangeInfoResponse, tickerPrices, liveExchangeInfo, accountPerms, livePerms] = await Promise.all([
    getAllExchangeInfo(mode),
    getAllTickerPrices(mode),
    needLiveCheck ? getAllExchangeInfo("live") : Promise.resolve(null),
    getAccountPermissions(mode),
    needLiveCheck ? getAccountPermissions("live") : Promise.resolve(null)
  ]);

  // For testnet: use LIVE account permissions when intersecting with live exchangeInfo
  // (the goal is to mirror what the user could actually trade on live).
  const livePermsForIntersect = livePerms ?? undefined;
  const liveTradable = new Set<string>();
  if (liveExchangeInfo) {
    for (const raw of liveExchangeInfo.symbols ?? []) {
      if (!isTradableSpotStableSymbol(raw, livePermsForIntersect)) continue;
      liveTradable.add(normalizeSymbol(String(raw.symbol ?? "")));
    }
  }

  const permsForMode = mode === "live" ? accountPerms : undefined;
  const rulesMap: Record<string, SymbolRules> = {};
  for (const raw of exchangeInfoResponse.symbols ?? []) {
    const sym = normalizeSymbol(String(raw.symbol ?? ""));
    if (!candidatePairs.has(sym)) continue;
    if (!isTradableSpotStableSymbol(raw, permsForMode)) continue;
    if (needLiveCheck && !liveTradable.has(sym)) continue;
    rulesMap[sym] = parseSymbolRules(raw);
  }

  const priceMap: Record<string, number> = {};
  for (const p of (Array.isArray(tickerPrices) ? tickerPrices : []) as Array<{
    symbol: string;
    price: string;
  }>) {
    const sym = normalizeSymbol(String(p.symbol ?? ""));
    if (candidatePairs.has(sym)) priceMap[sym] = Number(p.price);
  }

  const out: Record<string, SymbolLookupEntry> = {};
  for (const q of uniqueQueries) {
    const { base, quote: requestedQuote } = splitBaseAndQuote(q);
    if (!base) {
      out[q] = {
        tradable: false,
        currentPrice: null,
        reason: `Could not parse ticker: ${q}`
      };
      continue;
    }

    // Probe order: requested quote first (if it's allowed for this venue), then
    // venue-allowed defaults. Binance live = USDC only; testnet keeps both.
    const probeOrder: StableQuote[] = [];
    if (requestedQuote && allowedQuotes.includes(requestedQuote)) {
      probeOrder.push(requestedQuote);
    }
    for (const q2 of allowedQuotes) {
      if (!probeOrder.includes(q2)) probeOrder.push(q2);
    }

    let chosen: { quote: StableQuote; rules: SymbolRules } | null = null;
    for (const quote of probeOrder) {
      const sym = `${base}${quote}`;
      const rules = rulesMap[sym];
      if (rules && rules.status === "TRADING") {
        chosen = { quote, rules };
        break;
      }
    }

    if (!chosen) {
      const allowedLabel = allowedQuotes.map((qq) => `${base}/${qq}`).join(" or ");
      out[q] = {
        tradable: false,
        currentPrice: null,
        reason: `No tradable ${allowedLabel} spot pair found on Binance`
      };
      continue;
    }

    const canonicalSymbol = `${base}${chosen.quote}`;
    out[q] = {
      tradable: true,
      symbol: canonicalSymbol,
      quoteAsset: chosen.quote,
      currentPrice: priceMap[canonicalSymbol] ?? null,
      minQty: chosen.rules.minQty,
      minNotional: chosen.rules.minNotional,
      tickSize: chosen.rules.tickSize,
      stepSize: chosen.rules.stepSize,
      orderTypes: chosen.rules.orderTypes
    };
  }
  return out;
};

export const listVenueSymbols = async () => {
  if (venueSymbolsCache && venueSymbolsCache.expiresAt > Date.now()) {
    return venueSymbolsCache.symbols;
  }

  const response = await requestPublicJson("/v3/exchangeInfo");
  const symbols = (response.symbols ?? [])
    .filter(isTradableSpotStableSymbol)
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
  const balances = (rawAccountResponse.balances ?? []).filter((balance: any) => {
    const asset = String(balance.asset ?? "").trim();
    if (!asset) {
      return false;
    }
    return Number(balance.free) > 0 || Number(balance.locked) > 0;
  });

  // For each non-stable balance asset, include venue-allowed stable pairs as candidates; the
  // one that resolves to a live price will be used for USD valuation.
  const allowedQuotes = allowedStableQuotesFor(runtimeConfig);
  const usdcOnly = isUsdcOnlyVenue(runtimeConfig);
  const balanceSymbols = balances
    .flatMap((balance: any) => {
      const asset = String(balance.asset ?? "").trim().toUpperCase();
      if (!asset || isStableQuote(asset)) return [];
      return allowedQuotes.map((q) => `${asset}${q}`);
    });
  const selectedSymbols = contextSymbols
    .map(normalizeSymbol)
    .filter((symbol) => {
      if (symbol === ALL_SYMBOLS_TOKEN || symbol === "USDTUSDT" || symbol === "USDCUSDC") return false;
      // Drop any selection on a quote we don't allow for this venue.
      const { quote } = splitBaseAndQuote(symbol);
      if (quote && !allowedQuotes.includes(quote)) return false;
      return true;
    });

  const exchangeInfoResponse = await getAllExchangeInfo(runtimeConfig.mode);
  const exchangeSymbols = exchangeInfoResponse.symbols ?? [];
  // Re-use the account permissions already implied by `rawAccountResponse` to
  // filter exchangeInfo to what this account can actually trade.
  const accountPerms = new Set<string>(
    Array.isArray(rawAccountResponse?.permissions)
      ? rawAccountResponse.permissions.filter((p: unknown) => typeof p === "string")
      : []
  );
  if (rawAccountResponse?.canTrade) accountPerms.add("SPOT");
  const allTradableSpotSymbols = exchangeSymbols
    .filter((sym: any) => {
      if (!isTradableSpotStableSymbol(sym, accountPerms)) return false;
      const quote = String(sym.quoteAsset ?? "").toUpperCase();
      return allowedQuotes.includes(quote as StableQuote);
    })
    .map((symbol: any) => normalizeSymbol(symbol.symbol));

  // USDCUSDT is the peg-swap pair — only useful when both stables are allowed.
  const pegSymbols = usdcOnly ? [] : ["USDCUSDT"];
  const derivedSymbols = new Set(
    runtimeConfig.symbolScope === "all"
      ? [...allTradableSpotSymbols, ...balanceSymbols, ...pegSymbols]
      : [...balanceSymbols, ...selectedSymbols, ...pegSymbols]
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
    const asset = String(balance.asset ?? "").trim().toUpperCase();
    const usdPrice = isStableQuote(asset)
      ? 1
      : priceMap[`${asset}USDT`] ?? priceMap[`${asset}USDC`] ?? null;
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

  // Per-order notional cap is part of "execution rules" in the UI; when rules are off,
  // still enforce exchange minNotional above, but do not cap at maxNotionalPerOrderUsd.
  if (
    runtimeConfig.execution.enabled &&
    notional > runtimeConfig.execution.maxNotionalPerOrderUsd
  ) {
    throw new Error(`Notional ${notional} exceeds runtime maxNotionalPerOrderUsd`);
  }

  return {
    ...order,
    symbol,
    quantity,
    limitPrice: order.limitPrice ? roundToStep(order.limitPrice, rules.tickSize) : null,
    stopLossPrice: order.stopLossPrice ? roundToTick(order.stopLossPrice, rules.tickSize) : null,
    takeProfitPrice: order.takeProfitPrice ? roundToTick(order.takeProfitPrice, rules.tickSize) : null
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
  if (isStableQuote(normalizedAsset)) {
    return 1;
  }

  const cachedUsdt = venueContext.priceMap[`${normalizedAsset}USDT`];
  if (cachedUsdt) return cachedUsdt;
  const cachedUsdc = venueContext.priceMap[`${normalizedAsset}USDC`];
  if (cachedUsdc) return cachedUsdc;

  for (const quote of STABLE_QUOTES) {
    try {
      const ticker = await getTickerPrice(mode, `${normalizedAsset}${quote}`);
      const usdPrice = Number(ticker.price);
      if (Number.isFinite(usdPrice) && usdPrice > 0) return usdPrice;
    } catch {
      // try next quote
    }
  }

  return null;
};

const PEG_GUARD_PCT = 0.2;

/**
 * Ensures the account has enough of `quoteAsset` to cover `requiredQuoteAmount` for an
 * upcoming order on `<BASE><quoteAsset>`. If short, market-swaps the other stablecoin via
 * USDCUSDT — but only if the pair's price is within PEG_GUARD_PCT of 1:1.
 * Never swaps USDT → USDC unless the target order explicitly requires USDC (and vice versa).
 * No-op (returns null) when no swap is needed or when the peg guard trips.
 */
const ensureStableQuoteLiquidity = async (input: {
  mode: RuntimeConfig["mode"];
  quoteAsset: StableQuote;
  requiredQuoteAmount: number;
  venueContext: VenueContext;
}): Promise<{ swapped: boolean; reason?: string; rawResponse?: unknown }> => {
  const { mode, quoteAsset, requiredQuoteAmount, venueContext } = input;
  const getFree = (asset: string) => {
    const balance = venueContext.snapshot.balances.find(
      (b) => b.asset.toUpperCase() === asset
    );
    return balance ? Number(balance.free) : 0;
  };

  const haveTarget = getFree(quoteAsset);
  if (haveTarget >= requiredQuoteAmount) {
    return { swapped: false, reason: "sufficient" };
  }

  const otherAsset: StableQuote = quoteAsset === "USDT" ? "USDC" : "USDT";
  const haveOther = getFree(otherAsset);
  const shortfall = requiredQuoteAmount - haveTarget;
  if (haveOther < shortfall) {
    return { swapped: false, reason: "insufficient_combined" };
  }

  // USDCUSDT: price ≈ 1 (USDC in USDT). Peg guard: abort if > PEG_GUARD_PCT off.
  const pegSymbol = "USDCUSDT";
  const pegPrice =
    venueContext.priceMap[pegSymbol] ??
    Number((await getTickerPrice(mode, pegSymbol)).price ?? NaN);
  if (!Number.isFinite(pegPrice) || pegPrice <= 0) {
    return { swapped: false, reason: "peg_price_unavailable" };
  }
  const deviationPct = Math.abs(pegPrice - 1) * 100;
  if (deviationPct > PEG_GUARD_PCT) {
    return { swapped: false, reason: `peg_deviation_${deviationPct.toFixed(2)}pct` };
  }

  const pegRules = venueContext.symbolRules[pegSymbol] ?? null;

  // Direction: need USDC → buy USDC with USDT on USDCUSDT. Need USDT → sell USDC on USDCUSDT.
  const side: "BUY" | "SELL" = quoteAsset === "USDC" ? "BUY" : "SELL";

  const params = new URLSearchParams({
    symbol: pegSymbol,
    side,
    type: "MARKET",
    newOrderRespType: "FULL"
  });

  if (side === "BUY") {
    // quoteOrderQty spends exactly this much USDT to buy USDC.
    const spend = shortfall; // 1:1 with small spread; we buy slightly less USDC than shortfall
    params.set("quoteOrderQty", spend.toFixed(2));
  } else {
    // Sell exactly `shortfall` USDC for USDT.
    const qty = pegRules ? roundToStep(shortfall, pegRules.stepSize) : Number(shortfall.toFixed(6));
    if (pegRules && qty < pegRules.minQty) {
      return { swapped: false, reason: `below_min_qty_${pegRules.minQty}` };
    }
    params.set("quantity", qty.toString());
  }

  try {
    const rawResponse = await binanceFetch(
      mode,
      "/v3/order",
      {
        method: "POST",
        headers: { "content-type": "application/x-www-form-urlencoded" },
        body: params.toString()
      },
      true
    );
    console.log(
      `[binance] stablecoin swap ${side} USDCUSDT (shortfall=${shortfall.toFixed(2)} ${quoteAsset}, peg=${pegPrice.toFixed(4)})`
    );
    return { swapped: true, rawResponse };
  } catch (error) {
    return {
      swapped: false,
      reason: `swap_failed:${error instanceof Error ? error.message : "unknown"}`
    };
  }
};

/**
 * Place a single STOP_LOSS order on Binance that acts as a "disaster stop" —
 * a wider safety net than the app-managed SL. The guardian loop normally fires
 * first and cancels this order; the stop only triggers if the app is down or
 * delayed past the safety threshold. Works on any spot symbol (no OCO support
 * required).
 */
export const placeSafetyStopOrder = async (input: {
  mode: RuntimeConfig["mode"];
  symbol: string;
  quantity: number;
  stopPrice: number;
  clientOrderId: string;
  orderTypes?: string[];
  tickSize?: number;
}): Promise<{ orderId: string; rawResponse: unknown; type: "STOP_LOSS" | "STOP_LOSS_LIMIT" }> => {
  // Binance spot: STOP_LOSS (market-on-trigger) is NOT supported on most pairs —
  // exchangeInfo.orderTypes for a typical symbol usually lists STOP_LOSS_LIMIT
  // but not STOP_LOSS. Prefer STOP_LOSS when allowed, fall back to STOP_LOSS_LIMIT
  // with a limit price 0.5% below stopPrice so it almost always fills.
  const supportsStopLoss = input.orderTypes?.includes("STOP_LOSS") ?? false;
  const supportsStopLossLimit = input.orderTypes?.includes("STOP_LOSS_LIMIT") ?? true;

  const useMarket = supportsStopLoss;
  if (!useMarket && !supportsStopLossLimit) {
    throw new Error(`Symbol ${input.symbol} supports neither STOP_LOSS nor STOP_LOSS_LIMIT`);
  }

  const orderType: "STOP_LOSS" | "STOP_LOSS_LIMIT" = useMarket ? "STOP_LOSS" : "STOP_LOSS_LIMIT";

  const params = new URLSearchParams({
    symbol: input.symbol,
    side: "SELL",
    type: orderType,
    quantity: input.quantity.toString(),
    stopPrice: input.stopPrice.toString(),
    newClientOrderId: input.clientOrderId.slice(0, 36),
    newOrderRespType: "RESULT"
  });

  if (orderType === "STOP_LOSS_LIMIT") {
    // Place the limit slightly below stopPrice so it fills immediately on trigger.
    const limitRaw = input.stopPrice * 0.995;
    const limitPrice = input.tickSize ? roundToTick(limitRaw, input.tickSize) : limitRaw;
    params.set("price", limitPrice.toString());
    params.set("timeInForce", "GTC");
  }

  const rawResponse = await binanceFetch(
    input.mode,
    "/v3/order",
    {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: params.toString()
    },
    true
  );

  return {
    orderId: String(rawResponse.orderId ?? ""),
    rawResponse,
    type: orderType
  };
};

export const cancelSafetyStopOrder = async (
  mode: RuntimeConfig["mode"],
  symbol: string,
  orderId: string
): Promise<"cancelled" | "not_found"> => {
  const params = new URLSearchParams({
    symbol: normalizeSymbol(symbol),
    orderId,
    timestamp: Date.now().toString(),
    recvWindow: "5000"
  });
  params.set("signature", signParams(params, mode));

  const response = await fetch(`${getBaseUrl(mode)}/v3/order?${params.toString()}`, {
    method: "DELETE",
    headers: { "X-MBX-APIKEY": getApiKey(mode) }
  });

  if (response.ok) return "cancelled";

  const text = await response.text();
  let code: number | undefined;
  try {
    code = JSON.parse(text)?.code;
  } catch {
    /* ignore */
  }
  // -2011: unknown order (already filled/cancelled/never existed) — treat as "not there".
  if (response.status === 400 && code === -2011) return "not_found";
  throw new Error(`Binance cancel order failed for ${symbol}/${orderId}: ${response.status} ${text}`);
};

export const getBinanceOrderStatus = async (
  mode: RuntimeConfig["mode"],
  symbol: string,
  orderId: string
): Promise<{
  status: string;
  executedQty: number;
  avgPrice: number | null;
  fills: unknown[];
  raw: any;
} | null> => {
  const params = new URLSearchParams({
    symbol: normalizeSymbol(symbol),
    orderId,
    timestamp: Date.now().toString(),
    recvWindow: "5000"
  });
  params.set("signature", signParams(params, mode));

  const response = await fetch(`${getBaseUrl(mode)}/v3/order?${params.toString()}`, {
    method: "GET",
    headers: { "X-MBX-APIKEY": getApiKey(mode) }
  });

  if (!response.ok) {
    const text = await response.text();
    let code: number | undefined;
    try {
      code = JSON.parse(text)?.code;
    } catch {
      /* ignore */
    }
    if (response.status === 400 && code === -2013) return null; // order does not exist
    throw new Error(`Binance getOrder failed for ${symbol}/${orderId}: ${response.status} ${text}`);
  }

  const raw = await response.json();
  const executedQty = Number(raw.executedQty ?? 0);
  const cumQuote = Number(raw.cummulativeQuoteQty ?? 0);
  return {
    status: String(raw.status ?? ""),
    executedQty,
    avgPrice: executedQty > 0 ? cumQuote / executedQty : null,
    fills: raw.fills ?? [],
    raw
  };
};

/**
 * Fire a MARKET SELL for the given qty and return an ExecutionRecord.
 * Used by the guardian loop (SL/TP fire) and kill-bot fallback paths that
 * bypass the main `executeOrders` flow.
 */
export const placeMarketSell = async (input: {
  mode: RuntimeConfig["mode"];
  venue: RuntimeConfig["venue"];
  assetClass: RuntimeConfig["assetClass"];
  symbol: string;
  quantity: number;
  clientOrderIdPrefix: string;
  stopLossPrice: number | null;
  takeProfitPrice: number | null;
}): Promise<ExecutionRecord> => {
  const symbol = normalizeSymbol(input.symbol);
  const params = new URLSearchParams({
    symbol,
    side: "SELL",
    type: "MARKET",
    quantity: input.quantity.toString(),
    newClientOrderId: `${input.clientOrderIdPrefix}-${Date.now().toString(36)}`.slice(0, 36),
    newOrderRespType: "FULL"
  });

  try {
    const rawVenueResponse = await binanceFetch(
      input.mode,
      "/v3/order",
      {
        method: "POST",
        headers: { "content-type": "application/x-www-form-urlencoded" },
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
    const executedQuantity = Number(rawVenueResponse.executedQty ?? input.quantity);
    const executedNotionalUsd =
      averageFillPrice === null ? null : Number((executedQuantity * averageFillPrice).toFixed(8));

    return executionRecordSchema.parse({
      assetClass: input.assetClass,
      venue: input.venue,
      status: "success",
      symbol,
      side: "sell",
      orderType: "market",
      requestedQuantity: input.quantity,
      executedQuantity,
      requestedLimitPrice: null,
      averageFillPrice,
      executedNotionalUsd,
      feeAmount,
      feeAsset,
      feeAssetUsdPrice: null,
      feeUsd: null,
      slippagePct: null,
      stopLossPrice: input.stopLossPrice,
      takeProfitPrice: input.takeProfitPrice,
      ocoOrderId: null,
      orderIntent: {
        symbol,
        side: "sell",
        type: "market",
        quantity: input.quantity,
        limitPrice: null,
        stopLossPrice: null,
        takeProfitPrice: null,
        rationale: "Guardian-triggered market sell (SL/TP or safety)"
      },
      rawVenueResponse
    });
  } catch (error) {
    return executionRecordSchema.parse({
      assetClass: input.assetClass,
      venue: input.venue,
      status: "uncertain",
      symbol,
      side: "sell",
      orderType: "market",
      requestedQuantity: input.quantity,
      executedQuantity: null,
      requestedLimitPrice: null,
      averageFillPrice: null,
      executedNotionalUsd: null,
      feeAmount: null,
      feeAsset: null,
      feeAssetUsdPrice: null,
      feeUsd: null,
      slippagePct: null,
      stopLossPrice: input.stopLossPrice,
      takeProfitPrice: input.takeProfitPrice,
      ocoOrderId: null,
      orderIntent: {
        symbol,
        side: "sell",
        type: "market",
        quantity: input.quantity,
        limitPrice: null,
        stopLossPrice: null,
        takeProfitPrice: null,
        rationale: "Guardian-triggered market sell (SL/TP or safety)"
      },
      rawVenueResponse: {
        error: error instanceof Error ? error.message : "Unknown Binance market sell error"
      }
    });
  }
};

const buildExecutionRecord = (input: {
  runtimeConfig: RuntimeConfig;
  order: OrderIntent & { symbol: string; quantity: number; limitPrice: number | null; stopLossPrice: number | null; takeProfitPrice: number | null };
  rawVenueResponse: any;
}): ExecutionRecord => {
  const fills = input.rawVenueResponse.fills ?? [];
  const feeAmount = fills.reduce((sum: number, fill: any) => sum + Number(fill.commission ?? 0), 0);
  const feeAsset = fills[0]?.commissionAsset ?? null;
  const averageFillPrice =
    fills.length > 0
      ? fills.reduce((sum: number, fill: any) => sum + Number(fill.price) * Number(fill.qty), 0) /
        fills.reduce((sum: number, fill: any) => sum + Number(fill.qty), 0)
      : input.rawVenueResponse.price
        ? Number(input.rawVenueResponse.price)
        : null;
  const executedQuantity = Number(input.rawVenueResponse.executedQty ?? input.order.quantity);
  const executedNotionalUsd =
    averageFillPrice === null ? null : Number((executedQuantity * averageFillPrice).toFixed(8));

  return executionRecordSchema.parse({
    assetClass: input.runtimeConfig.assetClass,
    venue: input.runtimeConfig.venue,
    status: "success",
    symbol: input.order.symbol,
    side: input.order.side,
    orderType: input.order.type,
    requestedQuantity: input.order.quantity,
    executedQuantity,
    requestedLimitPrice: input.order.limitPrice,
    averageFillPrice,
    executedNotionalUsd,
    feeAmount,
    feeAsset,
    feeAssetUsdPrice: null,
    feeUsd: null,
    slippagePct: null,
    stopLossPrice: input.order.stopLossPrice,
    takeProfitPrice: input.order.takeProfitPrice,
    ocoOrderId: null,
    orderIntent: input.order,
    rawVenueResponse: input.rawVenueResponse
  });
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

    // Pre-trade liquidity check: peg-swap between USDT and USDC when both are tradable
    // on this venue. Disabled on Binance live (USDC-only — no USDT pairs to swap into).
    if (order.side === "buy" && !isUsdcOnlyVenue(input.runtimeConfig)) {
      const { quote: orderQuote } = splitBaseAndQuote(order.symbol);
      if (orderQuote) {
        const priceForSizing = input.venueContext.priceMap[order.symbol] ?? order.limitPrice ?? 0;
        const requiredQuote = order.quantity * priceForSizing;
        if (requiredQuote > 0) {
          await ensureStableQuoteLiquidity({
            mode: input.runtimeConfig.mode,
            quoteAsset: orderQuote,
            requiredQuoteAmount: requiredQuote * 1.001,
            venueContext: input.venueContext
          });
        }
      }
    }

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
          headers: { "content-type": "application/x-www-form-urlencoded" },
          body: params.toString()
        },
        true
      );

      // SL/TP are now enforced in-app by the guardian loop and protected by a
      // separate Binance "safety stop" placed post-fill in run-bot.ts (so the
      // execution adapter stays purely about placing the primary order).
      const record = buildExecutionRecord({
        runtimeConfig: input.runtimeConfig,
        order,
        rawVenueResponse
      });

      const feeAssetUsdPrice = await getUsdPriceForAsset(input.runtimeConfig.mode, record.feeAsset, input.venueContext);
      const feeUsd =
        record.feeAmount && feeAssetUsdPrice !== null
          ? Number((record.feeAmount * feeAssetUsdPrice).toFixed(8))
          : record.feeAmount === 0 ? 0 : null;
      const benchmarkPrice = input.venueContext.priceMap[order.symbol] ?? order.limitPrice ?? null;
      const slippagePct =
        benchmarkPrice && record.averageFillPrice
          ? ((record.averageFillPrice - benchmarkPrice) / benchmarkPrice) * 100
          : null;

      executions.push(
        executionRecordSchema.parse({
          ...record,
          feeAssetUsdPrice,
          feeUsd,
          slippagePct
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
          stopLossPrice: order.stopLossPrice,
          takeProfitPrice: order.takeProfitPrice,
          ocoOrderId: null,
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
