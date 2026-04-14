create sequence if not exists bots_bot_number_seq;

alter table bots add column if not exists bot_number integer;

with numbered as (
  select
    id,
    row_number() over (order by created_at asc, id asc) as next_number
  from bots
  where bot_number is null
)
update bots
set bot_number = numbered.next_number
from numbered
where bots.id = numbered.id;

alter table bots alter column bot_number set default nextval('bots_bot_number_seq');
alter table bots alter column bot_number set not null;

select setval(
  'bots_bot_number_seq',
  coalesce((select max(bot_number) from bots), 0) + 1,
  false
);

create unique index if not exists bots_bot_number_idx on bots (bot_number);

alter table bots add column if not exists parent_bot_id uuid references bots(id) on delete set null;
alter table bots add column if not exists prompt_config jsonb not null default
  '{
    "preset":"minimal",
    "modules":{
      "includeCurrentPositions":true,
      "includePastTrades":false,
      "pastTradesLookback":10,
      "includePerformanceStats":true,
      "includeBotRanking":false,
      "includeWalletOverview":true
    }
  }'::jsonb;
alter table bots add column if not exists trader_config jsonb not null default
  '{"mode":"deterministic","modelProfileId":null}'::jsonb;

alter table executions add column if not exists fee_asset_usd_price numeric;
alter table executions add column if not exists executed_notional_usd numeric;
