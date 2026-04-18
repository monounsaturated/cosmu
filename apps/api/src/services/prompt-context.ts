import type { VenueContext } from "../adapters/binance.js";
import {
  getBotPrePromptContext,
  getActiveFormatterPrompt,
  type BotSetup
} from "../lib/store.js";

const fmtUsd = (n: number) =>
  `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const fmtNum = (n: number) =>
  n.toLocaleString("en-US", { maximumSignificantDigits: 8, useGrouping: false });

export const NON_NEGOTIABLE_CONSTRAINTS_BLOCK = [
  "---",
  "NON-NEGOTIABLE CONSTRAINTS (enforced in code after your response):",
  "• Every BUY order MUST include stopLossPrice (strictly below entry) and takeProfitPrice (strictly above entry).",
  "  After a buy fills, an OCO SELL is automatically placed at those two levels.",
  "• For SELL orders: set stopLossPrice and takeProfitPrice to null.",
  "• No clear opportunity? Return mode='hold' with an empty orders array.",
  "• Reply with valid JSON only — no markdown, no text outside the JSON."
].join("\n");

// System prelude removed — the user's written prompt is now the entire system prompt for research.

export const DEFAULT_FORMATTER_BODY = [
  "You are the execution stage (phase 2) for one autonomous Binance USDT spot bot.",
  "",
  "Inputs (in the user message):",
  "- UPSTREAM RESEARCH: qualitative thesis from phase 1 — symbols may be informal; normalize to valid *USDT pairs only when you place orders.",
  "- SESSION / EXECUTION RULES / WALLET / AUTHORIZED PAIRS: hard facts — never contradict them.",
  "- LIVE MARKET PRICES: authoritative reference for sizing stops and limits on buys.",
  "",
  "Output: exactly one JSON object (no markdown fences, no prose) matching TradingDecision:",
  '- mode: one of "rebalance" | "enter" | "exit" | "hold" | "adjust". Use "hold" when there is no defensible trade.',
  "- rationaleSummary: <=600 chars, decision-grade summary.",
  "- globalRationale: <=4000 chars tying research to orders or explaining why you are flat.",
  "- confidence: number in [0,1].",
  "- timeHorizon: short string or null.",
  "- orders: array (<= max orders/run from rules). Each order: symbol, side buy|sell, type market|limit, quantity (>0), limitPrice (null unless limit), stopLossPrice, takeProfitPrice, rationale.",
  "- targetAllocations: usually [].",
  "",
  "Order logic:",
  "- BUY: every buy MUST set stopLossPrice strictly below the live reference price for that symbol and takeProfitPrice strictly above. Omit trades you cannot justify with the given prices.",
  "- SELL: set stopLossPrice and takeProfitPrice to null.",
  "- Respect authorized pair list when present; otherwise any Binance USDT spot pair is allowed if grounded in research + prices.",
  "- Stay within wallet + execution caps; prefer fewer, higher-conviction orders over many small ones.",
  "- If research conflicts with prices, scope, or risk limits, prefer mode hold with orders: []."
].join("\n");

type HistoryContext = Awaited<ReturnType<typeof getBotPrePromptContext>>;

/** Shared helpers for building wallet and price sections used by both phases. */

const buildWalletSection = (snapshot: VenueContext["snapshot"]) => {
  const lines = ["=== WALLET ===", `Total: ${fmtUsd(snapshot.totalUsdValue)}`];
  for (const b of snapshot.balances) {
    const usd = b.usdValue != null ? ` (${fmtUsd(b.usdValue)})` : "";
    const locked = b.locked > 0 ? ` + ${fmtNum(b.locked)} locked` : "";
    lines.push(`${b.asset}: ${fmtNum(b.free)} free${locked}${usd}`);
  }
  return lines.join("\n");
};

const buildSessionSection = (bot: BotSetup) => [
  "=== SESSION ===",
  `Bot: ${bot.name} (#${bot.botNumber}) | Model: ${bot.traderModelProfileName}`,
  `Mode: ${bot.runtimeConfig.mode} | Venue: Binance Spot | Frequency: every ${bot.runtimeConfig.frequencyMinutes}min`,
  `Budget: ${fmtUsd(bot.runtimeConfig.budgetUsdt)} — you must stay within this allocation`
].join("\n");

