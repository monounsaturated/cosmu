-- 014: Separate model profiles for research & trader phases + prompt usage tracking
--
-- Changes:
--   1. bots: add active_trader_model_profile_id (nullable FK to model_profiles)
--      - active_model_profile_id remains as the research model
--      - when active_trader_model_profile_id is NULL, runner falls back to active_model_profile_id
--   2. research_prompts: add last_used_at, updated_at columns
--   3. trader_prompts:   add last_used_at, updated_at columns

-- 1. Separate trader model on bots
alter table bots
  add column if not exists active_trader_model_profile_id uuid
    references model_profiles(id);

comment on column bots.active_model_profile_id is
  'Model profile used for the research (phase 1) LLM call';
comment on column bots.active_trader_model_profile_id is
  'Model profile used for the trader (phase 2) LLM call. Falls back to active_model_profile_id when NULL.';

-- Back-fill: set trader model to the same as research model for existing bots
update bots
  set active_trader_model_profile_id = active_model_profile_id
  where active_trader_model_profile_id is null;

-- 2. Prompt usage tracking – research_prompts
alter table research_prompts
  add column if not exists last_used_at timestamptz,
  add column if not exists updated_at  timestamptz default now();

-- 3. Prompt usage tracking – trader_prompts
alter table trader_prompts
  add column if not exists last_used_at timestamptz,
  add column if not exists updated_at  timestamptz default now();
