-- Workspace-mode segregation for bots.
-- Light bots remain the operational baseline. Research bots are venue-scoped
-- exploratory agents. Pro bots are promoted candidates eligible for
-- execution under approval gates.

alter table bots
  add column if not exists workspace_mode text not null default 'light'
    check (workspace_mode in ('light', 'research', 'pro'));

create index if not exists bots_workspace_mode_idx on bots (workspace_mode);

-- Promotion link from a research candidate to a Pro bot row. We do not
-- delete the candidate when the bot is killed, but we cascade the link.
alter table research_candidates
  add column if not exists promoted_bot_id uuid references bots(id) on delete set null;

create index if not exists research_candidates_promoted_bot_idx on research_candidates (promoted_bot_id);

-- Fast lookup and idempotency guard for candidate promotion requests.
create index if not exists approval_requests_live_promotion_candidate_idx
  on approval_requests ((payload->>'candidateId'))
  where request_type = 'live_promotion';
