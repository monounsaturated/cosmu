-- Add latest_value to alt_data_provider_summary so the Mind KNOWS panel (analysts._latest_values) can read the
-- newest VALUE per metric from the tiny rollup instead of a JOIN+GROUP-BY over the ~17M-row alt_data table
-- (the same full-scan perf trap already fixed for /intelligence and /scores). Point-in-time honest: the value
-- carried is that of the row with the newest available_at, maintained incrementally on ingest.
-- Idempotent + safe before/after deploy (the reader degrades to honest-empty when the column/table is absent).

alter table if exists alt_data_provider_summary add column if not exists latest_value text;

-- One-off backfill from existing alt_data: the value at MAX(available_at) per (provider, metric). Run ONCE,
-- manually, NOT on the request path (a single DISTINCT ON over alt_data, ~30s on prod).
update alt_data_provider_summary s
set latest_value = sub.value
from (
  select distinct on (provider, metric) provider, metric, value
  from alt_data
  order by provider, metric, available_at desc
) sub
where s.provider = sub.provider and s.metric = sub.metric;
