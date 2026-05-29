// module: Build compact runtime context + grounding blocks for prompts.
import { isUsdcOnlyVenue, type VenueContext } from "../adapters/binance.js";
import {
  getBotPrePromptContext,
  getActiveVenueTraderPrompt,
  getAppSettings,
  type BotSetup
} from "../lib/store.js";

const fmtUsd = (n: number) =>
  `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const fmtNum = (n: number) =>
  n.toLocaleString("en-US", { maximumSignificantDigits: 8, useGrouping: false });

export const renderRuntimeTemplate = (template: string) =>
  template.replaceAll("{date}", new Date().toISOString().slice(0, 10));

const heading = (label: string | undefined, fallback: string) =>
  `=== ${(label?.trim() || fallback).toUpperCase()} ===`;

export const DEFAULT_NON_NEGOTIABLE_CONSTRAINTS_BLOCK = [
  "---",
  "HARD RULES:",
  "- Buy only symbols verified this turn with tradability_resolve or binance_symbol_lookup; use the returned canonical symbol and currentPrice.",
  "- Resolve only the strongest few ideas. Do not ask for, print, or enumerate the full venue universe.",
  "- BUY: stopLossPrice < currentPrice and takeProfitPrice > currentPrice. SELL: both null.",
  "- If no valid trade survives, return hold with orders: [].",
  "- Final answer: one TradingDecision JSON object, no markdown or prose."
].join("\n");

// System prelude removed — the user's written prompt is now the entire system prompt for research.

export const DEFAULT_TRADER_BODY = [
  "You are phase 2 for one Binance spot bot. Convert the research text into a valid TradingDecision JSON object.",
  "Live Binance uses USDC pairs only. Testnet/dev may use USDT or USDC. Treat USDT and USDC as cash.",
  "Select at most 3 concrete trade ideas from the research, then resolve only those specific assets with tradability_resolve or binance_symbol_lookup.",
  "Use returned currentPrice, tickSize, stepSize, and canonical symbol. Ignore stale prices from research.",
  "If a research idea is not executable on this venue, do not force it. Either resolve a close venue-executable substitute with a clear rationale, or hold.",
  "Respect the injected wallet, authorized pairs, order caps, reserve, and allowed order types. Prefer fewer high-conviction orders.",
  "If nothing is defensible after validation, return mode='hold' with orders: [].",
  "Output exactly one JSON object with: mode, rationaleSummary, globalRationale, confidence, timeHorizon, orders, targetAllocations."
].join("\n");

type HistoryContext = Awaited<ReturnType<typeof getBotPrePromptContext>>;

/** Shared helpers for building wallet and price sections used by both phases. */

const buildWalletSection = (snapshot: VenueContext["snapshot"], label?: string) => {
  const lines = [heading(label, "WALLET"), `Total: ${fmtUsd(snapshot.totalUsdValue)}`];
  for (const b of snapshot.balances) {
    const usd = b.usdValue != null ? ` (${fmtUsd(b.usdValue)})` : "";
    const locked = b.locked > 0 ? ` + ${fmtNum(b.locked)} locked` : "";
    lines.push(`${b.asset}: ${fmtNum(b.free)} free${locked}${usd}`);
  }
  return lines.join("\n");
};

const buildSessionSection = (bot: BotSetup, label?: string) => [
  heading(label, "SESSION"),
  `Bot: ${bot.name} (#${bot.botNumber}) | Model: ${bot.traderModelProfileName}`,
  `Venue: ${venueLabel(bot.runtimeConfig.venue)} (${bot.runtimeConfig.venue}, ${bot.runtimeConfig.assetClass}) | Frequency: every ${bot.runtimeConfig.frequencyMinutes}min`,
  `Budget: ${fmtUsd(bot.runtimeConfig.budgetUsdt)} — you must stay within this allocation`
].join("\n");

const buildExecRulesSection = (exec: BotSetup["runtimeConfig"]["execution"], label?: string) => {
  const drawdownRule = exec.maxDrawdownEnabled
    ? `Max drawdown before bot kill: ${exec.maxDrawdownPct}%`
    : "Max drawdown kill: OFF";
  // When rules are disabled, deliberately do NOT surface the configured
  // max-orders-per-run / max-notional numbers: the model will anchor on them
  // and produce baskets of exactly that size even though nothing is enforced.
  // Only mention the caps when they're actually live.
  if (!exec.enabled) {
    return [
      heading(label, "EXECUTION RULES"),
      "Order caps: OFF — no order-count or per-order notional caps.",
      drawdownRule,
      "Size and count of orders are up to your judgment. Total spend is still bounded by the bot's budget and by available wallet balance; Binance tradability rules (min notional, lot size) still apply.",
      "Allowed order types: MARKET, LIMIT"
    ].join("\n");
  }

  const allowedTypes = [exec.allowMarketOrders && "MARKET", exec.allowLimitOrders && "LIMIT"]
    .filter(Boolean)
    .join(", ");
  return [
    heading(label, "EXECUTION RULES"),
    "Order caps: ON",
    `Max orders/run: ${exec.maxOrdersPerRun} | Max notional/order: $${exec.maxNotionalPerOrderUsd}`,
    `Cash reserve (untouchable): $${exec.minCashReserveUsd}`,
    drawdownRule,
    `Allowed types: ${allowedTypes}`
  ].join("\n");
};

