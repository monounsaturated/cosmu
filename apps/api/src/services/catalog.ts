// module: Tradable-symbol catalog cache sync.
import { sql } from "../db.js";
import { isBinanceVenue, listVenueSymbols } from "../adapters/binance.js";
import type { VenueId } from "./venues.js";
import { listXaiModels } from "../providers/xai.js";
import { listNousModels } from "../providers/nous.js";
import { listOpenAIModels } from "../providers/openai.js";
import { listAnthropicModels } from "../providers/anthropic.js";
import { listHuggingFaceModels } from "../providers/huggingface.js";
import { listGoogleModels } from "../providers/google.js";
import { listMistralModels } from "../providers/mistral.js";

type CatalogUpsertResult = {
  count: number;
  inserted: number;
  updated: number;
};

export type ProviderSyncResult = CatalogUpsertResult & {
  synced: boolean;
  message: string;
};

export const SUPPORTED_MODEL_PROVIDERS = ["xai", "openai", "anthropic", "google", "mistral", "huggingface", "nous"] as const;
export type SupportedModelProvider = (typeof SUPPORTED_MODEL_PROVIDERS)[number];

export const modelProviderLabel = (provider: string) =>
  provider === "xai" ? "xAI"
    : provider === "nous" ? "Nous"
      : provider === "openai" ? "OpenAI"
        : provider === "anthropic" ? "Anthropic"
          : provider === "huggingface" ? "Hugging Face"
            : provider === "google" ? "Google"
              : provider === "mistral" ? "Mistral"
                : provider;

// Known working xAI model profiles — used as seed fallback when xAI API is unreachable.
// These match the canonical names used by the sync so there are no duplicates.
export const BOOTSTRAP_XAI_PROFILES: { name: string; model: string }[] = [
  { name: "xAI grok-4.3", model: "grok-4.3" },
  { name: "xAI grok-3", model: "grok-3" },
  { name: "xAI grok-3-fast", model: "grok-3-fast" },
  { name: "xAI grok-3-mini", model: "grok-3-mini" },
  { name: "xAI grok-3-mini-fast", model: "grok-3-mini-fast" },
];

export const BOOTSTRAP_NOUS_PROFILES: { name: string; model: string }[] = [
  { name: "Nous Hermes 4 70B", model: "nousresearch/hermes-4-70b" },
  { name: "Nous Hermes 4 405B", model: "nousresearch/hermes-4-405b" },
  { name: "Nous minimax-m2.7", model: "minimax/minimax-m2.7" }
];

export const BOOTSTRAP_OPENAI_PROFILES: { name: string; model: string }[] = [
  { name: "OpenAI GPT-5.2", model: "gpt-5.2" },
  { name: "OpenAI GPT-5.2 Pro", model: "gpt-5.2-pro" },
  { name: "OpenAI GPT-5.1", model: "gpt-5.1" },
  { name: "OpenAI GPT-4.1", model: "gpt-4.1" },
  { name: "OpenAI GPT-4.1 mini", model: "gpt-4.1-mini" },
  { name: "OpenAI GPT-4o mini", model: "gpt-4o-mini" }
];

export const BOOTSTRAP_ANTHROPIC_PROFILES: { name: string; model: string }[] = [
  { name: "Anthropic Claude Opus 4.5", model: "claude-opus-4-5-20251101" },
  { name: "Anthropic Claude Opus 4.1", model: "claude-opus-4-1-20250805" },
  { name: "Anthropic Claude Sonnet 4.5", model: "claude-sonnet-4-5-20250929" },
  { name: "Anthropic Claude Sonnet 4.5 alias", model: "claude-sonnet-4-5" },
  { name: "Anthropic Claude Haiku 4.5 alias", model: "claude-haiku-4-5" }
];

export const BOOTSTRAP_GOOGLE_PROFILES: { name: string; model: string }[] = [
  { name: "Google Gemini 3 Pro Preview", model: "gemini-3-pro-preview" },
  { name: "Google Gemini 3 Flash Preview", model: "gemini-3-flash-preview" },
  { name: "Google Gemini Flash Latest", model: "gemini-flash-latest" }
];

