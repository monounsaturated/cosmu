-- Drop the redundant bot_runtime_configs.mode column.
-- Venue is the single source of truth for execution context; `mode` was a
-- denormalized testnet/live mirror derived from venue via netForVenue() and was
-- write-only (never read). Removed alongside the code that wrote it.

alter table if exists bot_runtime_configs
  drop column if exists mode;
