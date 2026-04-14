import { sql } from "../db.js";
import { listVenueSymbols } from "../adapters/binance.js";
import { listXaiModels } from "../providers/xai.js";

// Known working xAI model profiles — used as seed fallback when xAI API is unreachable.
// These match the canonical names used by the sync so there are no duplicates.
export const BOOTSTRAP_XAI_PROFILES: { name: string; model: string }[] = [
  { name: "xAI grok-3", model: "grok-3" },
  { name: "xAI grok-3-fast", model: "grok-3-fast" },
  { name: "xAI grok-3-mini", model: "grok-3-mini" },
  { name: "xAI grok-3-mini-fast", model: "grok-3-mini-fast" },
  { name: "xAI grok-beta", model: "grok-beta" },
  { name: "xAI grok-2", model: "grok-2" },
];

export const bootstrapModelProfiles = async () => {
  for (const profile of BOOTSTRAP_XAI_PROFILES) {
    await sql`
      insert into model_profiles (name, provider, model, settings)
      values (${profile.name}, 'xai', ${profile.model}, '{"temperature":0.2}'::jsonb)
      on conflict (provider, model) do nothing
    `;
  }
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

export const syncProviderModels = async (provider: string) => {
  if (provider !== "xai") {
    return;
  }

  if (!(await shouldRefreshProvider(provider))) {
    return;
  }

  const models = await listXaiModels();
  for (const model of models) {
    const profileName = `xAI ${model.id}`;
    await sql`
      insert into model_profiles (name, provider, model, settings)
      values (${profileName}, 'xai', ${model.id}, '{"temperature":0.2}'::jsonb)
      on conflict (provider, model) do update
      set
        name = excluded.name,
        settings = model_profiles.settings
    `;
  }

  await sql`
    insert into provider_model_catalog_sync (provider, synced_at)
    values (${provider}, now())
    on conflict (provider) do update
    set synced_at = now()
  `;
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
