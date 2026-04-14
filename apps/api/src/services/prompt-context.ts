import type { VenueContext } from "../adapters/binance.js";
import {
  getBotPrePromptContext,
  getFormatterPromptForVenue,
  getPrepromptForVenue,
  type BotSetup
} from "../lib/store.js";
import type { ResearchPhase } from "@cosmu/shared";

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

const DEFAULT_SYSTEM_PRELUDE = [
  "You are the trading decision engine for one autonomous spot bot.",
  "Return only valid JSON matching the provided schema."
].join("\n");

const RESEARCH_OUTPUT_INSTRUCTION = [
  "Return a single JSON object only (research phase — not executable orders).",
  "Fields:",
  "- rationaleSummary: short headline of your read on conditions and intent.",
  "- globalResearch: detailed reasoning, themes, risks, and what you would watch next.",
  "- candidateSymbols: array of Binance USDT spot symbols (e.g. BTCUSDT) you want priced for the execution stage; max 20; may be empty if you need no quotes.",
  "Do not output orders, quantities, or TradingDecision fields here."
].join("\n");

const DEFAULT_FORMATTER_BODY = [
  "You are the execution and formatting stage for one autonomous Binance spot bot.",
  "",
  "You receive:",
  "1) A research JSON object from an upstream analyst (rationale + thesis + candidateSymbols).",
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

const buildRuntimeUserSections = (input: {
  bot: BotSetup;
  venueContext: VenueContext;
  historyContext: HistoryContext;
  /** null = omit live price block; otherwise only symbols in this set appear */
  priceSymbolFilter: Set<string> | null;
  /** when true, prepend upstream research JSON block */
  researchBlock: ResearchPhase | null;
}) => {
  const { bot, venueContext, historyContext, priceSymbolFilter, researchBlock } = input;
  const { runtimeConfig, promptConfig } = bot;
  const modules = promptConfig.modules;
  const exec = runtimeConfig.execution;
  const { snapshot } = venueContext;

  const sections: string[] = [];

  if (researchBlock) {
    sections.push(
      ["=== UPSTREAM RESEARCH (phase 1 JSON) ===", JSON.stringify(researchBlock, null, 2)].join("\n")
    );
  }

  sections.push(
    [
      "=== SESSION ===",
      `Bot: ${bot.name} (#${bot.botNumber}) | Model: ${bot.modelProfileName}`,
      `Mode: ${runtimeConfig.mode} | Venue: Binance Spot | Frequency: every ${runtimeConfig.frequencyMinutes}min`,
      `Budget: ${fmtUsd(runtimeConfig.budgetUsdt)} — you must stay within this allocation`
    ].join("\n")
  );

  const allowedTypes = [exec.allowMarketOrders && "MARKET", exec.allowLimitOrders && "LIMIT"]
    .filter(Boolean)
    .join(", ");
  sections.push(
    [
      "=== EXECUTION RULES ===",
      `Rules enforced: ${exec.enabled ? "YES" : "NO (relaxed)"}`,
      exec.enabled
        ? `Max orders/run: ${exec.maxOrdersPerRun} | Max notional/order: ${exec.maxNotionalPerOrderUsd} USDT`
        : `Configured caps (not enforced while relaxed): max ${exec.maxOrdersPerRun} orders/run, ${exec.maxNotionalPerOrderUsd} USDT/order — total spend still cannot exceed budget and venue rules apply.`,
      exec.enabled ? `Cash reserve (untouchable): ${exec.minCashReserveUsd} USDT` : "",
      `Allowed types: ${allowedTypes}`
    ]
      .filter(Boolean)
      .join("\n")
  );

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

  if (priceSymbolFilter !== null && priceSymbolFilter.size > 0) {
    const relevantPriceEntries = Object.entries(venueContext.priceMap)
      .filter(([symbol]) => priceSymbolFilter.has(symbol))
      .sort(([a], [b]) => a.localeCompare(b));

    if (relevantPriceEntries.length > 0) {
      const priceLines = relevantPriceEntries.map(
        ([symbol, price]) => `${symbol}: ${fmtNum(price)}`
      );
      sections.push(
        [
          "=== LIVE MARKET PRICES (for execution) ===",
          "Use these reference prices for stopLossPrice / takeProfitPrice on buys.",
          ...priceLines
        ].join("\n")
      );
    }
  }

  if (runtimeConfig.symbolScope === "selected" && runtimeConfig.contextSymbols.length > 0) {
    sections.push(
      ["=== AUTHORIZED PAIRS — trade ONLY these ===", runtimeConfig.contextSymbols.join(", ")].join("\n")
    );
  } else {
    sections.push(
      "=== TRADING SCOPE ===\nYou may trade ANY USDT spot pair available on Binance. Pick your symbols based on your own analysis."
    );
  }

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
      .map((r, i) => `${i + 1}. ${r.botName ?? r.name ?? "Bot"}: ${fmtUsd(Number(r.netPnlUsd ?? 0))} net PnL`);
    sections.push(["=== BOT RANKINGS ===", ...rankLines].join("\n"));
  }

  return sections.join("\n\n");
};

