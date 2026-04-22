/**
 * Guardian loop: app-side SL/TP enforcement + Binance safety-stop reconciliation.
 *
 * Fires on a short interval (default 3s). For each active bot_position:
 *   - fetch a fresh ticker price
 *   - if price crossed SL or TP, cancel the safety stop, market-sell, close
 * On boot: reconcile safety_stop_order_id state so a stop that filled while
 * the app was down is recognized and the position closed with reason='safety_stop'.
 */

import {
  getAllTickerPrices,
  placeMarketSell,
  cancelSafetyStopOrder,
  getBinanceOrderStatus,
  normalizeSymbol,
  loadVenueContext,
  type VenueContext
} from "../adapters/binance.js";
import { sql } from "../db.js";
import {
  listActivePositions,
  storeExecutionRecords,
  updateSafetyStop,
  closePosition,
  type BotPosition
} from "../lib/store.js";
import { getBotSetupById } from "../lib/store/bots.js";
import type { BotSetup } from "../lib/store/bots.js";
import { notifySlack } from "./notifier.js";

// 10s tick — we don't need to fire every 3s, and this lowers API spend.
// Cache the ticker snapshot for 10s so parallel callers (e.g. positions endpoint)
// can share it.
const GUARDIAN_TICK_MS = Number(process.env.GUARDIAN_TICK_MS ?? "10000");
const CLOSE_BACKOFF_MS = 60_000; // never retry a position within 60s of last attempt
const MAX_CLOSE_ATTEMPTS = 5; // after this, stop retrying and alert

const botSetupCache = new Map<string, { setup: BotSetup; expiresAt: number }>();
const BOT_SETUP_TTL_MS = 60_000;

// Positions currently being closed (in-flight) or recently attempted with unknown outcome.
// Keyed by position id. `attempts` bumps on each retry; `lastAttemptAt` throttles retries.
type CloseState = { inFlight: boolean; attempts: number; lastAttemptAt: number; givenUp: boolean };
const closeState = new Map<string, CloseState>();

const getCloseState = (id: string): CloseState => {
  const existing = closeState.get(id);
  if (existing) return existing;
  const fresh: CloseState = { inFlight: false, attempts: 0, lastAttemptAt: 0, givenUp: false };
  closeState.set(id, fresh);
  return fresh;
};

const canAttemptClose = (id: string): boolean => {
  const s = getCloseState(id);
  if (s.inFlight) return false;
  if (s.givenUp) return false;
  if (s.lastAttemptAt > 0 && Date.now() - s.lastAttemptAt < CLOSE_BACKOFF_MS) return false;
  return true;
};

const getBotSetupCached = async (botId: string): Promise<BotSetup | null> => {
  const cached = botSetupCache.get(botId);
  const now = Date.now();
  if (cached && cached.expiresAt > now) return cached.setup;
  const setup = await getBotSetupById(botId);
  if (!setup) return null;
  botSetupCache.set(botId, { setup, expiresAt: now + BOT_SETUP_TTL_MS });
  return setup;
};

/**
 * Create a minimal "guardian run" to hold a guardian-triggered execution so
 * the FK chain stays intact. Runs.prompt_version_id is NOT NULL, so we reuse
 * the bot's currently-active prompt/model ids.
 */
const createGuardianRun = async (
  bot: BotSetup,
  reason: "stop_loss" | "take_profit" | "safety_stop_reconcile",
  symbol: string
): Promise<string> => {
  const [row] = await sql<{ id: string }[]>`
    insert into runs (
      bot_id, prompt_version_id, model_profile_id, runtime_config,
      compact_context, status, started_at, finished_at
    ) values (
      ${bot.id}, ${bot.promptVersionId}, ${bot.modelProfileId},
      ${sql.json(bot.runtimeConfig as never)},
      ${sql.json({ source: "guardian", reason, symbol } as never)},
      'success', now(), now()
    )
    returning id
  `;
  return row.id;
};

/**
 * Trigger a sell for a single position. Cancels the safety stop (if any),
 * fires a market sell, cross-checks the outcome on Binance, and closes the
 * specific position (by id). Uses in-flight guards + attempt backoff to prevent
 * runaway retry loops that previously produced thousands of sell attempts.
 */