const buildTradingScopeSection = (runtimeConfig: BotSetup["runtimeConfig"], label?: string) => {
  if (runtimeConfig.symbolScope === "selected" && runtimeConfig.contextSymbols.length > 0) {
    return [heading(label, "AUTHORIZED PAIRS - trade ONLY these"), runtimeConfig.contextSymbols.join(", ")].join("\n");
  }
  const scope = isUsdcOnlyVenue(runtimeConfig.venue)
    ? "any USDC-quoted spot pair available on Binance live (USDT pairs are NOT tradable in this region — use USDC only)"
    : "any stable-quoted spot pair available on Binance (USDC preferred, USDT fallback)";
  return `${heading(label, "TRADING SCOPE")}\nYou may trade ${scope}. Pick your symbols based on your own analysis.`;
};

// Live prices are no longer pre-injected into the trader prompt.
// The trader fetches authoritative prices on-demand via the `binance_symbol_lookup` tool.

const venueLabel = (venue: BotSetup["runtimeConfig"]["venue"]) =>
  venue === "binance-testnet" ? "Binance Testnet"
    : venue === "binance" ? "Binance"
      : venue === "ibkr-paper" ? "IBKR Paper"
        : "IBKR";

const buildResearchVenueBrief = (bot: BotSetup) => {
  const { runtimeConfig } = bot;
  const base = [
    "---",
    "VENUE BRIEF:",
    `- This bot trades on ${venueLabel(runtimeConfig.venue)}.`,
    `- Asset class: ${runtimeConfig.assetClass}.`,
    "- Do not ask for or print a full tradable-universe list.",
    "- Research broadly, but when naming a trade idea, include the asset/ticker plainly so the trader can resolve it deterministically before execution."
  ];

  if (runtimeConfig.venue === "binance") {
    base.push("- Binance live in this app is USDC-quoted spot only; USDT spot pairs are not executable here.");
  } else if (runtimeConfig.venue === "binance-testnet") {
    base.push("- Binance Testnet supports sandbox spot execution; the trader will verify exact USDT/USDC pair availability.");
  } else {
    base.push("- IBKR execution is prepared but not enabled yet; equity ideas should be stored as research/signals until the paper adapter is active.");
  }

  if (runtimeConfig.symbolScope === "selected") {
    const selected = runtimeConfig.contextSymbols.filter((symbol) => symbol !== "__ALL__");
    if (selected.length > 0 && selected.length <= 12) {
      base.push(`- This selected-pair bot is constrained to: ${selected.join(", ")}.`);
    } else if (selected.length > 12) {
      base.push(`- This selected-pair bot has ${selected.length} authorized symbols; do not print the full list.`);
    }
  }

  return base.join("\n");
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

/** Build optional module sections (used by the trader phase). */
const buildOptionalModuleSections = (input: {
  bot: BotSetup;
  venueContext: VenueContext;
  historyContext: HistoryContext;
  templates: Record<string, { label: string }>;
}) => {
  const { bot, venueContext, historyContext, templates } = input;
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
        heading(templates.includeWalletOverview?.label, "PORTFOLIO OVERVIEW"),
        `Started: ${start} | Now: ${now}${pnlNet}`,
        `Runs: ${p.runCount ?? 0} | Trades: ${p.tradeCount ?? 0} | Fees: ${fmtUsd(p.totalFeesUsd ?? 0)}`
      ].join("\n")
    );
  }

  if (modules.includePerformanceStats && historyContext.performance) {
    sections.push(
      [heading(templates.includePerformanceStats?.label, "PERFORMANCE STATS"), JSON.stringify(historyContext.performance, null, 2)].join("\n")
    );
  }

  if (modules.includePastTrades && historyContext.pastTrades?.length) {
    const tradeLines = (historyContext.pastTrades as Array<Record<string, unknown>>).map(
      (t) =>
        `${String(t.side ?? "").toUpperCase()} ${t.symbol} qty=${t.executedQuantity ?? t.requestedQuantity} @ ${t.averageFillPrice ?? "?"} → ${t.status}`
    );
    sections.push(
      [heading(templates.includePastTrades?.label, "RECENT TRADES"), `Lookback: last ${modules.pastTradesLookback}`, ...tradeLines].join("\n")
    );
  }

  if (modules.includeBotRanking && historyContext.ranking?.length) {
    const rankLines = (historyContext.ranking as Array<Record<string, unknown>>)
      .slice(0, 10)
      .map((r, i) => `${i + 1}. ${r.botName ?? r.name ?? "Bot"}: ${fmtUsd(Number(r.netPnlUsd ?? 0))} net PnL`);
    sections.push([heading(templates.includeBotRanking?.label, "BOT RANKINGS"), ...rankLines].join("\n"));
  }

  return sections;
};

