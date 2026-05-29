// module: Settings + prompt/trader-prompt CRUD routes.
import { Router, type Router as ExpressRouter } from "express";
import {
  addPromptVersion,
  addTraderPromptVersion,
  createVenueTraderPromptVersion,
  createPrompt,
  createTraderPrompt,
  getAllActiveVenueTraderPrompts,
  getAppSettings,
  getPromptVersionBody,
  listVenueTraderPromptVersions,
  listPrompts,
  listTraderPrompts,
  setAppSettings
} from "../lib/store.js";

export const settingsRouter: ExpressRouter = Router();

settingsRouter.get("/settings/venue-trader-prompt", async (_request, response, next) => {
  try {
    response.json({ venueTraderPrompts: await getAllActiveVenueTraderPrompts() });
  } catch (error) {
    next(error);
  }
});

settingsRouter.get("/settings/app", async (_request, response, next) => {
  try {
    response.json(await getAppSettings());
  } catch (error) {
    next(error);
  }
});

settingsRouter.put("/settings/app", async (request, response, next) => {
  try {
    response.json(await setAppSettings(request.body));
  } catch (error) {
    next(error);
  }
});

settingsRouter.put("/settings/venue-trader-prompt", async (request, response, next) => {
  try {
    const body = request.body as { venueTraderPrompts?: unknown };
    const raw = body?.venueTraderPrompts;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      response.status(400).json({ error: "venueTraderPrompts object required" });
      return;
    }
    const o = raw as Record<string, unknown>;
    if (typeof o.binance !== "string" || typeof o["binance-testnet"] !== "string") {
      response.status(400).json({
        error: "venueTraderPrompts must include string fields binance and binance-testnet"
      });
      return;
    }
    if (o.binance.length > 12000 || o["binance-testnet"].length > 12000) {
      response.status(400).json({ error: "Each trader prompt may be at most 12000 characters" });
      return;
    }
    if (o.binance.trim().length > 0) {
      await createVenueTraderPromptVersion("binance", o.binance.trim());
    }
    if (o["binance-testnet"].trim().length > 0) {
      await createVenueTraderPromptVersion("binance-testnet", o["binance-testnet"].trim());
    }
    response.json({ ok: true, venueTraderPrompts: await getAllActiveVenueTraderPrompts() });
  } catch (error) {
    next(error);
  }
});

settingsRouter.get("/settings/venue-trader-prompt/:venue/versions", async (request, response, next) => {
  try {
    const venue = request.params.venue;
    if (venue !== "binance" && venue !== "binance-testnet") {
      response.status(404).json({ error: "Venue not found" });
      return;
    }
    const versions = await listVenueTraderPromptVersions(venue);
    response.json({ venue, versions });
  } catch (error) {
    next(error);
  }
});

settingsRouter.get("/prompts", async (_request, response, next) => {
  try {
    response.json(await listPrompts());
  } catch (error) {
    next(error);
  }
});

settingsRouter.post("/prompts", async (request, response, next) => {
  try {
    const { name, slug, initialBody } = request.body;
    const result = await createPrompt({ name, slug, initialBody });
    response.json(result);
  } catch (error) {
    next(error);
  }
});

settingsRouter.get("/prompts/versions/:versionId/body", async (request, response, next) => {
  try {
    const version = await getPromptVersionBody(request.params.versionId);
    if (!version) {
      response.status(404).json({ error: "Prompt version not found" });
      return;
    }
    response.json(version);
  } catch (error) {
    next(error);
  }
});

settingsRouter.post("/prompts/:promptId/versions", async (request, response, next) => {
  try {
    const { body } = request.body;
    if (!body || typeof body !== "string" || !body.trim()) {
      response.status(400).json({ error: "body is required" });
      return;
    }
    const result = await addPromptVersion({ promptId: request.params.promptId, body: body.trim() });
    response.json(result);
  } catch (error) {
    next(error);
  }
});

settingsRouter.get("/trader-prompts", async (_request, response, next) => {
  try {
    response.json(await listTraderPrompts());
  } catch (error) {
    next(error);
  }
});

settingsRouter.post("/trader-prompts", async (request, response, next) => {
  try {
    const { name, slug, initialBody } = request.body;
    if (!initialBody || typeof initialBody !== "string" || !initialBody.trim()) {
      response.status(400).json({ error: "initialBody is required" });
      return;
    }
    const result = await createTraderPrompt({ name, slug, initialBody: initialBody.trim() });
    response.json(result);
  } catch (error) {
    next(error);
  }
});

settingsRouter.post("/trader-prompts/:promptId/versions", async (request, response, next) => {
  try {
    const { body } = request.body;
    if (!body || typeof body !== "string" || !body.trim()) {
      response.status(400).json({ error: "body is required" });
      return;
    }
    const result = await addTraderPromptVersion({ promptId: request.params.promptId, body: body.trim() });
    response.json(result);
  } catch (error) {
    next(error);
  }
});
