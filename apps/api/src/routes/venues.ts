// module: Venue routes — symbol catalog, connection status, balance/capacity.
import { Router, type Router as ExpressRouter } from "express";
import { sql } from "../db.js";
import { getVenueSymbols } from "../services/catalog.js";
import { checkVenueConnection, getVenueConnectionStatuses, parseVenueId } from "../services/venues.js";

export const venuesRouter: ExpressRouter = Router();

venuesRouter.get("/venues/:venue/symbols", async (request, response, next) => {
  try {
    const venue = parseVenueId(request.params.venue);
    if (!venue) {
      response.status(404).json({ error: "Venue not found" });
      return;
    }

    response.json({
      venue,
      label: venue === "binance-testnet" ? "Binance Testnet" : "Binance",
      symbols: await getVenueSymbols(venue, request.query.force === "true")
    });
  } catch (error) {
    next(error);
  }
});

venuesRouter.get("/venues/status", async (request, response, next) => {
  try {
    response.json({
      checkedAt: new Date().toISOString(),
      venues: await getVenueConnectionStatuses({ force: request.query.force === "true" })
    });
  } catch (error) {
    next(error);
  }
});

venuesRouter.get("/venues/:venue/balance", async (request, response, next) => {
  try {
    const venue = parseVenueId(request.params.venue);
    if (!venue) {
      response.status(404).json({ error: "Venue not found" });
      return;
    }

    const status = await checkVenueConnection(venue, { force: request.query.force === "true" });

    const allocatedBudgets = await sql<{ total: string }[]>`
      select coalesce(sum(budget_usdt), 0)::text as total
      from bot_runtime_configs
      where venue = ${venue}
        and enabled = true
    `;
    const allocatedUsdt = Number(allocatedBudgets[0]?.total ?? 0);
    const totalFreeUsdt = status.balance?.totalFreeUsdt ?? 0;

    response.json({
      venue,
      label: status.label,
      mode: status.mode,
      configured: status.configured,
      connected: status.connected,
      checkedAt: status.checkedAt,
      error: status.error,
      totalFreeUsdt,
      allocatedUsdt,
      availableUsdt: Math.max(0, totalFreeUsdt - allocatedUsdt)
    });
  } catch (error) {
    next(error);
  }
});
