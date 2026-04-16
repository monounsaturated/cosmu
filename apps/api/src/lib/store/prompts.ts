import type { RuntimeConfig } from "@cosmu/shared";
import { sql } from "../../db.js";

export const listPrompts = async () =>
  sql`
    with prompt_order as (
      select id, row_number() over (order by created_at asc) as "promptNumber"
      from prompts
    ),
    latest_version as (
      select distinct on (prompt_id)
        prompt_id, id, body, created_at
      from prompt_versions
      order by prompt_id, version desc
    )
    select
      p.id, p.name, p.slug, p.created_at as "createdAt",
      prompt_order."promptNumber",
      latest_version.id as "latestVersionId",
      latest_version.body as "latestBody",
      latest_version.created_at as "latestVersionCreatedAt"
    from prompts p
    join prompt_order on prompt_order.id = p.id
    left join latest_version on latest_version.prompt_id = p.id
    order by prompt_order."promptNumber" desc
  `;

export const listModelProfiles = async (provider?: string) => {
  if (provider) {
    return sql`
      select id, name, provider, model, settings, created_at as "createdAt"
      from model_profiles
      where provider = ${provider}
      order by created_at desc
    `;
  }
  return sql`
    select id, name, provider, model, settings, created_at as "createdAt"
    from model_profiles
    order by created_at desc
  `;
};

export const getPromptVersionBody = async (versionId: string) => {
  const [row] = await sql<{ id: string; body: string; version: number; promptId: string; promptName: string }[]>`
    select pv.id, pv.body, pv.version, p.id as "promptId", p.name as "promptName"
    from prompt_versions pv
    join prompts p on p.id = pv.prompt_id
    where pv.id = ${versionId}
    limit 1
  `;
  return row ?? null;
};

export const addPromptVersion = async (input: { promptId: string; body: string }) => {
  const [maxRow] = await sql<{ maxVersion: number }[]>`
    select coalesce(max(version), 0) as "maxVersion"
    from prompt_versions
    where prompt_id = ${input.promptId}
  `;
  const nextVersion = (maxRow?.maxVersion ?? 0) + 1;
  const [promptVersion] = await sql<{ id: string }[]>`
    insert into prompt_versions (prompt_id, version, body)
    values (${input.promptId}, ${nextVersion}, ${input.body})
    returning id
  `;
  return { promptVersionId: promptVersion.id, version: nextVersion };
};

export const createPrompt = async (input: { name?: string; slug?: string; initialBody: string }) => {
  const trimmedName = (input.name ?? "").trim();
  const effectiveName = trimmedName || `Prompt ${Date.now().toString(36)}`;
  const effectiveSlug = (input.slug ?? "").trim() || `prompt-${Date.now().toString(36)}`;

  const [prompt] = await sql<{ id: string }[]>`
    insert into prompts (name, slug) values (${effectiveName}, ${effectiveSlug}) returning id
  `;
  const [promptVersion] = await sql<{ id: string }[]>`
    insert into prompt_versions (prompt_id, version, body)
    values (${prompt.id}, 1, ${input.initialBody})
    returning id
  `;
  return { promptId: prompt.id, promptVersionId: promptVersion.id };
};

export const createModelProfile = async (input: {
  name: string;
  provider: string;
  model: string;
  settings: Record<string, unknown>;
}) => {
  const [existing] = await sql<{ id: string }[]>`
    select id from model_profiles
    where provider = ${input.provider} and model = ${input.model}
    limit 1
  `;
  if (existing) return existing.id;

  const [row] = await sql<{ id: string }[]>`
    insert into model_profiles (name, provider, model, settings)
    values (${input.name}, ${input.provider}, ${input.model}, ${sql.json(input.settings as any)})
    returning id
  `;
  return row.id;
};

type VenuePromptVersion = {
  id: string;
  venue: string;
  promptType: string;
  version: number;
  body: string;
  createdAt: string;
};

export const getActiveFormatterPrompt = async (
  venue: RuntimeConfig["venue"]
): Promise<VenuePromptVersion | null> => {
  try {
    const [row] = await sql<VenuePromptVersion[]>`
      select id, venue, prompt_type as "promptType", version, body,
             created_at::text as "createdAt"
      from venue_prompt_versions
      where venue = ${venue} and prompt_type = 'formatter' and length(trim(body)) > 0
      order by version desc
      limit 1
    `;
    return row ?? null;
  } catch (error) {
    console.warn("getActiveFormatterPrompt failed:", String(error));
    return null;
  }
};

export const createFormatterPromptVersion = async (
  venue: RuntimeConfig["venue"],
  body: string
): Promise<VenuePromptVersion> => {
  const [row] = await sql<VenuePromptVersion[]>`
    insert into venue_prompt_versions (venue, prompt_type, version, body)
    values (
      ${venue}, 'formatter',
      coalesce((select max(version) from venue_prompt_versions where venue = ${venue} and prompt_type = 'formatter'), 0) + 1,
      ${body}
    )
    returning id, venue, prompt_type as "promptType", version, body, created_at::text as "createdAt"
  `;
  return row;
};

export const listFormatterPromptVersions = async (venue: RuntimeConfig["venue"]): Promise<VenuePromptVersion[]> =>
  sql<VenuePromptVersion[]>`
    select id, venue, prompt_type as "promptType", version, body, created_at::text as "createdAt"
    from venue_prompt_versions
    where venue = ${venue} and prompt_type = 'formatter'
    order by version desc
  `;

export const getAllActiveFormatterPrompts = async () => {
  const binance = await getActiveFormatterPrompt("binance");
  const testnet = await getActiveFormatterPrompt("binance-testnet");
  return {
    binance: { body: binance?.body ?? "", version: binance?.version ?? null, id: binance?.id ?? null },
    "binance-testnet": { body: testnet?.body ?? "", version: testnet?.version ?? null, id: testnet?.id ?? null }
  };
};
