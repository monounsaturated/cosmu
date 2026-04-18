-- 015: Split raw_model_output into dedicated research_output and trader_output columns.
--
-- Rationale: raw_model_output was a single text column that stored either
--   (a) the combined phase1+phase2 JSON (from storeRawModelOutput), or
--   (b) just the trader's raw text (from storeDecision, which overwrote (a)).
-- Because storeDecision ran after storeRawModelOutput on every run, (b) always
-- won, and the research-phase output was effectively never persisted.
--
-- New shape:
--   research_output text null  — raw text returned by the research agent
--   trader_output   text null  — raw text returned by the trader agent
-- raw_model_output is dropped after backfilling whatever is currently there
-- into trader_output (because in practice that column held trader text).

alter table runs
  add column research_output text,
  add column trader_output   text;

-- Backfill: raw_model_output currently holds trader text for nearly every
-- non-null row (see rationale above). Move it to trader_output. We cannot
-- recover research_output for historical rows — it was never saved.
update runs
  set trader_output = raw_model_output
  where raw_model_output is not null;

alter table runs drop column raw_model_output;

comment on column runs.research_output is
  'Raw text output from the research agent (phase 1). Null for kill-mode runs and pre-migration runs.';
comment on column runs.trader_output is
  'Raw text output from the trader agent (phase 2). Null for kill-mode runs.';
