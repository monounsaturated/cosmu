import type { VenueContext } from "../adapters/binance.js";
import {
  getBotPrePromptContext,
  getFormatterPromptForVenue,
  getPrepromptForVenue,
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

const DEFAULT_SYSTEM_PRELUDE =
  "You are the research analyst for one autonomous spot bot. Analyse market conditions, identify opportunities, and mention any USDT trading pair symbols you find interesting (e.g. BTCUSDT). Write freely — your analysis will be passed to a separate execution stage.";

const DEFAULT_FORMATTER_BODY = [
  "You are the execution and formatting stage for one autonomous Binance spot bot.",
  "",
  "You receive:",
  "1) Free-form research analysis from an upstream analyst (thesis, reasoning, symbol mentions).",
  "2) Live snapshot prices for relevant symbols plus session, wallet, and execution rules.",
  "",
  "Your only output is one JSON object matching the TradingDecision schema.",
  "",
  "Rules:",
  "- Ground every BUY in the live prices given: stopLossPrice must be strictly below the reference price shown, takeProfitPrice strictly above.",
  "- If research is insufficient, contradictory, or no valid trade exists, return mode hold with an empty orders array.",
  "- Do not invent balances or symbols outside the research intent and the authorized trading scope.",
  "- SELL orders: stopLossPrice and takeProfitPrice must be null."
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
  `Bot: ${bot.name} (#${bot.botNumber}) | Model: ${bot.modelProfileName}`,
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

/** Phase 1: full context for creative research (no prices, no formatting constraints). */
const buildResearchUserSections = (input: {
  bot: BotSetup;
  venueContext: VenueContext;
  historyContext: HistoryContext;
}) => {
  const { bot, venueContext, historyContext } = input;
  const { runtimeConfig, promptConfig } = bot;
  const modules = promptConfig.modules;
  const { snapshot } = venueContext;

  const sections: string[] = [];

  sections.push(buildSessionSection(bot));
  sections.push(buildExecRulesSection(runtimeConfig.execution));
  sections.push(buildWalletSection(snapshot));
  sections.push(buildTradingScopeSection(runtimeConfig));

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

  return sections.join("\n\n");
};

/** Phase 2: slim context for the formatter (research text + prices + wallet + rules). */
const buildFormatterUserSections = (input: {
  bot: BotSetup;
  venueContext: VenueContext;
  researchRawText: string;
  priceSymbolFilter: Set<string>;
}) => {
  const { bot, venueContext, researchRawText, priceSymbolFilter } = input;
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

  return sections.join("\n\n");
};

type BuildPromptContextInput = {
  bot: BotSetup;
  venueContext: VenueContext;
};

/** Phase 1: preprompt + bot strategy (free-form, no structured output). */
export const buildResearchPhaseContext = async ({ bot, venueContext }: BuildPromptContextInput) => {
  const { runtimeConfig, promptConfig } = bot;
  const modules = promptConfig.modules;

  const historyContext = await getBotPrePromptContext({
    botId: bot.id,
    pastTradesLookback: modules.pastTradesLookback
  });

  const configuredPreprompt = (await getPrepromptForVenue(runtimeConfig.venue)).trim();
  const preamble = configuredPreprompt.length > 0 ? configuredPreprompt : DEFAULT_SYSTEM_PRELUDE;

  const systemPrompt = [preamble, bot.promptBody.trim()].filter(Boolean).join("\n\n");

  const userMessage = buildResearchUserSections({ bot, venueContext, historyContext });

  const compactContext: Record<string, unknown> = {
    phase: "research",
    mode: runtimeConfig.mode,
    symbolScope: runtimeConfig.symbolScope,
    walletTotalUsd: venueContext.snapshot.totalUsdValue,
    balanceCount: venueContext.snapshot.balances.length,
    modulesActive: Object.entries(modules)
      .filter(([k, v]) => v === true && k.startsWith("include"))
      .map(([k]) => k)
  };

  return { systemPrompt, userMessage, compactContext };
};

/** Phase 2: formatter + hard constraints; slim context with research text + prices. */
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
  const { runtimeConfig } = bot;

  const configuredFormatter = (await getFormatterPromptForVenue(runtimeConfig.venue)).trim();
  const formatterBody = configuredFormatter.length > 0 ? configuredFormatter : DEFAULT_FORMATTER_BODY;

  const systemPrompt = [formatterBody, NON_NEGOTIABLE_CONSTRAINTS_BLOCK].join("\n\n");

  const userMessage = buildFormatterUserSections({
    bot,
    venueContext,
    researchRawText,
    priceSymbolFilter
  });

  const compactContext: Record<string, unknown> = {
    phase: "formatter",
    mode: runtimeConfig.mode,
    symbolScope: runtimeConfig.symbolScope,
    walletTotalUsd: venueContext.snapshot.totalUsdValue,
    candidateSymbols,
    modulesActive: []
  };

  return { systemPrompt, userMessage, compactContext };
};
