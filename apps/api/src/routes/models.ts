// module: Model profile routes — list/create profiles + provider catalog sync.
import { Router, type Router as ExpressRouter } from "express";
import { listXaiModels } from "../providers/xai.js";
import {
  BOOTSTRAP_ANTHROPIC_PROFILES,
  BOOTSTRAP_GOOGLE_PROFILES,
  BOOTSTRAP_HUGGINGFACE_PROFILES,
  BOOTSTRAP_MISTRAL_PROFILES,
  BOOTSTRAP_NOUS_PROFILES,
  BOOTSTRAP_OPENAI_PROFILES,
  BOOTSTRAP_XAI_PROFILES,
  SUPPORTED_MODEL_PROVIDERS,
  bootstrapModelProfiles,
  modelProviderLabel,
  syncAllProviderModels,
  syncProviderModels
} from "../services/catalog.js";
import { createModelProfile, listModelProfiles } from "../lib/store.js";

export const modelsRouter: ExpressRouter = Router();

const ALWAYS_KEEP_XAI_MODEL_IDS = new Set(["grok-4.3"]);

modelsRouter.get("/models", async (request, response, next) => {
  try {
    const provider = typeof request.query.provider === "string" ? request.query.provider : undefined;
    let liveXaiModelIds: Set<string> | null = null;
    let liveXaiModels: Array<{ id: string; created: number | null }> = [];
    const providersToSync = provider ? [provider] : [...SUPPORTED_MODEL_PROVIDERS];

    for (const providerName of providersToSync) {
      try {
        await syncProviderModels(providerName);
      } catch (syncError) {
        console.warn(`${providerName} sync failed:`, String(syncError));
      }
    }

    try {
      await bootstrapModelProfiles();
    } catch (bootstrapError) {
      console.warn("Model bootstrap failed:", String(bootstrapError));
    }

    if (!provider || provider === "xai") {
      try {
        liveXaiModels = await listXaiModels();
        liveXaiModelIds = new Set(liveXaiModels.map((model) => model.id));
      } catch (liveCatalogError) {
        console.warn("xAI live catalog check failed, serving cached profiles:", String(liveCatalogError));
      }
    }

    let profiles: Array<Record<string, unknown>>;
    try {
      profiles = await listModelProfiles(provider) as Array<Record<string, unknown>>;
    } catch (dbError) {
      console.warn("DB query for model profiles failed, building response from xAI live catalog:", String(dbError));
      if (liveXaiModels.length > 0 && (!provider || provider === "xai")) {
        profiles = liveXaiModels.map((m) => ({
          id: `live:xai:${m.id}`,
          name: `xAI ${m.id}`,
          provider: "xai",
          model: m.id,
          settings: { temperature: 0.2 }
        }));
        response.json(profiles);
        return;
      }
      const fallback = BOOTSTRAP_XAI_PROFILES.map((p) => ({
        id: `fallback:xai:${p.model}`,
        name: p.name,
        provider: "xai",
        model: p.model,
        settings: { temperature: 0.2 }
      })).concat(BOOTSTRAP_NOUS_PROFILES.map((p) => ({
        id: `fallback:nous:${p.model}`,
        name: p.name,
        provider: "nous",
        model: p.model,
        settings: { temperature: 0.2 }
      }))).concat(BOOTSTRAP_OPENAI_PROFILES.map((p) => ({
        id: `fallback:openai:${p.model}`,
        name: p.name,
        provider: "openai",
        model: p.model,
        settings: { temperature: 0.2 }
      }))).concat(BOOTSTRAP_ANTHROPIC_PROFILES.map((p) => ({
        id: `fallback:anthropic:${p.model}`,
        name: p.name,
        provider: "anthropic",
        model: p.model,
        settings: { temperature: 0.2 }
      }))).concat(BOOTSTRAP_GOOGLE_PROFILES.map((p) => ({
        id: `fallback:google:${p.model}`,
        name: p.name,
        provider: "google",
        model: p.model,
        settings: { temperature: 0.2 }
      }))).concat(BOOTSTRAP_MISTRAL_PROFILES.map((p) => ({
        id: `fallback:mistral:${p.model}`,
        name: p.name,
        provider: "mistral",
        model: p.model,
        settings: { temperature: 0.2 }
      }))).concat(BOOTSTRAP_HUGGINGFACE_PROFILES.map((p) => ({
        id: `fallback:huggingface:${p.model}`,
        name: p.name,
        provider: "huggingface",
        model: p.model,
        settings: { temperature: 0.2 }
      })));
      response.json(fallback);
      return;
    }

    if (provider === "xai" && liveXaiModelIds && liveXaiModelIds.size > 0) {
      response.json(profiles.filter((profile) => liveXaiModelIds!.has(String(profile.model)) || ALWAYS_KEEP_XAI_MODEL_IDS.has(String(profile.model))));
      return;
    }

    if (!provider && liveXaiModelIds && liveXaiModelIds.size > 0) {
      response.json(
        profiles.filter((profile) => profile.provider !== "xai" || liveXaiModelIds!.has(String(profile.model)) || ALWAYS_KEEP_XAI_MODEL_IDS.has(String(profile.model)))
      );
      return;
    }

    response.json(profiles);
  } catch (error) {
    next(error);
  }
});

modelsRouter.post("/models", async (request, response, next) => {
  try {
    const { name, provider, model, settings } = request.body;
    const id = await createModelProfile({ name, provider, model, settings });
    response.json({ id });
  } catch (error) {
    next(error);
  }
});

modelsRouter.post("/internal/catalog/sync", async (request, response, next) => {
  try {
    const force = request.query.force === "true";
    const provider = typeof request.query.provider === "string" ? request.query.provider : "all";
    const catalogSync = provider === "all"
      ? await syncAllProviderModels(force)
      : {
          syncedAt: new Date().toISOString(),
          force,
          providers: [{
            provider,
            label: modelProviderLabel(provider),
            ...(await syncProviderModels(provider, force))
          }],
          bootstrap: await bootstrapModelProfiles()
        };

    const models = await listModelProfiles(provider === "all" ? undefined : provider);

    response.json({
      ok: true,
      provider,
      modelCount: models.length,
      syncedAt: catalogSync.syncedAt,
      sync: catalogSync.providers,
      bootstrap: catalogSync.bootstrap,
      models: models.map(m => ({ id: m.id, name: m.name, provider: m.provider, model: m.model }))
    });
  } catch (error) {
    next(error);
  }
});
