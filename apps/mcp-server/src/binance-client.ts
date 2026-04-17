/**
 * Lightweight Binance REST client for the MCP server.
 * Mirrors the functions from apps/api/src/adapters/binance.ts but is self-contained
 * so the MCP server has zero dependency on the API app at runtime.
 */
import crypto from "node:crypto";
import { env } from "./env.js";

type Mode = "testnet" | "live";

const LIVE_BASE = "https://api.binance.com/api";
const TESTNET_BASE = "https://testnet.binance.vision/api";

const baseUrl = (mode: Mode) => (mode === "live" ? LIVE_BASE : TESTNET_BASE);

const apiKey = (mode: Mode) =>
  mode === "testnet" && env.BINANCE_TESTNET_API_KEY
    ? env.BINANCE_TESTNET_API_KEY
    : env.BINANCE_API_KEY;

const apiSecret = (mode: Mode) =>
  mode === "testnet" && env.BINANCE_TESTNET_API_SECRET
    ? env.BINANCE_TESTNET_API_SECRET
    : env.BINANCE_API_SECRET;

const sign = (params: URLSearchParams, mode: Mode) =>
  crypto.createHmac("sha256", apiSecret(mode)).update(params.toString()).digest("hex");

async function request(mode: Mode, path: string, init?: RequestInit & { signed?: boolean }) {
  const url = `${baseUrl(mode)}${path}`;
  const headers = new Headers(init?.headers);
  headers.set("X-MBX-APIKEY", apiKey(mode));

  const res = await fetch(url, { ...init, headers });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Binance ${path}: ${res.status} ${text}`);
  }
  return res.json();
}

function signedQuery(mode: Mode, path: string) {
  const params = new URLSearchParams({ timestamp: Date.now().toString(), recvWindow: "5000" });
  params.set("signature", sign(params, mode));
  return request(mode, `${path}?${params.toString()}`);
}

/* ── Public tools ── */

export async function getAccount(mode: Mode) {
  const account = await signedQuery(mode, "/v3/account");
  const balances = (account.balances ?? [])
    .filter((b: any) => Number(b.free) > 0 || Number(b.locked) > 0)
    .map((b: any) => ({ asset: b.asset, free: Number(b.free), locked: Number(b.locked) }));
  const usdt = balances.find((b: any) => b.asset === "USDT");
  return {
    totalFreeUsdt: usdt?.free ?? 0,
    totalLockedUsdt: usdt?.locked ?? 0,
    balances
  };
}

export async function getPrices(mode: Mode, symbols?: string[]) {
  const all = await request(mode, "/v3/ticker/price");
  const filter = symbols ? new Set(symbols.map((s) => s.toUpperCase())) : null;
  const result: Record<string, number> = {};
  for (const entry of Array.isArray(all) ? all : []) {
    const sym = String(entry.symbol).toUpperCase();
    if (filter && !filter.has(sym)) continue;
    result[sym] = Number(entry.price);
  }
  return result;
}

export async function getSymbols() {
  const info = await request("live" as Mode, "/v3/exchangeInfo");
  return (info.symbols ?? [])
    .filter((s: any) => s.status === "TRADING" && s.isSpotTradingAllowed !== false && s.quoteAsset === "USDT")
    .map((s: any) => s.symbol as string)
    .sort();
}

export async function getKlines(mode: Mode, symbol: string, interval: string, limit: number) {
  const params = new URLSearchParams({ symbol: symbol.toUpperCase(), interval, limit: String(limit) });
  const raw = await request(mode, `/v3/klines?${params.toString()}`);
  return (raw as any[]).map((k) => ({
    openTime: k[0],
    open: Number(k[1]),
    high: Number(k[2]),
    low: Number(k[3]),
    close: Number(k[4]),
    volume: Number(k[5]),
    closeTime: k[6]
  }));
}

export async function getTicker24h(mode: Mode, symbol?: string) {
  const path = symbol
    ? `/v3/ticker/24hr?symbol=${symbol.toUpperCase()}`
    : "/v3/ticker/24hr";
  return request(mode, path);
}

export async function getOrderBook(mode: Mode, symbol: string, limit = 20) {
  const params = new URLSearchParams({ symbol: symbol.toUpperCase(), limit: String(limit) });
  return request(mode, `/v3/depth?${params.toString()}`);
}

export async function cancelOpenOrders(mode: Mode, symbol: string) {
  const params = new URLSearchParams({
    symbol: symbol.toUpperCase(),
    timestamp: Date.now().toString(),
    recvWindow: "5000"
  });
  params.set("signature", sign(params, mode));

  const res = await fetch(`${baseUrl(mode)}/v3/openOrders?${params.toString()}`, {
    method: "DELETE",
    headers: { "X-MBX-APIKEY": apiKey(mode) }
  });

  if (!res.ok) {
    const text = await res.text();
    let code: number | undefined;
    try { code = JSON.parse(text)?.code; } catch {}
    if (res.status === 400 && (code === -1121 || code === -2011)) return [];
    throw new Error(`Cancel orders failed for ${symbol}: ${res.status} ${text}`);
  }
  return res.json();
}

export async function getOpenOrders(mode: Mode, symbol?: string) {
  const params = new URLSearchParams({ timestamp: Date.now().toString(), recvWindow: "5000" });
  if (symbol) params.set("symbol", symbol.toUpperCase());
  params.set("signature", sign(params, mode));
  return request(mode, `/v3/openOrders?${params.toString()}`);
}
