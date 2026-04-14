import type { VenueContext } from "../adapters/binance.js";
import { getBotPrePromptContext, type BotSetup } from "../lib/store.js";

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
  const operatorPrompt = promptConfig.operatorPrompt?.trim();
  const exec = runtimeConfig.execution;
  const { snapshot } = venueContext;

  const historyContext = await getBotPrePromptContext({
    botId: bot.id,
    pastTradesLookback: modules.pastTradesLookback
  });

  // ── System message: user strategy + hard constraints ───────────────────────
  const systemPrompt = [
    bot.promptBody.trim(),
    operatorPrompt ? ["---", "SECONDARY OPERATOR PROMPT", operatorPrompt].join("\n") : "",
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

  // ── User message: structured runtime data ──────────────────────────────────
  const sections: string[] = [];

  sections.push(
    [
      "=== SESSION ===",
      `Bot: ${bot.name} (#${bot.botNumber}) | Model: ${bot.modelProfileName}`,
      `Mode: ${runtimeConfig.mode} | Venue: Binance Spot | Frequency: every ${runtimeConfig.frequencyMinutes}min`,
      `Budget: ${fmtUsd(runtimeConfig.budgetUsdt)} — you must stay within this allocation`
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

  // — Market prices from the venue —
  const priceEntries = Object.entries(venueContext.priceMap)
    .sort(([a], [b]) => a.localeCompare(b));
  if (priceEntries.length > 0) {
    const priceLines = priceEntries.map(
      ([symbol, price]) => `${symbol}: ${fmtNum(price)}`
    );
    sections.push(
      [
        "=== LIVE MARKET PRICES (from venue) ===",
        "Use these prices to set stopLossPrice / takeProfitPrice correctly.",
        ...priceLines
      ].join("\n")
    );
  }

  // — Available trading pairs —
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

  const compactContext: Record<string, unknown> = {
    mode: runtimeConfig.mode,
    symbolScope: runtimeConfig.symbolScope,
    walletTotalUsd: snapshot.totalUsdValue,
    balanceCount: snapshot.balances.length,
    modulesActive: Object.entries(modules)
      .filter(([k, v]) => v === true && k.startsWith("include"))
      .map(([k]) => k)
  };

  return { systemPrompt, userMessage, compactContext };
};
