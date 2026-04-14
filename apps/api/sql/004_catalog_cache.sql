create table if not exists provider_model_catalog_sync (
  provider text primary key,
  synced_at timestamptz not null default now()
);

create table if not exists venue_symbol_catalog (
  venue text not null,
  symbol text not null,
  is_active boolean not null default true,
  last_seen_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (venue, symbol)
);

create index if not exists venue_symbol_catalog_venue_active_idx on venue_symbol_catalog (venue, is_active, symbol);

create unique index if not exists model_profiles_provider_model_idx on model_profiles (provider, model);