type BuildPromptContextInput = {
  bot: BotSetup;
  venueContext: VenueContext;
};

/** Phase 1: preprompt + bot strategy; user context without live prices (research JSON). */
export const buildResearchPhaseContext = async ({ bot, venueContext }: BuildPromptContextInput) => {
  const { runtimeConfig, promptConfig } = bot;
  const modules = promptConfig.modules;

  const historyContext = await getBotPrePromptContext({
    botId: bot.id,
    pastTradesLookback: modules.pastTradesLookback
  });

  const configuredPreprompt = (await getPrepromptForVenue(runtimeConfig.venue)).trim();
  const preamble = configuredPreprompt.length > 0 ? configuredPreprompt : DEFAULT_SYSTEM_PRELUDE;

  const systemPrompt = [preamble, bot.promptBody.trim(), RESEARCH_OUTPUT_INSTRUCTION].filter(Boolean).join("\n\n");

  const userMessage = buildRuntimeUserSections({
    bot,
    venueContext,
    historyContext,
    priceSymbolFilter: null,
    researchBlock: null
  });

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

/** Phase 2: formatter + hard constraints; user context includes research + prices for given symbols. */
export const buildFormatterPhaseContext = async ({
  bot,
  venueContext,
  research,
  priceSymbolFilter
}: BuildPromptContextInput & { research: ResearchPhase; priceSymbolFilter: Set<string> }) => {
  const { runtimeConfig, promptConfig } = bot;
  const modules = promptConfig.modules;

  const historyContext = await getBotPrePromptContext({
    botId: bot.id,
    pastTradesLookback: modules.pastTradesLookback
  });

  const configuredFormatter = (await getFormatterPromptForVenue(runtimeConfig.venue)).trim();
  const formatterBody = configuredFormatter.length > 0 ? configuredFormatter : DEFAULT_FORMATTER_BODY;

  const systemPrompt = [formatterBody, NON_NEGOTIABLE_CONSTRAINTS_BLOCK].join("\n\n");

  const userMessage = buildRuntimeUserSections({
    bot,
    venueContext,
    historyContext,
    priceSymbolFilter,
    researchBlock: research
  });

  const compactContext: Record<string, unknown> = {
    phase: "formatter",
    mode: runtimeConfig.mode,
    symbolScope: runtimeConfig.symbolScope,
    walletTotalUsd: venueContext.snapshot.totalUsdValue,
    candidateSymbols: research.candidateSymbols,
    modulesActive: Object.entries(modules)
      .filter(([k, v]) => v === true && k.startsWith("include"))
      .map(([k]) => k)
  };

  return { systemPrompt, userMessage, compactContext };
};
