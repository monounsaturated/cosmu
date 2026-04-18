import { sql } from "../../db.js";

export type TraderPromptSummary = {
  id: string;
  name: string;
  slug: string;
  createdAt: string;
  promptNumber: number;
  latestVersionId: string | null;
  latestBody: string | null;
  latestVersionCreatedAt: string | null;
  lastUsedAt: string | null;
};

export const listTraderPrompts = async (): Promise<TraderPromptSummary[]> =>
  sql<TraderPromptSummary[]>`
    with prompt_order as (
      select id, row_number() over (order by created_at asc) as "promptNumber"
      from trader_prompts
    ),
    latest_version as (
      select distinct on (prompt_id)
        prompt_id, id, body, created_at
      from trader_prompt_versions
      order by prompt_id, version desc
    )
    select
      p.id, p.name, p.slug, p.created_at as "createdAt",
      prompt_order."promptNumber",
      latest_version.id as "latestVersionId",
      latest_version.body as "latestBody",
      latest_version.created_at as "latestVersionCreatedAt",
      p.last_used_at as "lastUsedAt"
    from trader_prompts p
    join prompt_order on prompt_order.id = p.id
    left join latest_version on latest_version.prompt_id = p.id
    order by prompt_order."promptNumber" desc
  `;

export const touchTraderPromptUsage = async (promptVersionId: string) => {
  await sql`
    update trader_prompts
    set last_used_at = now(), updated_at = now()
    where id = (
      select prompt_id from trader_prompt_versions where id = ${promptVersionId} limit 1
    )
  `;
};

export const createTraderPrompt = async (input: {
  name?: string;
  slug?: string;
  initialBody: string;
}) => {
  const trimmedName = (input.name ?? "").trim();
  const effectiveName = trimmedName || `Trader Prompt ${Date.now().toString(36)}`;
  const effectiveSlug = (input.slug ?? "").trim() || `trader-prompt-${Date.now().toString(36)}`;

  const [prompt] = await sql<{ id: string }[]>`
    insert into trader_prompts (name, slug) values (${effectiveName}, ${effectiveSlug}) returning id
  `;
  const [promptVersion] = await sql<{ id: string }[]>`
    insert into trader_prompt_versions (prompt_id, version, body)
    values (${prompt.id}, 1, ${input.initialBody})
    returning id
  `;
  return { promptId: prompt.id, promptVersionId: promptVersion.id };
};

export const addTraderPromptVersion = async (input: { promptId: string; body: string }) => {
  const [maxRow] = await sql<{ maxVersion: number }[]>`
    select coalesce(max(version), 0) as "maxVersion"
    from trader_prompt_versions
    where prompt_id = ${input.promptId}
  `;
  const nextVersion = (maxRow?.maxVersion ?? 0) + 1;
  const [promptVersion] = await sql<{ id: string }[]>`
    insert into trader_prompt_versions (prompt_id, version, body)
    values (${input.promptId}, ${nextVersion}, ${input.body})
    returning id
  `;
  return { promptVersionId: promptVersion.id, version: nextVersion };
};

export const getTraderPromptVersionBody = async (versionId: string) => {
  const [row] = await sql<{ id: string; body: string; version: number; promptId: string; promptName: string }[]>`
    select tpv.id, tpv.body, tpv.version, tp.id as "promptId", tp.name as "promptName"
    from trader_prompt_versions tpv
    join trader_prompts tp on tp.id = tpv.prompt_id
    where tpv.id = ${versionId}
    limit 1
  `;
  return row ?? null;
};

export const getNextTraderPromptNumber = async (): Promise<number> => {
  const [row] = await sql<{ next: number }[]>`
    select coalesce(max(prompt_number), 0) + 1 as next from trader_prompts
  `;
  return row.next;
};