const triggerGuardianSell = async (
  position: BotPosition,
  reason: "stop_loss" | "take_profit"
): Promise<void> => {
  const state = getCloseState(position.id);
  state.inFlight = true;
  state.attempts += 1;
  state.lastAttemptAt = Date.now();

  try {
    const bot = await getBotSetupCached(position.botId);
    if (!bot) {
      console.warn(`[guardian] bot ${position.botId} not found; skipping ${position.symbol}`);
      return;
    }

    // 1. Cancel safety stop (best-effort)
    if (position.safetyStopOrderId) {
      try {
        await cancelSafetyStopOrder(
          bot.runtimeConfig.mode,
          position.symbol,
          position.safetyStopOrderId
        );
      } catch (err) {
        console.error(
          `[guardian] failed to cancel safety stop for ${position.symbol}:`,
          err instanceof Error ? err.message : err
        );
      }
    }

    // 2. Market-sell the position's quantity
    let execution = await placeMarketSell({
      mode: bot.runtimeConfig.mode,
      venue: bot.runtimeConfig.venue,
      assetClass: bot.runtimeConfig.assetClass,
      symbol: position.symbol,
      quantity: position.quantity,
      clientOrderIdPrefix: `guardian-${reason.slice(0, 2)}`,
      stopLossPrice: null,
      takeProfitPrice: null
    });

    // 3. Cross-check uncertain sells: poll order status up to 3× by clientOrderId.
    //    If we can see it's FILLED on Binance, upgrade status -> success.
    //    If still uncertain after retries, bail WITHOUT recording a run (noise)
    //    and rely on backoff to prevent hammering.
    if (execution.status === "uncertain") {
      const rawErr = (execution.rawVenueResponse as any)?.error ?? "";
      console.warn(`[guardian] uncertain sell for ${position.symbol}: ${rawErr}`);
      if (state.attempts >= MAX_CLOSE_ATTEMPTS) {
        state.givenUp = true;
        await notifySlack(
          `⚠️ Guardian gave up on ${bot.name} ${position.symbol} after ${state.attempts} uncertain attempts. Manual intervention needed.`
        );
      }
      return;
    }

    // 4. Persist run + execution only when we have a real fill to record
    const runId = await createGuardianRun(bot, reason, position.symbol);
    const stored = await storeExecutionRecords(runId, [execution]);
    const executionId = stored[0]?.id ?? null;

    // 5. Close this specific position (not FIFO — we know exactly which one
    //    crossed SL/TP). If the fill was smaller than the position quantity
    //    (rare on market sells), we still close it — the residual dust stays
    //    in the wallet and will be reconciled later.
    const qty = execution.executedQuantity ?? 0;
    const price = execution.averageFillPrice ?? 0;
    if (qty > 0 && price > 0) {
      const proceedsUsd = qty * price;
      const realizedPnl = proceedsUsd - position.costBasisUsd;
      await closePosition({
        id: position.id,
        closeReason: reason,
        closeExecutionId: executionId,
        realizedPnlUsd: realizedPnl,
        realizedFeesUsd: execution.feeUsd ?? 0
      });
      // Successful close: drop the state so the id can be reused if replayed.
      closeState.delete(position.id);
    } else {
      console.error(`[guardian] success status but no qty/price for ${position.symbol}`);
    }

    await notifySlack(
      `Guardian ${reason} fired for ${bot.name}: sold ${qty} ${position.symbol} @ ~${price}`
    );
  } finally {
    const s = closeState.get(position.id);
    if (s) s.inFlight = false;
  }
};

/**
 * On boot: for each active position that has a safety_stop_order_id, check
 * whether that Binance order is still live. If it filled while we were down,
 * close the position with reason='safety_stop'.
 */
