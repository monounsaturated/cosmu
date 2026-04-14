-- Store the exact prompt sent to the LLM for each run (system + user message)
alter table runs add column if not exists prompt_system text;
alter table runs add column if not exists prompt_user text;
