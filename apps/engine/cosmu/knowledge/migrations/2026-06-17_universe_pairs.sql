-- Migration: the venue-tagged, liquidity-ranked UNIVERSE table (Agent B — venue universe + survivorship calendar).
-- universe_pairs is the BROAD machine-fetched discovery set across ALL venues (Binance spot+perp, Kraken
-- spot+futures, Hyperliquid, Polymarket, IBKR-curated equities) — the ONE source the lab tests wide over per
-- (strategy × symbol × VENUE). Distinct from `instruments` (the small curated execution catalog the engine
-- seeds): this is thousands of pairs with REAL 24h USD liquidity + a global tier (0 deepest / 1 / 2 deep) +
-- the point-in-time survivorship window (listed_at/delisted_at, also fed into the UniverseCalendar).
-- Additive + idempotent: CREATE TABLE IF NOT EXISTS, no data loss, no cascade. Safe before or after deploy.
create table if not exists universe_pairs (
  id text primary key,                 -- "venue:symbol"
  venue text not null,
  symbol text not null,
  base text,
  quote text,
  asset_class text not null,           -- crypto | equity | prediction
  instrument_type text not null,       -- spot | perp | equity | prediction
  liquidity_usd_24h numeric not null default 0,
  tier integer,                        -- 0 deepest / 1 / 2 — null until ranked
  rank integer,                        -- global liquidity rank (0 = deepest)
  listed_at text,
  delisted_at text,
  active integer not null default 1,
  source text not null,                -- live | curated | vision
  fetched_at text not null
);
create index if not exists idx_universe_pairs_venue on universe_pairs(venue);
create index if not exists idx_universe_pairs_class on universe_pairs(asset_class);
create index if not exists idx_universe_pairs_tier on universe_pairs(tier);
create index if not exists idx_universe_pairs_liquidity on universe_pairs(liquidity_usd_24h);
