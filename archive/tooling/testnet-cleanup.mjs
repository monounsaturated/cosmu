#!/usr/bin/env node
/**
 * Sells all non-USDT assets on Binance testnet to get a clean USDT balance.
 * Run: set -a && source .env.local && set +a && node scripts/testnet-cleanup.mjs
 */
import crypto from "node:crypto";

const TESTNET_BASE = "https://testnet.binance.vision/api";
const API_KEY = process.env.BINANCE_TESTNET_API_KEY;
const API_SECRET = process.env.BINANCE_TESTNET_API_SECRET;

if (!API_KEY || !API_SECRET) {
  console.error("❌ Missing BINANCE_TESTNET_API_KEY or BINANCE_TESTNET_API_SECRET in env");
  process.exit(1);
}

const sign = (qs) => crypto.createHmac("sha256", API_SECRET).update(qs).digest("hex");

const signedRequest = async (method, path, params = {}) => {
  const p = new URLSearchParams({ ...params, timestamp: Date.now().toString(), recvWindow: "10000" });
  p.set("signature", sign(p.toString()));
  const url = `${TESTNET_BASE}${path}`;
  const opts = { method, headers: { "X-MBX-APIKEY": API_KEY, "Content-Type": "application/x-www-form-urlencoded" } };
  const res = method === "GET"
    ? await fetch(`${url}?${p}`, opts)
    : await fetch(url, { ...opts, body: p.toString() });
  const text = await res.text();
  if (!res.ok) throw new Error(`${method} ${path} → ${res.status}: ${text}`);
  return JSON.parse(text);
};

const publicGet = async (path, params = {}) => {
  const qs = new URLSearchParams(params).toString();
  const res = await fetch(`${TESTNET_BASE}${path}${qs ? `?${qs}` : ""}`);
  return res.json();
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ── 1. Get account ─────────────────────────────────────────────────────────
console.log("\n📊 Fetching testnet account...");
const account = await signedRequest("GET", "/v3/account");
const allBalances = (account.balances ?? []);
const nonUsdt = allBalances.filter((b) => b.asset !== "USDT" && Number(b.free) > 0);

const usdtBefore = allBalances.find((b) => b.asset === "USDT");
console.log(`USDT before: ${Number(usdtBefore?.free ?? 0).toFixed(2)}`);
console.log(`Non-USDT assets with free balance: ${nonUsdt.length}`);
nonUsdt.forEach((b) => console.log(`  ${b.asset}: ${b.free}`));

if (nonUsdt.length === 0) {
  console.log("\n✅ Already all USDT — nothing to sell.");
  process.exit(0);
}

// ── 2. Get exchange info (testnet) ─────────────────────────────────────────
console.log("\n📋 Loading testnet exchange rules...");
const exInfo = await publicGet("/v3/exchangeInfo");
const symbolMap = Object.fromEntries((exInfo.symbols ?? []).map((s) => [s.symbol, s]));

// ── 3. Sell each asset ─────────────────────────────────────────────────────
console.log("\n💸 Selling all to USDT...\n");
const results = [];

for (const b of nonUsdt) {
  const symbol = `${b.asset}USDT`;
  const info = symbolMap[symbol];

  if (!info || info.status !== "TRADING" || info.isSpotTradingAllowed === false) {
    results.push({ asset: b.asset, status: "skip", reason: `${symbol} not TRADING on testnet` });
    continue;
  }

  const lotSize = info.filters.find((f) => f.filterType === "LOT_SIZE");
  const minNotionalFilter = info.filters.find((f) => f.filterType === "MIN_NOTIONAL" || f.filterType === "NOTIONAL");
  const stepSize = Number(lotSize?.stepSize ?? 0.001);
  const minQty = Number(lotSize?.minQty ?? 0);
  const minNotionalVal = Number(minNotionalFilter?.minNotional ?? minNotionalFilter?.minNotional ?? 1);

  const precision = stepSize.toString().includes(".") ? stepSize.toString().split(".")[1].length : 0;
  const rawQty = Math.floor(Number(b.free) / stepSize) * stepSize;
  const quantity = Number(rawQty.toFixed(precision));

  if (quantity <= 0 || quantity < minQty) {
    results.push({ asset: b.asset, status: "skip", reason: `qty ${quantity} < minQty ${minQty}` });
    continue;
  }

  // Price check
  let price = 0;
  try {
    const ticker = await publicGet("/v3/ticker/price", { symbol });
    price = Number(ticker.price ?? 0);
  } catch (_) {}

  const notional = quantity * price;
  if (price > 0 && notional < minNotionalVal) {
    results.push({ asset: b.asset, status: "skip", reason: `notional $${notional.toFixed(4)} < min $${minNotionalVal}` });
    continue;
  }

  try {
    const order = await signedRequest("POST", "/v3/order", {
      symbol,
      side: "SELL",
      type: "MARKET",
      quantity: quantity.toString(),
      newOrderRespType: "RESULT"
    });
    const received = Number(order.cummulativeQuoteQty ?? 0);
    const avgPrice = Number(order.fills?.[0]?.price ?? price);
    results.push({ asset: b.asset, status: "sold", quantity, received: received.toFixed(2), avgPrice });
    console.log(`  ✓ SELL ${quantity} ${b.asset} → ${received.toFixed(2)} USDT`);
  } catch (e) {
    results.push({ asset: b.asset, status: "error", reason: e.message.slice(0, 120) });
    console.log(`  ✗ ${b.asset}: ${e.message.slice(0, 80)}`);
  }

  await sleep(250);
}

// ── 4. Final balance ───────────────────────────────────────────────────────
await sleep(500);
const finalAccount = await signedRequest("GET", "/v3/account");
const finalBalances = finalAccount.balances.filter((b) => Number(b.free) > 0 || Number(b.locked) > 0);
const finalUsdt = finalBalances.find((b) => b.asset === "USDT");
const remaining = finalBalances.filter((b) => b.asset !== "USDT");

console.log("\n══════════════════════════════════════");
console.log("         TESTNET FINAL STATE");
console.log("══════════════════════════════════════");
console.log(`USDT: ${Number(finalUsdt?.free ?? 0).toFixed(2)} free${Number(finalUsdt?.locked ?? 0) > 0 ? ` + ${Number(finalUsdt.locked).toFixed(2)} locked` : ""}`);

if (remaining.length > 0) {
  console.log("\nUnsold assets (below min notional or no pair):");
  remaining.forEach((b) => console.log(`  ${b.asset}: ${b.free} free${Number(b.locked) > 0 ? ` + ${b.locked} locked` : ""}`));
} else {
  console.log("All assets converted to USDT ✅");
}

console.log("\nSell summary:");
results.forEach((r) => {
  if (r.status === "sold") console.log(`  ✓ ${r.asset}: ${r.quantity} sold → $${r.received} USDT`);
  else if (r.status === "skip") console.log(`  ⊘ ${r.asset}: skipped — ${r.reason}`);
  else console.log(`  ✗ ${r.asset}: ERROR — ${r.reason}`);
});
