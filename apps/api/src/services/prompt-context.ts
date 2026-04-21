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

/**
 * Anti-hallucination guardrail appended to every research system prompt.
 *
 * Grok fabricates confidently when asked for "latest tweets" without browsing — it
 * will invent plausible posts dated months/years ago. Research runs on xAI's
 * Responses API with `web_search` + `x_search` enabled, so the model CAN browse;
 * this block tells it that it must, and must flag the turn if it can't.
 */
export const RESEARCH_GROUNDING_BLOCK = [
  "---",
  "GROUNDING RULES (critical — your output feeds live trading decisions):",
  `• Today's date is ${new Date().toISOString().slice(0, 10)}. Any cited news, tweet, or price MUST come from a search you actually ran this turn — you have web_search and x_search tools available.`,
  "• For ANY claim about recent prices, news, tweets, or market events: call a search tool first. Never cite a date, username, or headline you did not just retrieve.",
  "• If a search returns no results or the tools are unavailable for some reason, say so explicitly (\"unable to retrieve live data for X\") and do NOT invent content to fill the gap. A short, honest report beats a detailed fabricated one.",
  "• When quoting tweets/posts, include the exact retrieved timestamp. When citing prices, state the source and time. Do not round timestamps to \"today\" unless they actually are today."
].join("\n");

export const NON_NEGOTIABLE_CONSTRAINTS_BLOCK = [
  "---",
  "NON-NEGOTIABLE CONSTRAINTS (enforced in code after your response):",
  "• Every BUY order MUST include stopLossPrice (strictly below entry) AND takeProfitPrice (strictly above entry).",
  "  The entry reference is the currentPrice returned by `binance_symbol_lookup` for that symbol — NOT any price mentioned in the upstream research.",
  "  After a buy fills, an OCO SELL is automatically placed at those two levels. Buys missing SL/TP, or with SL/TP on the wrong side of currentPrice, are silently dropped.",
  "• For SELL orders: set stopLossPrice and takeProfitPrice to null.",
  "• Never place a buy for a symbol you have not verified tradable via `binance_symbol_lookup` in this turn. If tradable:false, drop that candidate.",
  "• No defensible trade? Return mode='hold' with an empty orders array.",
  "• Final reply (after all tool calls) MUST be one JSON object matching TradingDecision — no markdown fences, no prose outside the JSON."
].join("\n");

// System prelude removed — the user's written prompt is now the entire system prompt for research.

