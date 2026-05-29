// module: Index config/run/snapshot storage for qualitative-to-quantitative views.
import type { IndexConfig, IndexSnapshot } from "@cosmu/shared";
import { sql } from "../../db.js";
import { parseJson, type JsonValue } from "./helpers.js";

type IndexConfigRow = Omit<IndexConfig, "createdAt" | "updatedAt"> & {
  createdAt: Date;
  updatedAt: Date;
};

type IndexSnapshotRow = Omit<IndexSnapshot, "capturedAt"> & {
  capturedAt: Date;
};

export const ensureIndexSchema = async () => {
  await sql`
    create table if not exists index_configs (
      id uuid primary key default gen_random_uuid(),
      name text not null,
      slug text not null unique,
      description text,
      status text not null check (status in ('active', 'paused', 'error')) default 'paused',
      cadence_minutes integer not null check (cadence_minutes > 0),
      source_keys jsonb not null default '[]'::jsonb,
      prompt_body text not null,
      output_schema jsonb not null default '{}'::jsonb,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    )
  `;
  await sql`
    create table if not exists index_runs (
      id uuid primary key default gen_random_uuid(),
      index_id uuid not null references index_configs(id) on delete cascade,
      status text not null check (status in ('running', 'success', 'failure')) default 'running',
      source_counts jsonb not null default '{}'::jsonb,
      cost_json jsonb not null default '{}'::jsonb,
      error text,
      started_at timestamptz not null default now(),
      finished_at timestamptz,
      created_at timestamptz not null default now()
    )
  `;
  await sql`
    create table if not exists index_snapshots (
      id uuid primary key default gen_random_uuid(),
      index_id uuid not null references index_configs(id) on delete cascade,
      run_id uuid references index_runs(id) on delete set null,
      value numeric,
      label text,
      summary text not null,
      evidence_json jsonb not null default '[]'::jsonb,
      captured_at timestamptz not null default now()
    )
  `;
};

const mapIndexConfig = (row: IndexConfigRow): IndexConfig => ({
  ...row,
  description: row.description ?? null,
  sourceKeys: Array.isArray(row.sourceKeys) ? row.sourceKeys.map(String) : [],
  outputSchema: parseJson(row.outputSchema),
  createdAt: row.createdAt.toISOString(),
  updatedAt: row.updatedAt.toISOString()
});

const mapIndexSnapshot = (row: IndexSnapshotRow): IndexSnapshot => ({
  ...row,
  value: row.value == null ? null : Number(row.value),
  label: row.label ?? null,
  evidenceJson: parseJson(row.evidenceJson),
  capturedAt: row.capturedAt.toISOString()
});

export const listIndexConfigs = async () => {
  const rows = await sql<IndexConfigRow[]>`
    select
      id, name, slug, description, status,
      cadence_minutes as "cadenceMinutes",
      source_keys as "sourceKeys",
      prompt_body as "promptBody",
      output_schema as "outputSchema",
      created_at as "createdAt",
      updated_at as "updatedAt"
    from index_configs
    order by updated_at desc
    limit 100
  `;
  return rows.map(mapIndexConfig);
};

export const createIndexConfig = async (input: {
  name: string;
  slug: string;
  description?: string | null;
  cadenceMinutes: number;
  sourceKeys: string[];
  promptBody: string;
  outputSchema?: unknown;
}) => {
  const [row] = await sql<IndexConfigRow[]>`
    insert into index_configs (
      name, slug, description, cadence_minutes, source_keys, prompt_body, output_schema
    ) values (
      ${input.name}, ${input.slug}, ${input.description ?? null}, ${input.cadenceMinutes},
      ${sql.json(input.sourceKeys as JsonValue)}, ${input.promptBody},
      ${sql.json((input.outputSchema ?? {}) as JsonValue)}
    )
    returning
      id, name, slug, description, status,
      cadence_minutes as "cadenceMinutes",
      source_keys as "sourceKeys",
      prompt_body as "promptBody",
      output_schema as "outputSchema",
      created_at as "createdAt",
      updated_at as "updatedAt"
  `;
  return mapIndexConfig(row);
};

export const getDueIndexConfigs = async (): Promise<IndexConfig[]> => {
  const rows = await sql<IndexConfigRow[]>`
    select
      c.id, c.name, c.slug, c.description, c.status,
      c.cadence_minutes as "cadenceMinutes",
      c.source_keys as "sourceKeys",
      c.prompt_body as "promptBody",
      c.output_schema as "outputSchema",
      c.created_at as "createdAt",
      c.updated_at as "updatedAt"
    from index_configs c
    where c.status = 'active'
      and not exists (
        select 1 from index_runs r where r.index_id = c.id and r.status = 'running'
      )
      and (
        (select max(r2.started_at) from index_runs r2 where r2.index_id = c.id) is null
        or (select max(r2.started_at) from index_runs r2 where r2.index_id = c.id)
             < now() - make_interval(mins => c.cadence_minutes)
      )
    order by c.updated_at asc
  `;
  return rows.map(mapIndexConfig);
};

// Atomic claim: only inserts a running run when none is already in flight for this
// index, so overlapping scheduler ticks can't double-fire the same index.
export const claimIndexRun = async (indexId: string): Promise<string | null> => {
  const [row] = await sql<{ id: string }[]>`
    insert into index_runs (index_id, status)
    select ${indexId}, 'running'
    where not exists (
      select 1 from index_runs where index_id = ${indexId} and status = 'running'
    )
    returning id
  `;
  return row?.id ?? null;
};

export const finishIndexRun = async (
  runId: string,
  input: { status: "success" | "failure"; sourceCounts?: unknown; cost?: unknown; error?: string | null }
) => {
  await sql`
    update index_runs
    set status = ${input.status},
        source_counts = ${sql.json((input.sourceCounts ?? {}) as JsonValue)},
        cost_json = ${sql.json((input.cost ?? {}) as JsonValue)},
        error = ${input.error ?? null},
        finished_at = now()
    where id = ${runId}
  `;
};

export const setIndexStatus = async (indexId: string, status: IndexConfig["status"]) => {
  await sql`
    update index_configs set status = ${status}, updated_at = now() where id = ${indexId}
  `;
};

export const createIndexSnapshot = async (input: {
  indexId: string;
  runId: string | null;
  value: number | null;
  label: string | null;
  summary: string;
  evidence?: unknown;
}): Promise<IndexSnapshot> => {
  const [row] = await sql<IndexSnapshotRow[]>`
    insert into index_snapshots (index_id, run_id, value, label, summary, evidence_json)
    values (
      ${input.indexId}, ${input.runId}, ${input.value}, ${input.label},
      ${input.summary}, ${sql.json((input.evidence ?? []) as JsonValue)}
    )
    returning
      id, index_id::text as "indexId", value::float8 as value, label, summary,
      evidence_json as "evidenceJson", captured_at as "capturedAt"
  `;
  return mapIndexSnapshot(row);
};

export const listIndexSnapshots = async (indexId: string, limit = 50) => {
  const rows = await sql<IndexSnapshotRow[]>`
    select
      id, index_id::text as "indexId", value::float8 as value, label, summary,
      evidence_json as "evidenceJson", captured_at as "capturedAt"
    from index_snapshots
    where index_id = ${indexId}
    order by captured_at desc
    limit ${Math.min(Math.max(limit, 1), 200)}
  `;
  return rows.map(mapIndexSnapshot);
};
