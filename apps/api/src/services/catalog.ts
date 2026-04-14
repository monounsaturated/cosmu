import { sql } from "../db.js";
import { listVenueSymbols } from "../adapters/binance.js";
import { listXaiModels } from "../providers/xai.js";

type CatalogUpsertResult = {
  count: number;
  inserted: number;
  updated: number;
};

export type ProviderSyncResult = CatalogUpsertResult & {
  synced: boolean;
  message: string;
};

// Known working xAI model profiles — used as seed fallback when xAI API is unreachable.
// These match the canonical names used by the sync so there are no duplicates.
export const BOOTSTRAP_XAI_PROFILES: { name: string; model: string }[] = [
  { name: "xAI grok-3", model: "grok-3" },
  { name: "xAI grok-3-fast", model: "grok-3-fast" },
  { name: "xAI grok-3-mini", model: "grok-3-mini" },
  { name: "xAI grok-3-mini-fast", model: "grok-3-mini-fast" },
];

export const bootstrapModelProfiles = async (): Promise<CatalogUpsertResult> => {
  let inserted = 0;
  let updated = 0;

  for (const profile of BOOTSTRAP_XAI_PROFILES) {
    const result = await sql`
      insert into model_profiles (name, provider, model, settings)
      values (${profile.name}, 'xai', ${profile.model}, '{"temperature":0.2}'::jsonb)
      on conflict (name) do update
      set
        provider = excluded.provider,
        model = excluded.model
      returning (xmax::text = '0') as inserted
    `;
    if (result[0]?.inserted) {
      inserted++;
    } else {
      updated++;
    }
  }

  console.log(`[catalog] Bootstrapped ${BOOTSTRAP_XAI_PROFILES.length} models (${inserted} new, ${updated} updated)`);
  return { count: BOOTSTRAP_XAI_PROFILES.length, inserted, updated };
};

const HOURS_12_MS = 12 * 60 * 60 * 1000;

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

  return Date.now() - row.syncedAt.getTime() > HOURS_12_MS;
};

export const syncProviderModels = async (provider: string, force = false): Promise<ProviderSyncResult> => {
  if (provider !== "xai") {
    return { synced: false, count: 0, inserted: 0, updated: 0, message: "Provider not supported" };
  }

  if (!force && !(await shouldRefreshProvider(provider))) {
    console.log(`[catalog] Skipping ${provider} sync - within 12 hour window`);
    return {
      synced: false,
      count: 0,
      inserted: 0,
      updated: 0,
      message: "Skipped - synced within last 12 hours"
    };
  }

  console.log(`[catalog] Fetching models from ${provider} API...`);
  const models = await listXaiModels();
  console.log(`[catalog] Found ${models.length} models from ${provider}`);

  let inserted = 0;
  let updated = 0;

  for (const model of models) {
    const profileName = `xAI ${model.id}`;
    const result = await sql`
      insert into model_profiles (name, provider, model, settings)
      values (${profileName}, 'xai', ${model.id}, '{"temperature":0.2}'::jsonb)
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

const shouldRefreshVenue = async (venue: string) => {
  const [row] = await sql<{ lastSeenAt: Date }[]>`
    select max(last_seen_at) as "lastSeenAt"
    from venue_symbol_catalog
    where venue = ${venue}
  `;

  if (!row?.lastSeenAt) {
    return true;
  }

  return Date.now() - row.lastSeenAt.getTime() > HOURS_12_MS;
};

export const syncVenueSymbols = async (venue: "binance") => {
  if (!(await shouldRefreshVenue(venue))) {
    return;
  }

  const symbols = (await listVenueSymbols()) as string[];

  await sql`
    update venue_symbol_catalog
    set is_active = false, updated_at = now()
    where venue = ${venue}
  `;

  for (const symbol of symbols) {
    await sql`
      insert into venue_symbol_catalog (venue, symbol, is_active, last_seen_at, updated_at)
      values (${venue}, ${symbol}, true, now(), now())
      on conflict (venue, symbol) do update
      set
        is_active = true,
        last_seen_at = now(),
        updated_at = now()
    `;
  }
};

export const getVenueSymbols = async (venue: "binance") => {
  try {
    await syncVenueSymbols(venue);
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
