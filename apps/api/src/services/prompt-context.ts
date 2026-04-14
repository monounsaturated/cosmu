import type { VenueContext } from "../adapters/binance.js";
import { getBotPrePromptContext, type BotSetup } from "../lib/store.js";

// Shown when symbolScope = "all" — just reference anchors for the LLM
const MAJOR_PAIRS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT"];

const fmtUsd = (n: number) =>
  `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const fmtNum = (n: number) =>
  n.toLocaleString("en-US", { maximumSignificantDigits: 8, useGrouping: false });

type BuildPromptContextInput = {
  bot: BotSetup;
  venueContext: VenueContext;
};

export const buildPromptContext = async ({ bot, venueContext }: BuildPromptContextInput) => {
  const { runtimeConfig, promptConfig } = bot;
  const modules = promptConfig.modules;
  const exec = runtimeConfig.execution;
  const { snapshot, priceMap } = venueContext;

  const historyContext = await getBotPrePromptContext({
    botId: bot.id,
    pastTradesLookback: modules.pastTradesLookback
  });

  // ── System message: the user's strategy + non-negotiable rules ─────────────
  const systemPrompt = [
    bot.promptBody.trim(),
    [
      "---",
      "NON-NEGOTIABLE CONSTRAINTS (enforced in code after your response):",
      "• Every BUY order MUST include stopLossPrice (strictly below entry) and takeProfitPrice (strictly above entry).",
      "  After a buy fills, an OCO SELL is automatically placed at those two levels.",
      "• For SELL orders: set stopLossPrice and takeProfitPrice to null.",
      "• No clear opportunity? Return mode='hold' with an empty orders array.",
      "• Reply with valid JSON only — no markdown, no text outside the JSON."
    ].join("\n")
  ].join("\n\n");

  // ── User message: structured runtime data as readable sections ─────────────
  const sections: string[] = [];

  // — Bot metadata —
  sections.push(
    [
      "=== SESSION ===",
      `Bot: ${bot.name} (#${bot.botNumber}) | Preset: ${promptConfig.preset} | Model: ${bot.modelProfileName}`,
      `Mode: ${runtimeConfig.mode} | Venue: Binance Spot | Frequency: every ${runtimeConfig.frequencyMinutes}min`
    ].join("\n")
  );

  // — Execution rules —
  const allowedTypes = [exec.allowMarketOrders && "MARKET", exec.allowLimitOrders && "LIMIT"]
    .filter(Boolean)
    .join(", ");
  sections.push(
    [
      "=== EXECUTION RULES ===",
      `Rules enforced: ${exec.enabled ? "YES" : "NO (relaxed)"}`,
      `Max orders/run: ${exec.maxOrdersPerRun} | Max notional/order: ${exec.maxNotionalPerOrderUsd} USDT`,
      exec.enabled ? `Cash reserve (untouchable): ${exec.minCashReserveUsd} USDT` : "",
      `Allowed types: ${allowedTypes}`
    ]
      .filter(Boolean)
      .join("\n")
  );

  // — Wallet —
  const walletLines = [
    "=== WALLET ===",
    `Total: ${fmtUsd(snapshot.totalUsdValue)}`
  ];
  for (const b of snapshot.balances) {
    const usd = b.usdValue != null ? ` (${fmtUsd(b.usdValue)})` : "";
    const locked = b.locked > 0 ? ` + ${fmtNum(b.locked)} locked` : "";
    walletLines.push(`${b.asset}: ${fmtNum(b.free)} free${locked}${usd}`);
  }
  sections.push(walletLines.join("\n"));

  // — Market prices: held assets + selected pairs + major anchors —
  const heldPairs = snapshot.balances
    .filter((b) => b.asset !== "USDT" && priceMap[`${b.asset}USDT`])
    .map((b) => `${b.asset}USDT`);

  const selectedPairs =
    runtimeConfig.symbolScope === "selected"
      ? runtimeConfig.contextSymbols.filter((s) => priceMap[s])
      : [];

  const shownSet = new Set([...heldPairs, ...selectedPairs]);
  const majorFill = MAJOR_PAIRS.filter((p) => priceMap[p] && !shownSet.has(p));
  const pricePairs = [...heldPairs, ...selectedPairs.filter((p) => !shownSet.has(p)), ...majorFill].slice(
    0,
    30
  );

  if (pricePairs.length > 0) {
    const priceLines = ["=== MARKET PRICES ==="];
    for (const pair of pricePairs) {
      const tag = heldPairs.includes(pair) ? " [held]" : selectedPairs.includes(pair) ? " [selected]" : "";
      priceLines.push(`${pair}: ${fmtNum(priceMap[pair]!)}${tag}`);
    }
    sections.push(priceLines.join("\n"));
  }

  // — Authorized pairs: only injected when symbolScope = "selected" —
  if (runtimeConfig.symbolScope === "selected" && runtimeConfig.contextSymbols.length > 0) {
    sections.push(
      ["=== AUTHORIZED PAIRS — trade ONLY these ===", runtimeConfig.contextSymbols.join(", ")].join("\n")
    );
  }

  // — Optional modules —
  if (modules.includeWalletOverview && historyContext.performance) {
    const p = historyContext.performance;
    const start = fmtUsd(p.firstPortfolioUsd ?? 0);
    const now = fmtUsd(p.currentPortfolioUsd ?? snapshot.totalUsdValue);
    const pnlNet = p.netPnlUsd != null ? ` | Net PnL: ${fmtUsd(p.netPnlUsd)}` : "";
    sections.push(
      [
        "=== PORTFOLIO OVERVIEW ===",
        `Started: ${start} | Now: ${now}${pnlNet}`,
        `Runs: ${p.runCount ?? 0} | Trades: ${p.tradeCount ?? 0} | Fees: ${fmtUsd(p.totalFeesUsd ?? 0)}`
      ].join("\n")
    );
  }

  if (modules.includePerformanceStats && historyContext.performance) {
    sections.push(
      [
        "=== PERFORMANCE STATS ===",
        JSON.stringify(historyContext.performance, null, 2)
      ].join("\n")
    );
  }

  if (modules.includePastTrades && historyContext.pastTrades?.length) {
    const tradeLines = (historyContext.pastTrades as Array<Record<string, unknown>>).map(
      (t) =>
        `${String(t.side ?? "").toUpperCase()} ${t.symbol} qty=${t.executedQuantity ?? t.requestedQuantity} @ ${t.averageFillPrice ?? "?"} → ${t.status}`
    );
    sections.push(
      [`=== RECENT TRADES (last ${modules.pastTradesLookback}) ===`, ...tradeLines].join("\n")
    );
  }

  if (modules.includeBotRanking && historyContext.ranking?.length) {
    const rankLines = (historyContext.ranking as Array<Record<string, unknown>>)
      .slice(0, 10)
      .map((r, i) => `${i + 1}. ${r.name}: ${fmtUsd(Number(r.netPnlUsd ?? 0))} net PnL`);
    sections.push(["=== BOT RANKINGS ===", ...rankLines].join("\n"));
  }

  const userMessage = sections.join("\n\n");

  // Compact summary stored in DB for audit/replay (not sent to LLM)
  const compactContext: Record<string, unknown> = {
    preset: promptConfig.preset,
    mode: runtimeConfig.mode,
    symbolScope: runtimeConfig.symbolScope,
    walletTotalUsd: snapshot.totalUsdValue,
    balanceCount: snapshot.balances.length,
    pricesShownCount: pricePairs.length,
    modulesActive: Object.entries(modules)
      .filter(([k, v]) => v === true && k.startsWith("include"))
      .map(([k]) => k)
  };

  return { systemPrompt, userMessage, compactContext };
};
