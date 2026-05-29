// module: Resolve research ideas into venue-executable instruments without bloating prompts.
import {
  tradabilityRequestSchema,
  type TradabilityRequest,
  type TradabilityResult
} from "@cosmu/shared";
import { isBinanceVenue, lookupBinanceSymbols, netForVenue } from "../adapters/binance.js";

const normalizeInput = (value: string) => value.replace(/[^A-Z0-9.:-]/gi, "").toUpperCase();

const unsupported = (input: TradabilityRequest, explanation: string): TradabilityResult => ({
  assetOrSymbol: input.assetOrSymbol,
  venue: input.venue,
  assetClass: input.assetClass,
  executable: false,
  reason: "venue_not_supported",
  symbol: null,
  instrumentId: null,
  quoteAsset: null,
  currentPrice: null,
  minNotional: null,
  orderTypes: [],
  explanation,
  alternatives: []
});

export const resolveTradability = async (rawInput: unknown): Promise<TradabilityResult> => {
  const input = tradabilityRequestSchema.parse(rawInput);
  const assetOrSymbol = normalizeInput(input.assetOrSymbol);

  if (!assetOrSymbol) {
    return {
      ...unsupported(input, "No asset or symbol was provided."),
      reason: "no_pair"
    };
  }

  if (!isBinanceVenue(input.venue)) {
    return unsupported(
      input,
      `${input.venue} is prepared in the venue model, but execution is not enabled yet. IBKR needs account/session, contract resolution, market-hours, and paper-order validation before it can trade.`
    );
  }

  if (input.assetClass !== "spot") {
    return unsupported(input, `Asset class ${input.assetClass} is not supported by the Binance spot adapter.`);
  }

  const lookup = await lookupBinanceSymbols(netForVenue(input.venue), [assetOrSymbol]);
  const entry = lookup[assetOrSymbol] ?? Object.values(lookup)[0];

  if (!entry || !entry.tradable) {
    return {
      assetOrSymbol,
      venue: input.venue,
      assetClass: input.assetClass,
      executable: false,
      reason: "no_pair",
      symbol: null,
      instrumentId: null,
      quoteAsset: null,
      currentPrice: null,
      minNotional: null,
      orderTypes: [],
      explanation: entry?.reason ?? `No executable Binance spot pair found for ${assetOrSymbol}.`,
      alternatives: []
    };
  }

  return {
    assetOrSymbol,
    venue: input.venue,
    assetClass: input.assetClass,
    executable: true,
    reason: "tradable",
    symbol: entry.symbol,
    instrumentId: entry.symbol,
    quoteAsset: entry.quoteAsset,
    currentPrice: entry.currentPrice,
    minNotional: entry.minNotional,
    orderTypes: entry.orderTypes,
    explanation: `${entry.symbol} is executable on ${input.venue}. Use this canonical symbol if trading.`,
    alternatives: []
  };
};

export const resolveTradabilityBatch = async (items: unknown[]) =>
  Promise.all(items.slice(0, 25).map((item) => resolveTradability(item)));
