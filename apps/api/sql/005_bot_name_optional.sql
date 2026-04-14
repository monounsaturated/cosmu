-- Make bot name optional (non-unique) — identity is bot_number
alter table bots drop constraint if exists bots_name_key;

-- Make prompt name and slug non-unique — prompts are identified by auto-number
alter table prompts drop constraint if exists prompts_name_key;
alter table prompts drop constraint if exists prompts_slug_key;

-- Also relax bots slug uniqueness (identity is bot_number)
alter table bots drop constraint if exists bots_slug_key;

-- Renumber bots to remove gaps (must do BEFORE resync)
with renumbered as (
  select id, row_number() over (order by bot_number asc) as new_number
  from bots
)
update bots
set bot_number = renumbered.new_number
from renumbered
where bots.id = renumbered.id
  and bots.bot_number != renumbered.new_number;

-- Resync bot_number sequence to max existing value
select setval(
  'bots_bot_number_seq',
  coalesce((select max(bot_number) from bots), 0) + 1,
  false
);
