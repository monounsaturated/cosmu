import "dotenv/config";

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required env var: ${name}`);
  return value;
}

function optional(name: string): string | undefined {
  return process.env[name] || undefined;
}

export const env = {
  BINANCE_API_KEY: required("BINANCE_API_KEY"),
  BINANCE_API_SECRET: required("BINANCE_API_SECRET"),
  BINANCE_TESTNET_API_KEY: optional("BINANCE_TESTNET_API_KEY"),
  BINANCE_TESTNET_API_SECRET: optional("BINANCE_TESTNET_API_SECRET"),
  /** Default mode if not specified per-tool call. */
  DEFAULT_MODE: (process.env.DEFAULT_MODE ?? "testnet") as "testnet" | "live"
};