export const DEFAULT_FORMATTER_BODY = [
  "You are the execution stage (phase 2) for one autonomous Binance spot bot (quoted in USDT or USDC — both count as cash).",
  "",
  "You have a tool available: `binance_symbol_lookup(symbols: string[])`. Pass bare bases ('NEIRO') or full pairs ('BTCUSDT','NEIROUSDC'); the tool returns the best tradable stable-quoted pair (USDT preferred, USDC fallback). ALWAYS use the canonical `symbol` from the response when placing the order — e.g. if you asked for 'NEIRO' and got back {symbol:'NEIROUSDC'}, your order.symbol must be 'NEIROUSDC'. Pass ONLY the specific tickers you are considering; one call with up to 10 symbols is enough — do not waste iterations.",
  "",
  "Inputs (in the user message):",
  "- UPSTREAM RESEARCH: qualitative thesis from phase 1. Symbols may be informal or mis-spelled; normalize to bases and let the lookup pick USDT or USDC. Any price figures mentioned there may be stale or wrong — ignore them and use currentPrice from the tool.",
  "- SESSION / EXECUTION RULES / WALLET / AUTHORIZED PAIRS: hard facts — never contradict them.",
  "- (No live prices are pre-injected. Always fetch via the tool.)",
  "",
  "Workflow:",
  "1. Read the research output and list the candidate bases.",
  "2. If the bot has an AUTHORIZED PAIRS list, discard candidates not in it.",
  "3. Call `binance_symbol_lookup` once with the surviving candidates.",
  "4. Drop any returned with tradable:false.",
  "5. For each remaining symbol, use the canonical `symbol` returned (may be USDT or USDC). Size orders with the tool's currentPrice. Compute stopLossPrice strictly below and takeProfitPrice strictly above that price, respecting tickSize.",
  "6. Respect wallet + execution caps. Prefer fewer, higher-conviction orders.",
  "7. If after all filtering no order survives, return mode='hold' with orders: [].",
  "",
  "Output: exactly one JSON object (no markdown fences, no prose) matching TradingDecision:",
  '- mode: one of "rebalance" | "enter" | "exit" | "hold" | "adjust".',
  "- rationaleSummary: <=600 chars, decision-grade summary.",
  "- globalRationale: <=4000 chars tying research + tool-returned facts to orders (or explaining why flat).",
  "- confidence: number in [0,1].",
  "- timeHorizon: short string or null.",
  "- orders: array (<= max orders/run). Each: symbol, side buy|sell, type market|limit, quantity (>0), limitPrice (null unless limit), stopLossPrice, takeProfitPrice, rationale.",
  "- targetAllocations: usually []."
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
      ? `Max orders/run: ${exec.maxOrdersPerRun} | Max notional/order: $${exec.maxNotionalPerOrderUsd}`
      : `Configured caps (not enforced while relaxed): max ${exec.maxOrdersPerRun} orders/run, $${exec.maxNotionalPerOrderUsd}/order — total spend still cannot exceed budget and venue rules apply.`,
    exec.enabled ? `Cash reserve (untouchable): $${exec.minCashReserveUsd}` : "",
    `Allowed types: ${allowedTypes}`
  ]
    .filter(Boolean)
    .join("\n");
};

const buildTradingScopeSection = (runtimeConfig: BotSetup["runtimeConfig"]) => {
  if (runtimeConfig.symbolScope === "selected" && runtimeConfig.contextSymbols.length > 0) {
    return ["=== AUTHORIZED PAIRS — trade ONLY these ===", runtimeConfig.contextSymbols.join(", ")].join("\n");
  }
  return "=== TRADING SCOPE ===\nYou may trade ANY stable-quoted spot pair available on Binance (USDT or USDC; USDT preferred, USDC fallback). Pick your symbols based on your own analysis.";
};

// Live prices are no longer pre-injected into the trader prompt.
// The trader fetches authoritative prices on-demand via the `binance_symbol_lookup` tool.

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

/** Phase 2: trader context with research text + wallet + rules + optional modules.
 *  Live prices are deliberately NOT injected — the trader fetches them via binance_symbol_lookup. */
const buildFormatterUserSections = (input: {
  bot: BotSetup;
  venueContext: VenueContext;
  researchRawText: string;
  historyContext: HistoryContext;
}) => {
  const { bot, venueContext, researchRawText, historyContext } = input;
  const { runtimeConfig } = bot;
  const { snapshot } = venueContext;

  const sections: string[] = [];

  sections.push(
    ["=== UPSTREAM RESEARCH (phase 1 analysis) ===", researchRawText].join("\n")
  );
  sections.push(buildSessionSection(bot));
  sections.push(buildExecRulesSection(runtimeConfig.execution));
  sections.push(buildWalletSection(snapshot));
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

  // Grounding block is xAI-specific: only xAI research runs through the Responses
  // API with web_search/x_search, so only xAI needs the "cite only what you just
  // retrieved" guardrails. Other providers don't have browsing wired in and the
  // block would mislead them.
  const parts = [bot.promptBody.trim()];
  if (bot.modelProvider === "xai") parts.push(RESEARCH_GROUNDING_BLOCK);
  const systemPrompt = parts.join("\n\n");
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
  candidateSymbols
}: BuildPromptContextInput & {
  researchRawText: string;
  candidateSymbols: string[];
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
