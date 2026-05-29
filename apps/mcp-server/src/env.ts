import { config } from "dotenv";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { existsSync } from "node:fs";

// Load .env.local from monorepo root (works whether running from project root or mcp-server dir)
const __dirname = dirname(fileURLToPath(import.meta.url));
const roots = [resolve(__dirname, "../../.."), resolve(__dirname, "..")];
for (const root of roots) {
  for (const file of [".env.local", ".env"]) {
    const path = resolve(root, file);
    if (existsSync(path)) config({ path });
  }
}

function optional(name: string): string | undefined {
  return process.env[name] || undefined;
}

export const env = {
  BINANCE_API_KEY: optional("BINANCE_API_KEY"),
  BINANCE_API_SECRET: optional("BINANCE_API_SECRET"),
  BINANCE_TESTNET_API_KEY: optional("BINANCE_TESTNET_API_KEY"),
  BINANCE_TESTNET_API_SECRET: optional("BINANCE_TESTNET_API_SECRET"),
  /** Default mode if not specified per-tool call. */
  DEFAULT_MODE: (process.env.DEFAULT_MODE ?? "testnet") as "testnet" | "live"
};
