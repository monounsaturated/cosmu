// module: Yahoo Finance source — best-effort quotes/news for research, not execution.
import crypto from "node:crypto";
import { sourceFetchRequestSchema } from "@cosmu/shared";
import type { SourcePort } from "./types.js";

const hash = (value: string) => crypto.createHash("sha256").update(value).digest("hex");

const normalizeSymbol = (value: string) =>
  value.trim().toUpperCase().replace(/[^A-Z0-9.^=-]/g, "");

export const yahooFinanceSource: SourcePort = {
  definition: {
    key: "yahoo_finance",
    label: "Yahoo Finance",
    kind: "yahoo_finance",
    enabled: true,
    capabilities: ["quote", "historical_prices", "news"],
    description: "Best-effort public Yahoo Finance chart data for research/indexing. Not an execution-grade feed.",
    configHint: "No key required. Public endpoint availability can change."
  },
  fetch: async (rawRequest) => {
    const request = sourceFetchRequestSchema.parse(rawRequest);
    const symbol = normalizeSymbol(request.query);
    if (!symbol) return { observations: [], warning: "No symbol provided" };

    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?range=5d&interval=1d`;
    const response = await fetch(url, {
      headers: { "User-Agent": "cosmu-source-yahoo-finance" },
      signal: AbortSignal.timeout(10000)
    });
    if (!response.ok) {
      return { observations: [], warning: `Yahoo Finance responded ${response.status}` };
    }

    const raw = await response.json();
    const result = raw?.chart?.result?.[0];
    const quote = result?.indicators?.quote?.[0] ?? {};
    const timestamps = Array.isArray(result?.timestamp) ? result.timestamp : [];
    const closes = Array.isArray(quote.close) ? quote.close : [];
    const lastIndex = closes.map((v: unknown) => Number(v)).findLastIndex((v: number) => Number.isFinite(v));
    const lastClose = lastIndex >= 0 ? Number(closes[lastIndex]) : null;
    const observedAt = timestamps[lastIndex]
      ? new Date(Number(timestamps[lastIndex]) * 1000).toISOString()
      : new Date().toISOString();
    const currency = result?.meta?.currency ?? "USD";
    const exchangeName = result?.meta?.exchangeName ?? "unknown exchange";
    const content = [
      `${symbol} latest available close: ${lastClose ?? "unknown"} ${currency}.`,
      `Exchange: ${exchangeName}.`,
      "Use this as research context only; execution must resolve through the selected venue."
    ].join("\n");

    return {
      observations: [{
        sourceKind: "market",
        sourceName: "Yahoo Finance",
        sourceUrl: url,
        observedAt,
        title: `Yahoo Finance ${symbol}`,
        content,
        rawJson: raw,
        contentHash: hash(`yahoo_finance:${symbol}:${observedAt}:${lastClose ?? "null"}`)
      }]
    };
  }
};
