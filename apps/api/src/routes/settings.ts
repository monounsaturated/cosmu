// module: Settings + prompt/trader-prompt CRUD routes.
import { Router, type Router as ExpressRouter } from "express";
import {
  addPromptVersion,
  createFormatterPromptVersion,
  createPrompt,
  createTraderPrompt,
  getAllActiveFormatterPrompts,
  getAppSettings,
  getPromptVersionBody,
  listFormatterPromptVersions,
  listPrompts,
  listTraderPrompts,
  setAppSettings
} from "../lib/store.js";

export const settingsRouter: ExpressRouter = Router();

settingsRouter.get("/settings/formatter-prompt", async (_request, response, next) => {
  try {
    response.json({ formatterPrompts: await getAllActiveFormatterPrompts() });
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

settingsRouter.put("/settings/formatter-prompt", async (request, response, next) => {
  try {
    const body = request.body as { formatterPrompts?: unknown };
    const raw = body?.formatterPrompts;
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      response.status(400).json({ error: "formatterPrompts object required" });
      return;
    }
    const o = raw as Record<string, unknown>;
    if (typeof o.binance !== "string" || typeof o["binance-testnet"] !== "string") {
      response.status(400).json({
        error: "formatterPrompts must include string fields binance and binance-testnet"
      });
      return;
    }
    if (o.binance.length > 12000 || o["binance-testnet"].length > 12000) {
      response.status(400).json({ error: "Each formatter prompt may be at most 12000 characters" });
      return;
    }
    if (o.binance.trim().length > 0) {
      await createFormatterPromptVersion("binance", o.binance.trim());
    }
    if (o["binance-testnet"].trim().length > 0) {
      await createFormatterPromptVersion("binance-testnet", o["binance-testnet"].trim());
    }
    response.json({ ok: true, formatterPrompts: await getAllActiveFormatterPrompts() });
  } catch (error) {
    next(error);
  }
});

settingsRouter.get("/settings/formatter-prompt/:venue/versions", async (request, response, next) => {
  try {
    const venue = request.params.venue;
    if (venue !== "binance" && venue !== "binance-testnet") {
      response.status(404).json({ error: "Venue not found" });
      return;
    }
    const versions = await listFormatterPromptVersions(venue);
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