export const BOOTSTRAP_MISTRAL_PROFILES: { name: string; model: string }[] = [
  { name: "Mistral Large 3", model: "mistral-large-2512" },
  { name: "Mistral Medium 3.5", model: "mistral-medium-latest" },
  { name: "Mistral Small 4", model: "mistral-small-latest" }
];

export const BOOTSTRAP_HUGGINGFACE_PROFILES: { name: string; model: string }[] = [
  { name: "Hugging Face DeepSeek R1 fastest", model: "deepseek-ai/DeepSeek-R1:fastest" },
  { name: "Hugging Face Qwen3 Coder cheapest", model: "Qwen/Qwen3-Coder-480B-A35B-Instruct:cheapest" }
];

export const bootstrapModelProfiles = async (): Promise<CatalogUpsertResult> => {
  let inserted = 0;
  let updated = 0;

  const profiles = [
    ...BOOTSTRAP_XAI_PROFILES.map((profile) => ({ ...profile, provider: "xai" })),
    ...BOOTSTRAP_NOUS_PROFILES.map((profile) => ({ ...profile, provider: "nous" })),
    ...BOOTSTRAP_OPENAI_PROFILES.map((profile) => ({ ...profile, provider: "openai" })),
    ...BOOTSTRAP_ANTHROPIC_PROFILES.map((profile) => ({ ...profile, provider: "anthropic" })),
    ...BOOTSTRAP_GOOGLE_PROFILES.map((profile) => ({ ...profile, provider: "google" })),
    ...BOOTSTRAP_MISTRAL_PROFILES.map((profile) => ({ ...profile, provider: "mistral" })),
    ...BOOTSTRAP_HUGGINGFACE_PROFILES.map((profile) => ({ ...profile, provider: "huggingface" }))
  ];

  for (const profile of profiles) {
    const result = await sql`
      insert into model_profiles (name, provider, model, settings)
      values (${profile.name}, ${profile.provider}, ${profile.model}, '{"temperature":0.2}'::jsonb)
      on conflict (provider, model) do update
      set
        name = excluded.name
      returning (xmax::text = '0') as inserted
    `;
    if (result[0]?.inserted) {
      inserted++;
    } else {
      updated++;
    }
  }

  console.log(`[catalog] Bootstrapped ${profiles.length} models (${inserted} new, ${updated} updated)`);
  return { count: profiles.length, inserted, updated };
};

export const CATALOG_REFRESH_INTERVAL_MS = 60 * 60 * 1000;

const shouldRefreshProvider = async (provider: string) => {
  const [row] = await sql<{ syncedAt: Date }[]>`
    select synced_at as "syncedAt"
    from provider_model_catalog_sync
    where provider = ${provider}
    limit 1
  `;

  if (!row) {
    return true;
  }

  return Date.now() - row.syncedAt.getTime() > CATALOG_REFRESH_INTERVAL_MS;
};

export const syncProviderModels = async (provider: string, force = false): Promise<ProviderSyncResult> => {
  if (!SUPPORTED_MODEL_PROVIDERS.includes(provider as SupportedModelProvider)) {
    return { synced: false, count: 0, inserted: 0, updated: 0, message: "Provider not supported" };
  }

  if (!force && !(await shouldRefreshProvider(provider))) {
    console.log(`[catalog] Skipping ${provider} sync - within 1 hour window`);
    return {
      synced: false,
      count: 0,
      inserted: 0,
      updated: 0,
      message: "Skipped - synced within last hour"
    };
  }

  console.log(`[catalog] Fetching models from ${provider} API...`);
  const models =
    provider === "xai" ? await listXaiModels()
      : provider === "nous" ? await listNousModels()
        : provider === "openai" ? await listOpenAIModels()
          : provider === "anthropic" ? await listAnthropicModels()
            : provider === "google" ? await listGoogleModels()
              : provider === "mistral" ? await listMistralModels()
                : await listHuggingFaceModels();
  console.log(`[catalog] Found ${models.length} models from ${provider}`);

  let inserted = 0;
  let updated = 0;

  for (const model of models) {
    const providerLabel = modelProviderLabel(provider);
    const profileName = `${providerLabel} ${model.id}`;
    const result = await sql`
      insert into model_profiles (name, provider, model, settings)
      values (${profileName}, ${provider}, ${model.id}, '{"temperature":0.2}'::jsonb)
      on conflict (name) do update
      set
        provider = excluded.provider,
        model = excluded.model,
        settings = model_profiles.settings
      returning (xmax::text = '0') as inserted
    `;
    if (result[0]?.inserted) {
      inserted++;
    } else {
      updated++;
    }
  }

  await sql`
    insert into provider_model_catalog_sync (provider, synced_at)
    values (${provider}, now())
    on conflict (provider) do update
    set synced_at = now()
  `;

  console.log(`[catalog] Synced ${models.length} models (${inserted} new, ${updated} updated)`);
  return {
    synced: true,
    count: models.length,
    inserted,
    updated,
    message: `Synced ${models.length} models from ${provider}`
  };
};

