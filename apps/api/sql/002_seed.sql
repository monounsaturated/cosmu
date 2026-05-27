with inserted_prompt as (
  insert into prompts (name, slug)
  values ('Core Trader', 'core-trader')
  on conflict (slug) do update set name = excluded.name
  returning id
),
selected_prompt as (
  select id from inserted_prompt
  union all
  select id from prompts where slug = 'core-trader'
  limit 1
),
inserted_prompt_version as (
  insert into prompt_versions (prompt_id, version, body)
  select
    id,
    1,
    $prompt$
You are the trading decision engine for one autonomous spot bot.

Return only valid JSON matching the provided schema.

Objectives:
- manage the current spot portfolio prudently
- prefer clear, high-conviction actions
- if conditions are unclear, choose hold with no orders

Rules:
- venue is Binance spot
- mode is supplied in runtime context and must be respected implicitly by the operator, not mentioned in the output
- do not invent balances, prices, or symbols
- only propose orders for symbols that can plausibly trade against USDT
- keep the order list lean
- every order must include a concise rationale
$prompt$
  from selected_prompt
  on conflict (prompt_id, version) do nothing
  returning id
),
selected_prompt_version as (
  select id from inserted_prompt_version
  union all
  select pv.id
  from prompt_versions pv
  join selected_prompt sp on sp.id = pv.prompt_id
  where pv.version = 1
  limit 1
),
inserted_model_profile as (
  insert into model_profiles (name, provider, model, settings)
  values ('Grok 4.3 Default', 'xai', 'grok-4.3', '{"temperature":0.2}'::jsonb)
  on conflict (name) do update set
    provider = excluded.provider,
    model = excluded.model,
    settings = excluded.settings
  returning id
),
selected_model_profile as (
  select id from inserted_model_profile
  union all
  select id from model_profiles where name = 'Grok 4.3 Default'
  limit 1
),
inserted_bot as (
  insert into bots (name, slug, active_prompt_version_id, active_model_profile_id)
  select
    'Primary Spot Bot',
    'primary-spot-bot',
    spv.id,
    smp.id
  from selected_prompt_version spv
  cross join selected_model_profile smp
  on conflict (slug) do update set
    active_prompt_version_id = excluded.active_prompt_version_id,
    active_model_profile_id = excluded.active_model_profile_id
  returning id
),
selected_bot as (
  select id from inserted_bot
  union all
  select id from bots where slug = 'primary-spot-bot'
  limit 1
)
insert into bot_runtime_configs (
  bot_id,
  enabled,
  venue,
  frequency_minutes,
  mode,
  asset_class,
  execution_config,
  context_symbols
)
select
  sb.id,
  true,
  'binance',
  15,
  'testnet',
  'spot',
  '{"allowMarketOrders":true,"allowLimitOrders":true,"maxOrdersPerRun":3,"maxNotionalPerOrderUsd":250,"minCashReserveUsd":25,"maxDrawdownPct":10}'::jsonb,
  '["BTCUSDT","ETHUSDT","SOLUSDT"]'::jsonb
from selected_bot sb
on conflict (bot_id) do update set
  enabled = excluded.enabled,
  venue = excluded.venue,
  frequency_minutes = excluded.frequency_minutes,
  mode = excluded.mode,
  asset_class = excluded.asset_class,
  execution_config = excluded.execution_config,
  context_symbols = excluded.context_symbols,
  updated_at = now();
