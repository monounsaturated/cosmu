/**
 * MCP tool definitions — each maps to a Binance REST call.
 *
 * Every tool has:
 *  - name / description (exposed via tools/list)
 *  - inputSchema (JSON Schema for parameter validation)
 *  - handler (function that takes validated params and returns content)
 */
import * as binance from "./binance-client.js";
import { env } from "./env.js";

type Mode = "testnet" | "live";

function resolveMode(input: { mode?: string }): Mode {
  const m = input.mode ?? env.DEFAULT_MODE;
  if (m !== "live" && m !== "testnet") return "testnet";
  return m;
}

export type ToolDef = {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  handler: (args: any) => Promise<unknown>;
};

const modeProperty = {
  mode: {
    type: "string",
    enum: ["live", "testnet"],
    description: "Binance mode. Defaults to DEFAULT_MODE env var (testnet)."
  }
};

export const tools: ToolDef[] = [
  {
    name: "get_account",
    description: "Fetch current Binance account balances (free/locked per asset, total USDT).",
    inputSchema: {
      type: "object",
      properties: { ...modeProperty },
      required: []
    },
    handler: async (args) => binance.getAccount(resolveMode(args))
  },
  {
    name: "get_prices",
    description: "Fetch current ticker prices. Optionally filter to specific symbols (e.g. [\"BTCUSDT\",\"ETHUSDT\"]).",
    inputSchema: {
      type: "object",
      properties: {
        ...modeProperty,
        symbols: {
          type: "array",
          items: { type: "string" },
          description: "Optional list of symbols to filter (e.g. BTCUSDT). Returns all if omitted."
        }
      },
      required: []
    },
    handler: async (args) => binance.getPrices(resolveMode(args), args.symbols)
  },
  {
    name: "get_symbols",
    description: "List all tradable USDT spot symbols on Binance.",
    inputSchema: {
      type: "object",
      properties: {},
      required: []
    },
    handler: async () => binance.getSymbols()
  },
  {
    name: "get_klines",
    description: "Fetch OHLCV candlestick data for a symbol. Useful for technical analysis.",
    inputSchema: {
      type: "object",
      properties: {
        ...modeProperty,
        symbol: { type: "string", description: "Trading pair (e.g. BTCUSDT)" },
        interval: {
          type: "string",
          enum: ["1m", "5m", "15m", "1h", "4h", "1d", "1w"],
          description: "Candlestick interval"
        },
        limit: {
          type: "number",
          description: "Number of candles to return (max 1000, default 100)"
        }
      },
      required: ["symbol", "interval"]
    },
    handler: async (args) =>
      binance.getKlines(resolveMode(args), args.symbol, args.interval, args.limit ?? 100)
  },
  {
    name: "get_ticker_24h",
    description: "Fetch 24-hour rolling ticker statistics. Returns price change, volume, highs/lows.",
    inputSchema: {
      type: "object",
      properties: {
        ...modeProperty,
        symbol: {
          type: "string",
          description: "Trading pair (e.g. BTCUSDT). Omit for all symbols."
        }
      },
      required: []
    },
    handler: async (args) => binance.getTicker24h(resolveMode(args), args.symbol)
  },
  {
    name: "get_order_book",
    description: "Fetch the order book (bids/asks) for a symbol.",
    inputSchema: {
      type: "object",
      properties: {
        ...modeProperty,
        symbol: { type: "string", description: "Trading pair (e.g. BTCUSDT)" },
        limit: {
          type: "number",
          description: "Depth limit (5, 10, 20, 50, 100). Default 20."
        }
      },
      required: ["symbol"]
    },
    handler: async (args) =>
      binance.getOrderBook(resolveMode(args), args.symbol, args.limit ?? 20)
  },
  {
    name: "get_open_orders",
    description: "Fetch currently open orders. Optionally filter by symbol.",
    inputSchema: {
      type: "object",
      properties: {
        ...modeProperty,
        symbol: {
          type: "string",
          description: "Filter to a specific trading pair. Omit for all open orders."
        }
      },
      required: []
    },
    handler: async (args) => binance.getOpenOrders(resolveMode(args), args.symbol)
  },
  {
    name: "cancel_open_orders",
    description: "Cancel all open orders for a given symbol.",
    inputSchema: {
      type: "object",
      properties: {
        ...modeProperty,
        symbol: { type: "string", description: "Trading pair (e.g. BTCUSDT)" }
      },
      required: ["symbol"]
    },
    handler: async (args) => binance.cancelOpenOrders(resolveMode(args), args.symbol)
  }
];