export const syncAllProviderModels = async (force = false) => {
  const results = [];
  let bootstrapResult = { count: 0, inserted: 0, updated: 0 };

  for (const provider of SUPPORTED_MODEL_PROVIDERS) {
    try {
      results.push({
        provider,
        label: modelProviderLabel(provider),
        ...(await syncProviderModels(provider, force))
      });
    } catch (error) {
      console.warn(`[catalog] ${provider} sync failed:`, error instanceof Error ? error.message : String(error));
      results.push({
        provider,
        label: modelProviderLabel(provider),
        synced: false,
        count: 0,
        inserted: 0,
        updated: 0,
        message: error instanceof Error ? error.message : String(error)
      });
    }
  }

  try {
    bootstrapResult = await bootstrapModelProfiles();
  } catch (error) {
    console.warn("[catalog] model bootstrap failed:", error instanceof Error ? error.message : String(error));
  }

  return {
    syncedAt: new Date().toISOString(),
    force,
    providers: results,
    bootstrap: bootstrapResult
  };
};

const shouldRefreshVenue = async (venue: string) => {
  const [row] = await sql<{ lastSeenAt: Date }[]>`
    select max(last_seen_at) as "lastSeenAt"
    from venue_symbol_catalog
    where venue = ${venue}
  `;

  if (!row?.lastSeenAt) {
    return true;
  }

  return Date.now() - row.lastSeenAt.getTime() > CATALOG_REFRESH_INTERVAL_MS;
};

const venueMode = (venue: Extract<VenueId, "binance" | "binance-testnet">) =>
  venue === "binance-testnet" ? "testnet" as const : "live" as const;

export const syncVenueSymbols = async (venue: VenueId, force = false) => {
  if (!isBinanceVenue(venue)) {
    return {
      venue,
      synced: false,
      count: 0,
      message: "Skipped - venue symbol sync is not implemented for this planned venue"
    };
  }

  if (!force && !(await shouldRefreshVenue(venue))) {
    return {
      venue,
      synced: false,
      count: 0,
      message: "Skipped - synced within last hour"
    };
  }

  const symbols = (await listVenueSymbols(venueMode(venue))) as string[];

  await sql`
    update venue_symbol_catalog
    set is_active = false, updated_at = now()
    where venue = ${venue}
  `;

  if (symbols.length > 0) {
    await sql`
      insert into venue_symbol_catalog (venue, symbol, is_active, last_seen_at, updated_at)
      select ${venue}, symbol, true, now(), now()
      from unnest(${symbols}::text[]) as symbol
      on conflict (venue, symbol) do update
      set
        is_active = true,
        last_seen_at = now(),
        updated_at = now()
    `;
  }

  return {
    venue,
    synced: true,
    count: symbols.length,
    message: `Synced ${symbols.length} symbols`
  };
};

export const getVenueSymbols = async (venue: VenueId, force = false) => {
  try {
    await syncVenueSymbols(venue, force);
  } catch (syncError) {
    console.warn("Venue symbol sync failed, serving cached catalog:", syncError);
  }

  const rows = await sql<{ symbol: string }[]>`
    select symbol
    from venue_symbol_catalog
    where venue = ${venue}
      and is_active = true
    order by symbol asc
  `;

  return rows.map((row) => row.symbol);
};