const buildExecRulesSection = (exec: BotSetup["runtimeConfig"]["execution"]) => {
  const allowedTypes = [exec.allowMarketOrders && "MARKET", exec.allowLimitOrders && "LIMIT"]
    .filter(Boolean)
    .join(", ");
  return [
    "=== EXECUTION RULES ===",
    `Rules enforced: ${exec.enabled ? "YES" : "NO (relaxed)"}`,
    exec.enabled
      ? `Max orders/run: ${exec.maxOrdersPerRun} | Max notional/order: ${exec.maxNotionalPerOrderUsd} USDT`
      : `Configured caps (not enforced while relaxed): max ${exec.maxOrdersPerRun} orders/run, ${exec.maxNotionalPerOrderUsd} USDT/order — total spend still cannot exceed budget and venue rules apply.`,
    exec.enabled ? `Cash reserve (untouchable): ${exec.minCashReserveUsd} USDT` : "",
    `Allowed types: ${allowedTypes}`
  ]
    .filter(Boolean)
    .join("\n");
};

const buildTradingScopeSection = (runtimeConfig: BotSetup["runtimeConfig"]) => {
  if (runtimeConfig.symbolScope === "selected" && runtimeConfig.contextSymbols.length > 0) {
    return ["=== AUTHORIZED PAIRS — trade ONLY these ===", runtimeConfig.contextSymbols.join(", ")].join("\n");
  }
  return "=== TRADING SCOPE ===\nYou may trade ANY USDT spot pair available on Binance. Pick your symbols based on your own analysis.";
};

const buildPriceSection = (venueContext: VenueContext, priceSymbolFilter: Set<string>) => {
  if (priceSymbolFilter.size === 0) return null;
  const relevantPriceEntries = Object.entries(venueContext.priceMap)
    .filter(([symbol]) => priceSymbolFilter.has(symbol))
    .sort(([a], [b]) => a.localeCompare(b));
  if (relevantPriceEntries.length === 0) return null;
  const priceLines = relevantPriceEntries.map(
    ([symbol, price]) => `${symbol}: ${fmtNum(price)}`
  );
  return [
    "=== LIVE MARKET PRICES (for execution) ===",
    "Use these reference prices for stopLossPrice / takeProfitPrice on buys.",
    ...priceLines
  ].join("\n");
};

/** Phase 1: pure written prompt — no injected data sections. */
const buildResearchUserSections = (_input: {
  bot: BotSetup;
  venueContext: VenueContext;
  historyContext: HistoryContext;
}) => {
  // Research phase receives NO injected data — just the written prompt
  // (delivered via the system message). Return empty user message.
  return "";
};

/** Build optional module sections (used by the trader/formatter phase). */
const buildOptionalModuleSections = (input: {
  bot: BotSetup;
  venueContext: VenueContext;
  historyContext: HistoryContext;
}) => {
  const { bot, venueContext, historyContext } = input;
  const modules = bot.promptConfig.modules;
  const { snapshot } = venueContext;

  const sections: string[] = [];

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
      ["=== PERFORMANCE STATS ===", JSON.stringify(historyContext.performance, null, 2)].join("\n")
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
      .map((r, i) => `${i + 1}. ${r.botName ?? r.name ?? "Bot"}: ${fmtUsd(Number(r.netPnlUsd ?? 0))} net PnL`);
    sections.push(["=== BOT RANKINGS ===", ...rankLines].join("\n"));
  }

  return sections;
};