/** Phase 2: trader context with research text + wallet + rules + optional modules.
 *  Live prices are deliberately NOT injected — the trader fetches them via binance_symbol_lookup. */
const buildTraderUserSections = (input: {
  bot: BotSetup;
  venueContext: VenueContext;
  researchRawText: string;
  historyContext: HistoryContext;
  templates: Record<string, { label: string }>;
}) => {
  const { bot, venueContext, researchRawText, historyContext, templates } = input;
  const { runtimeConfig } = bot;
  const { snapshot } = venueContext;

  const sections: string[] = [];

  sections.push(
    [heading(templates.traderResearchOutput?.label, "UPSTREAM RESEARCH (phase 1 analysis)"), researchRawText].join("\n")
  );
  sections.push(buildSessionSection(bot, templates.traderSession?.label));
  sections.push(buildExecRulesSection(runtimeConfig.execution, templates.traderExecutionRules?.label));
  sections.push(buildWalletSection(snapshot, templates.traderWallet?.label));
  sections.push(buildTradingScopeSection(runtimeConfig, templates.traderTradingScope?.label));

  // Append optional data modules (toggled on bot creation form)
  const moduleSections = buildOptionalModuleSections({ bot, venueContext, historyContext, templates });
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
  const appSettings = await getAppSettings();
  const groundingBlock = renderRuntimeTemplate(appSettings.promptRuntime.researchGroundingRules).trim();

  const parts = [bot.promptBody.trim()];
  parts.push(buildResearchVenueBrief(bot));
  if (groundingBlock) parts.push(groundingBlock);
  const systemPrompt = parts.join("\n\n");
  const userMessage = "Analyze the market now. Identify any trading opportunities worth exploring.";

  const compactContext: Record<string, unknown> = {
    phase: "research",
    venue: runtimeConfig.venue,
    symbolScope: runtimeConfig.symbolScope,
    walletTotalUsd: venueContext.snapshot.totalUsdValue,
    balanceCount: venueContext.snapshot.balances.length,
    modulesActive: []
  };

  return { systemPrompt, userMessage, compactContext };
};

/** Phase 2: trader + hard constraints; includes all injected data. */
export const buildTraderPhaseContext = async ({
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
  const appSettings = await getAppSettings();

  const historyContext = await getBotPrePromptContext({
    botId: bot.id,
    pastTradesLookback: modules.pastTradesLookback
  });

  // Use bot's own trader prompt if set; fall back to venue-level trader prompt; then default
  const botTraderBody = bot.traderPromptBody?.trim() ?? "";
  let traderBody: string;
  let traderPromptVersionId: string | null = null;

  if (botTraderBody.length > 0) {
    traderBody = botTraderBody;
    traderPromptVersionId = bot.traderPromptVersionId ?? null;
  } else {
    const activeVenueTrader = await getActiveVenueTraderPrompt(runtimeConfig.venue);
    const trimmedCustom = activeVenueTrader?.body?.trim() ?? "";
    traderBody = trimmedCustom.length > 0 ? trimmedCustom : DEFAULT_TRADER_BODY;
    traderPromptVersionId = activeVenueTrader?.id ?? null;
  }

  const nonNegotiable = appSettings.promptRuntime.injectedDataTemplates.traderNonNegotiable.preview.trim() ||
    DEFAULT_NON_NEGOTIABLE_CONSTRAINTS_BLOCK;
  const systemPrompt = [traderBody, renderRuntimeTemplate(nonNegotiable)].join("\n\n");

  const userMessage = buildTraderUserSections({
    bot,
    venueContext,
    researchRawText,
    historyContext,
    templates: appSettings.promptRuntime.injectedDataTemplates
  });

  const compactContext: Record<string, unknown> = {
    phase: "trader",
    venue: runtimeConfig.venue,
    symbolScope: runtimeConfig.symbolScope,
    walletTotalUsd: venueContext.snapshot.totalUsdValue,
    candidateSymbols,
    modulesActive: []
  };

  return {
    systemPrompt,
    userMessage,
    compactContext,
    traderPromptVersionId
  };
};