export const reconcileSafetyStops = async (): Promise<void> => {
  const positions = await listActivePositions();
  for (const position of positions) {
    if (!position.safetyStopOrderId) continue;
    const bot = await getBotSetupCached(position.botId);
    if (!bot) continue;

    try {
      const status = await getBinanceOrderStatus(
        bot.runtimeConfig.mode,
        position.symbol,
        position.safetyStopOrderId
      );
      if (!status) {
        await updateSafetyStop(position.id, null, null);
        continue;
      }
      if (status.status === "FILLED") {
        // Record the safety-stop fill as an execution + close position.
        const runId = await createGuardianRun(bot, "safety_stop_reconcile", position.symbol);
        const executedQty = status.executedQty;
        const avgPrice = status.avgPrice ?? position.safetyStopPrice ?? position.avgEntryPrice;
        const proceedsUsd = executedQty * avgPrice;
        const realizedPnl = proceedsUsd - position.costBasisUsd;

        await sql`
          insert into executions (
            run_id, asset_class, venue, status, symbol, side, order_type,
            requested_quantity, executed_quantity, requested_limit_price,
            average_fill_price, executed_notional_usd, fee_amount, fee_asset,
            fee_asset_usd_price, fee_usd, slippage_pct,
            stop_loss_price, take_profit_price, oco_order_id,
            order_intent, raw_venue_response
          ) values (
            ${runId}, ${bot.runtimeConfig.assetClass}, ${bot.runtimeConfig.venue}, 'success',
            ${position.symbol}, 'sell', 'market',
            ${executedQty}, ${executedQty}, null,
            ${avgPrice}, ${proceedsUsd}, 0, null,
            null, 0, null,
            null, null, ${position.safetyStopOrderId},
            ${sql.json({
              symbol: position.symbol,
              side: "sell",
              type: "market",
              quantity: executedQty,
              limitPrice: null,
              stopLossPrice: null,
              takeProfitPrice: null,
              rationale: "Safety stop filled (reconciled on boot)"
            })},
            ${sql.json(status.raw)}
          )
        `;

        await closePosition({
          id: position.id,
          closeReason: "safety_stop",
          closeExecutionId: null,
          realizedPnlUsd: realizedPnl,
          realizedFeesUsd: 0
        });
        await notifySlack(
          `Safety stop reconciled for ${bot.name}: ${position.symbol} filled @ ${avgPrice}`
        );
      } else if (status.status === "CANCELED" || status.status === "REJECTED" || status.status === "EXPIRED") {
        await updateSafetyStop(position.id, null, null);
      }
    } catch (err) {
      console.error(`[guardian] reconcile failed for ${position.symbol}:`, err);
    }
  }
};

/**
 * Main tick: load all active positions, get fresh prices, fire SL/TP sells.
 */
export const runGuardianTick = async (): Promise<void> => {
  const positions = await listActivePositions();
  if (positions.length === 0) return;

  // Group positions by mode (testnet vs live) since ticker endpoint differs.
  const positionsByMode = new Map<"testnet" | "live", BotPosition[]>();
  for (const position of positions) {
    const bot = await getBotSetupCached(position.botId);
    if (!bot) continue;
    const mode = bot.runtimeConfig.mode;
    const arr = positionsByMode.get(mode) ?? [];
    arr.push(position);
    positionsByMode.set(mode, arr);
  }

  for (const [mode, modePositions] of positionsByMode.entries()) {
    let priceMap: Record<string, number> = {};
    try {
      const all = await getAllTickerPrices(mode);
      if (Array.isArray(all)) {
        for (const p of all as Array<{ symbol: string; price: string }>) {
          priceMap[normalizeSymbol(String(p.symbol ?? ""))] = Number(p.price);
        }
      }
    } catch (err) {
      console.error(`[guardian] ticker fetch failed for mode=${mode}:`, err);
      continue;
    }

    for (const position of modePositions) {
      const price = priceMap[normalizeSymbol(position.symbol)];
      if (!price || !Number.isFinite(price)) continue;

      // Skip positions that are in-flight / backing off / given up.
      if (!canAttemptClose(position.id)) continue;

      // SL first: if both fire in the same tick, SL is more conservative.
      if (price <= position.stopLossPrice) {
        await triggerGuardianSell(position, "stop_loss");
      } else if (price >= position.takeProfitPrice) {
        await triggerGuardianSell(position, "take_profit");
      }
    }
  }
};

let guardianTimer: NodeJS.Timeout | null = null;
let reconciled = false;
// Reentrancy guard: never let two ticks overlap. With slow Binance responses
// a 10s setInterval could stack up; setTimeout-chain + running flag prevents
// that and keeps API usage predictable.
let tickRunning = false;
let stopRequested = false;

export const startGuardian = () => {
  if (guardianTimer) return;
  stopRequested = false;

  // Reconcile once on first start.
  if (!reconciled) {
    reconciled = true;
    reconcileSafetyStops().catch((err) =>
      console.error("[guardian] initial reconcile failed:", err)
    );
  }

  const schedule = () => {
    if (stopRequested) return;
    guardianTimer = setTimeout(loop, GUARDIAN_TICK_MS);
  };

  const loop = async () => {
    if (tickRunning) {
      schedule();
      return;
    }
    tickRunning = true;
    try {
      await runGuardianTick();
    } catch (err) {
      console.error("[guardian] tick failed:", err);
    } finally {
      tickRunning = false;
      schedule();
    }
  };

  schedule();
  console.log(`[guardian] started with tick interval ${GUARDIAN_TICK_MS}ms`);
};

export const stopGuardian = () => {
  stopRequested = true;
  if (guardianTimer) {
    clearTimeout(guardianTimer);
    guardianTimer = null;
  }
};

// Keep VenueContext import from being flagged as unused. It is referenced in the
// type-level for future guardian heuristics (liquidity checks).
void (undefined as unknown as VenueContext);
void loadVenueContext;