/** Phase 2: trader context with research text + prices + wallet + rules + optional modules. */
const buildFormatterUserSections = (input: {
  bot: BotSetup;
  venueContext: VenueContext;
  researchRawText: string;
  priceSymbolFilter: Set<string>;
  historyContext: HistoryContext;
}) => {
  const { bot, venueContext, researchRawText, priceSymbolFilter, historyContext } = input;
  const { runtimeConfig } = bot;
  const { snapshot } = venueContext;

  const sections: string[] = [];

  sections.push(
    ["=== UPSTREAM RESEARCH (phase 1 analysis) ===", researchRawText].join("\n")
  );
  sections.push(buildSessionSection(bot));
  sections.push(buildExecRulesSection(runtimeConfig.execution));
  sections.push(buildWalletSection(snapshot));

  const priceBlock = buildPriceSection(venueContext, priceSymbolFilter);
  if (priceBlock) sections.push(priceBlock);

  sections.push(buildTradingScopeSection(runtimeConfig));

  // Append optional data modules (toggled on bot creation form)
  const moduleSections = buildOptionalModuleSections({ bot, venueContext, historyContext });
  sections.push(...moduleSections);

  return sections.join("\n\n");
};

type BuildPromptContextInput = {
  bot: BotSetup;
  venueContext: VenueContext;
};

/** Phase 1: pure written prompt — no injected data. */
export const buildResearchPhaseContext = async ({ bot, venueContext }: BuildPromptContextInput) => {
  const { runtimeConfig } = bot;

  const systemPrompt = bot.promptBody.trim();
  const userMessage = "Analyze the market now. Identify any trading opportunities worth exploring.";

  const compactContext: Record<string, unknown> = {
    phase: "research",
    mode: runtimeConfig.mode,
    symbolScope: runtimeConfig.symbolScope,
    walletTotalUsd: venueContext.snapshot.totalUsdValue,
    balanceCount: venueContext.snapshot.balances.length,
    modulesActive: []
  };

  return { systemPrompt, userMessage, compactContext };
};

/** Phase 2: formatter + hard constraints; includes all injected data. */
export const buildFormatterPhaseContext = async ({
  bot,
  venueContext,
  researchRawText,
  candidateSymbols,
  priceSymbolFilter
}: BuildPromptContextInput & {
  researchRawText: string;
  candidateSymbols: string[];
  priceSymbolFilter: Set<string>;
}) => {
  const { runtimeConfig, promptConfig } = bot;
  const modules = promptConfig.modules;

  const historyContext = await getBotPrePromptContext({
    botId: bot.id,
    pastTradesLookback: modules.pastTradesLookback
  });

  // Use bot's own trader prompt if set; fall back to venue-level formatter; then default
  const botTraderBody = bot.traderPromptBody?.trim() ?? "";
  let formatterBody: string;
  let formatterPromptVersionId: string | null = null;

  if (botTraderBody.length > 0) {
    formatterBody = botTraderBody;
    formatterPromptVersionId = bot.traderPromptVersionId ?? null;
  } else {
    const activeFormatter = await getActiveFormatterPrompt(runtimeConfig.venue);
    const trimmedCustom = activeFormatter?.body?.trim() ?? "";
    formatterBody = trimmedCustom.length > 0 ? trimmedCustom : DEFAULT_FORMATTER_BODY;
    formatterPromptVersionId = activeFormatter?.id ?? null;
  }

  const systemPrompt = [formatterBody, NON_NEGOTIABLE_CONSTRAINTS_BLOCK].join("\n\n");

  const userMessage = buildFormatterUserSections({
    bot,
    venueContext,
    researchRawText,
    priceSymbolFilter,
    historyContext
  });

  const compactContext: Record<string, unknown> = {
    phase: "formatter",
    mode: runtimeConfig.mode,
    symbolScope: runtimeConfig.symbolScope,
    walletTotalUsd: venueContext.snapshot.totalUsdValue,
    candidateSymbols,
    modulesActive: []
  };

  return {
    systemPrompt,
    userMessage,
    compactContext,
    formatterPromptVersionId
  };
};
