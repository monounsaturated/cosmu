import type {
  Dataset,
  DatasetVersion,
  EvaluationJob,
  EvaluationResult,
  ExperimentSpec,
  ResearchEngineRun,
  ResearchMemory,
  ResearchSession
} from "@cosmu/shared";
import { sql } from "../../db.js";
import { parseJson, type JsonValue } from "./helpers.js";

type DatasetRow = Omit<Dataset, "createdAt" | "updatedAt"> & {
  createdAt: Date;
  updatedAt: Date;
};

type DatasetVersionRow = Omit<DatasetVersion, "createdAt" | "startAt" | "endAt"> & {
  createdAt: Date;
  startAt: Date | null;
  endAt: Date | null;
};

type SessionRow = Omit<ResearchSession, "createdAt" | "updatedAt"> & {
  createdAt: Date;
  updatedAt: Date;
};

type EngineRunRow = Omit<ResearchEngineRun, "createdAt" | "startedAt" | "finishedAt"> & {
  createdAt: Date;
  startedAt: Date | null;
  finishedAt: Date | null;
};

type SpecRow = Omit<ExperimentSpec, "createdAt"> & {
  createdAt: Date;
};

type EvalResultRow = Omit<EvaluationResult, "createdAt"> & {
  createdAt: Date;
};

type EvalJobRow = Omit<EvaluationJob, "createdAt" | "startedAt" | "finishedAt" | "result"> & {
  createdAt: Date;
  startedAt: Date | null;
  finishedAt: Date | null;
  result?: EvalResultRow | null;
};

type MemoryRow = Omit<ResearchMemory, "createdAt" | "updatedAt"> & {
  createdAt: Date;
  updatedAt: Date;
};

const mapDataset = (row: DatasetRow): Dataset => ({
  ...row,
  tags: Array.isArray(row.tags) ? row.tags.map((value) => String(value)) : [],
  description: row.description ?? null,
  createdAt: row.createdAt.toISOString(),
  updatedAt: row.updatedAt.toISOString()
});

const mapDatasetVersion = (row: DatasetVersionRow): DatasetVersion => ({
  ...row,
  schemaJson: parseJson(row.schemaJson),
  metadataJson: parseJson(row.metadataJson),
  startAt: row.startAt?.toISOString() ?? null,
  endAt: row.endAt?.toISOString() ?? null,
  contentHash: row.contentHash ?? null,
  createdAt: row.createdAt.toISOString()
});

const mapSession = (row: SessionRow): ResearchSession => ({
  ...row,
  allowedTools: Array.isArray(row.allowedTools) ? row.allowedTools.map((value) => String(value)) : [],
  datasetVersionIds: Array.isArray(row.datasetVersionIds)
    ? row.datasetVersionIds.map((value) => String(value))
    : [],
  stopReason: row.stopReason ?? null,
  modelProfileId: row.modelProfileId ?? null,
  createdAt: row.createdAt.toISOString(),
  updatedAt: row.updatedAt.toISOString()
});

const mapEngineRun = (row: EngineRunRow): ResearchEngineRun => ({
  ...row,
  inputJson: parseJson(row.inputJson),
  outputJson: row.outputJson == null ? null : parseJson(row.outputJson),
  logsText: row.logsText ?? null,
  error: row.error ?? null,
  startedAt: row.startedAt?.toISOString() ?? null,
  finishedAt: row.finishedAt?.toISOString() ?? null,
  createdAt: row.createdAt.toISOString()
});

const mapSpec = (row: SpecRow): ExperimentSpec => ({
  ...row,
  specJson: parseJson(row.specJson),
  createdAt: row.createdAt.toISOString()
});

const mapResult = (row: EvalResultRow): EvaluationResult => ({
  ...row,
  metricsJson: parseJson(row.metricsJson),
  splitSummaryJson: parseJson(row.splitSummaryJson),
  artifactsJson: parseJson(row.artifactsJson),
  gatesJson: parseJson(row.gatesJson),
  createdAt: row.createdAt.toISOString()
});

const mapEvalJob = (row: EvalJobRow): EvaluationJob => ({
  ...row,
  datasetVersionIds: Array.isArray(row.datasetVersionIds) ? row.datasetVersionIds.map((value) => String(value)) : [],
  configJson: parseJson(row.configJson),
  error: row.error ?? null,
  startedAt: row.startedAt?.toISOString() ?? null,
  finishedAt: row.finishedAt?.toISOString() ?? null,
  createdAt: row.createdAt.toISOString(),
  result: row.result ? mapResult(row.result) : null
});

const mapMemory = (row: MemoryRow): ResearchMemory => ({
  ...row,
  sessionId: row.sessionId ?? null,
  evidenceJson: parseJson(row.evidenceJson),
  createdAt: row.createdAt.toISOString(),
  updatedAt: row.updatedAt.toISOString()
});

export const listDatasets = async () => {
  const rows = await sql<DatasetRow[]>`
    select
      id, name, source_kind as "sourceKind", description, tags, active,
      created_at as "createdAt", updated_at as "updatedAt"
    from datasets
    order by active desc, created_at desc
  `;
  return rows.map(mapDataset);
};

export const createDataset = async (input: {
  name: string;
  sourceKind: Dataset["sourceKind"];
  description?: string | null;
  tags?: string[];
}) => {
  const [row] = await sql<DatasetRow[]>`
    insert into datasets (name, source_kind, description, tags)
    values (
      ${input.name},
      ${input.sourceKind},
      ${input.description ?? null},
      ${sql.json((input.tags ?? []) as JsonValue)}
    )
    returning
      id, name, source_kind as "sourceKind", description, tags, active,
      created_at as "createdAt", updated_at as "updatedAt"
  `;
  return mapDataset(row);
};

export const createDatasetVersion = async (input: {
  datasetId: string;
  schemaJson?: unknown;
  metadataJson?: unknown;
  rowCount?: number | null;
  startAt?: string | null;
  endAt?: string | null;
  contentJson?: unknown;
  contentHash?: string | null;
}) => {
  const [indexRow] = await sql<{ nextVersion: number }[]>`
    select coalesce(max(version_number), 0) + 1 as "nextVersion"
    from dataset_versions
    where dataset_id = ${input.datasetId}
  `;

  const [row] = await sql<DatasetVersionRow[]>`
    insert into dataset_versions (
      dataset_id, version_number, schema_json, metadata_json, row_count, start_at, end_at, content_json, content_hash
    ) values (
      ${input.datasetId},
      ${indexRow.nextVersion},
      ${sql.json((input.schemaJson ?? {}) as JsonValue)},
      ${sql.json((input.metadataJson ?? {}) as JsonValue)},
      ${input.rowCount ?? null},
      ${input.startAt ?? null}::timestamptz,
      ${input.endAt ?? null}::timestamptz,
      ${sql.json((input.contentJson ?? null) as JsonValue)},
      ${input.contentHash ?? null}
    )
    returning
      id, dataset_id::text as "datasetId", version_number as "versionNumber",
      schema_json as "schemaJson", metadata_json as "metadataJson",
      row_count as "rowCount", start_at as "startAt", end_at as "endAt",
      content_hash as "contentHash", created_at as "createdAt"
  `;
  return mapDatasetVersion(row);
};

export const listDatasetVersions = async (datasetId: string) => {
  const rows = await sql<DatasetVersionRow[]>`
    select
      id, dataset_id::text as "datasetId", version_number as "versionNumber",
      schema_json as "schemaJson", metadata_json as "metadataJson",
      row_count as "rowCount", start_at as "startAt", end_at as "endAt",
      content_hash as "contentHash", created_at as "createdAt"
    from dataset_versions
    where dataset_id = ${datasetId}
    order by version_number desc
  `;
  return rows.map(mapDatasetVersion);
};

export const getDatasetVersion = async (versionId: string) => {
  const [row] = await sql<(DatasetVersionRow & { contentJson: unknown | null })[]>`
    select
      id, dataset_id::text as "datasetId", version_number as "versionNumber",
      schema_json as "schemaJson", metadata_json as "metadataJson",
      row_count as "rowCount", start_at as "startAt", end_at as "endAt",
      content_hash as "contentHash", content_json as "contentJson", created_at as "createdAt"
    from dataset_versions
    where id = ${versionId}
    limit 1
  `;
  if (!row) return null;
  return {
    ...mapDatasetVersion(row),
    contentJson: row.contentJson == null ? null : parseJson(row.contentJson)
  };
};

export const createResearchSession = async (input: {
  title: string;
  objective: string;
  engine: ResearchSession["engine"];
  autonomyMode: ResearchSession["autonomyMode"];
  maxIterations?: number;
  maxRuntimeMinutes?: number;
  maxCostUsd?: number;
  allowedTools?: string[];
  modelProfileId?: string | null;
  datasetVersionIds?: string[];
}) => {
  const [row] = await sql<SessionRow[]>`
    insert into research_sessions (
      title, objective, engine, autonomy_mode, status,
      max_iterations, max_runtime_minutes, max_cost_usd,
      allowed_tools, model_profile_id
    ) values (
      ${input.title}, ${input.objective}, ${input.engine}, ${input.autonomyMode}, 'queued',
      ${input.maxIterations ?? 3}, ${input.maxRuntimeMinutes ?? 30}, ${input.maxCostUsd ?? 10},
      ${sql.json((input.allowedTools ?? []) as JsonValue)},
      ${input.modelProfileId ?? null}
    )
    returning
      id, title, objective, engine, autonomy_mode as "autonomyMode", status,
      model_profile_id::text as "modelProfileId",
      max_iterations as "maxIterations",
      max_runtime_minutes as "maxRuntimeMinutes",
      max_cost_usd::float8 as "maxCostUsd",
      allowed_tools as "allowedTools",
      stop_reason as "stopReason",
      created_at as "createdAt", updated_at as "updatedAt",
      '[]'::jsonb as "datasetVersionIds"
  `;

  if (input.datasetVersionIds && input.datasetVersionIds.length > 0) {
    for (const versionId of input.datasetVersionIds) {
      await sql`
        insert into research_session_datasets (session_id, dataset_version_id)
        values (${row.id}, ${versionId}::uuid)
        on conflict do nothing
      `;
    }
  }

  return getResearchSession(row.id);
};

export const listResearchSessions = async (limit = 50) => {
  const rows = await sql<SessionRow[]>`
    select
      rs.id, rs.title, rs.objective, rs.engine, rs.autonomy_mode as "autonomyMode", rs.status,
      rs.model_profile_id::text as "modelProfileId",
      rs.max_iterations as "maxIterations",
      rs.max_runtime_minutes as "maxRuntimeMinutes",
      rs.max_cost_usd::float8 as "maxCostUsd",
      rs.allowed_tools as "allowedTools",
      rs.stop_reason as "stopReason",
      rs.created_at as "createdAt", rs.updated_at as "updatedAt",
      coalesce(
        (
          select jsonb_agg(rsd.dataset_version_id::text order by rsd.created_at asc)
          from research_session_datasets rsd
          where rsd.session_id = rs.id
        ),
        '[]'::jsonb
      ) as "datasetVersionIds"
    from research_sessions rs
    order by rs.created_at desc
    limit ${Math.min(Math.max(limit, 1), 200)}
  `;
  return rows.map(mapSession);
};

export const getResearchSession = async (sessionId: string) => {
  const [row] = await sql<SessionRow[]>`
    select
      rs.id, rs.title, rs.objective, rs.engine, rs.autonomy_mode as "autonomyMode", rs.status,
      rs.model_profile_id::text as "modelProfileId",
      rs.max_iterations as "maxIterations",
      rs.max_runtime_minutes as "maxRuntimeMinutes",
      rs.max_cost_usd::float8 as "maxCostUsd",
      rs.allowed_tools as "allowedTools",
      rs.stop_reason as "stopReason",
      rs.created_at as "createdAt", rs.updated_at as "updatedAt",
      coalesce(
        (
          select jsonb_agg(rsd.dataset_version_id::text order by rsd.created_at asc)
          from research_session_datasets rsd
          where rsd.session_id = rs.id
        ),
        '[]'::jsonb
      ) as "datasetVersionIds"
    from research_sessions rs
    where rs.id = ${sessionId}
    limit 1
  `;
  return row ? mapSession(row) : null;
};

export const updateResearchSession = async (input: {
  id: string;
  status?: ResearchSession["status"];
  stopReason?: string | null;
}) => {
  const [row] = await sql<SessionRow[]>`
    update research_sessions
    set status = coalesce(${input.status ?? null}, status),
        stop_reason = coalesce(${input.stopReason ?? null}, stop_reason),
        updated_at = now()
    where id = ${input.id}
    returning
      id, title, objective, engine, autonomy_mode as "autonomyMode", status,
      model_profile_id::text as "modelProfileId",
      max_iterations as "maxIterations",
      max_runtime_minutes as "maxRuntimeMinutes",
      max_cost_usd::float8 as "maxCostUsd",
      allowed_tools as "allowedTools",
      stop_reason as "stopReason",
      created_at as "createdAt", updated_at as "updatedAt",
      '[]'::jsonb as "datasetVersionIds"
  `;
  return row ? getResearchSession(row.id) : null;
};

export const createResearchEngineRun = async (input: {
  sessionId: string;
  engine: ResearchEngineRun["engine"];
  inputJson?: unknown;
}) => {
  const [row] = await sql<EngineRunRow[]>`
    insert into research_engine_runs (session_id, engine, status, input_json)
    values (${input.sessionId}, ${input.engine}, 'queued', ${sql.json((input.inputJson ?? {}) as JsonValue)})
    returning
      id, session_id::text as "sessionId", engine, status,
      input_json as "inputJson", output_json as "outputJson",
      logs_text as "logsText", error, started_at as "startedAt", finished_at as "finishedAt",
      created_at as "createdAt"
  `;
  return mapEngineRun(row);
};

export const listResearchEngineRuns = async (sessionId: string) => {
  const rows = await sql<EngineRunRow[]>`
    select
      id, session_id::text as "sessionId", engine, status,
      input_json as "inputJson", output_json as "outputJson",
      logs_text as "logsText", error, started_at as "startedAt", finished_at as "finishedAt",
      created_at as "createdAt"
    from research_engine_runs
    where session_id = ${sessionId}
    order by created_at desc
  `;
  return rows.map(mapEngineRun);
};

export const updateResearchEngineRun = async (input: {
  id: string;
  status?: ResearchEngineRun["status"];
  outputJson?: unknown;
  logsText?: string | null;
  error?: string | null;
  started?: boolean;
  finished?: boolean;
}) => {
  const [row] = await sql<EngineRunRow[]>`
    update research_engine_runs
    set status = coalesce(${input.status ?? null}, status),
        output_json = coalesce(${sql.json((input.outputJson ?? null) as JsonValue)}, output_json),
        logs_text = coalesce(${input.logsText ?? null}, logs_text),
        error = coalesce(${input.error ?? null}, error),
        started_at = case when ${input.started ?? false} then coalesce(started_at, now()) else started_at end,
        finished_at = case when ${input.finished ?? false} then now() else finished_at end
    where id = ${input.id}
    returning
      id, session_id::text as "sessionId", engine, status,
      input_json as "inputJson", output_json as "outputJson",
      logs_text as "logsText", error, started_at as "startedAt", finished_at as "finishedAt",
      created_at as "createdAt"
  `;
  return row ? mapEngineRun(row) : null;
};

export const createExperimentSpec = async (input: {
  sessionId: string;
  hypothesis: string;
  specJson: unknown;
  createdBy?: string;
}) => {
  const [indexRow] = await sql<{ nextVersion: number }[]>`
    select coalesce(max(version_number), 0) + 1 as "nextVersion"
    from experiment_specs
    where session_id = ${input.sessionId}
  `;
  const [row] = await sql<SpecRow[]>`
    insert into experiment_specs (session_id, version_number, hypothesis, spec_json, status, created_by)
    values (
      ${input.sessionId}, ${indexRow.nextVersion}, ${input.hypothesis},
      ${sql.json(input.specJson as JsonValue)}, 'draft', ${input.createdBy ?? 'user'}
    )
    returning
      id, session_id::text as "sessionId", version_number as "versionNumber",
      hypothesis, spec_json as "specJson", status, created_by as "createdBy",
      created_at as "createdAt"
  `;
  return mapSpec(row);
};

export const listExperimentSpecs = async (sessionId: string) => {
  const rows = await sql<SpecRow[]>`
    select
      id, session_id::text as "sessionId", version_number as "versionNumber",
      hypothesis, spec_json as "specJson", status, created_by as "createdBy",
      created_at as "createdAt"
    from experiment_specs
    where session_id = ${sessionId}
    order by version_number desc
  `;
  return rows.map(mapSpec);
};

export const getExperimentSpec = async (specId: string) => {
  const [row] = await sql<SpecRow[]>`
    select
      id, session_id::text as "sessionId", version_number as "versionNumber",
      hypothesis, spec_json as "specJson", status, created_by as "createdBy",
      created_at as "createdAt"
    from experiment_specs
    where id = ${specId}
    limit 1
  `;
  return row ? mapSpec(row) : null;
};

export const updateExperimentSpec = async (input: {
  id: string;
  specJson?: unknown;
  status?: ExperimentSpec["status"];
}) => {
  const [row] = await sql<SpecRow[]>`
    update experiment_specs
    set spec_json = coalesce(${sql.json((input.specJson ?? null) as JsonValue)}, spec_json),
        status = coalesce(${input.status ?? null}, status)
    where id = ${input.id}
    returning
      id, session_id::text as "sessionId", version_number as "versionNumber",
      hypothesis, spec_json as "specJson", status, created_by as "createdBy",
      created_at as "createdAt"
  `;
  return row ? mapSpec(row) : null;
};

export const createEvaluationResult = async (input: {
  sessionId: string;
  specId: string;
  metricsJson: unknown;
  splitSummaryJson: unknown;
  artifactsJson?: unknown;
  gatesJson: unknown;
}) => {
  const [row] = await sql<EvalResultRow[]>`
    insert into evaluation_results (
      session_id, spec_id, metrics_json, split_summary_json, artifacts_json, gates_json
    ) values (
      ${input.sessionId}, ${input.specId},
      ${sql.json(input.metricsJson as JsonValue)},
      ${sql.json(input.splitSummaryJson as JsonValue)},
      ${sql.json((input.artifactsJson ?? {}) as JsonValue)},
      ${sql.json(input.gatesJson as JsonValue)}
    )
    returning
      id, session_id::text as "sessionId", spec_id::text as "specId",
      metrics_json as "metricsJson", split_summary_json as "splitSummaryJson",
      artifacts_json as "artifactsJson", gates_json as "gatesJson",
      created_at as "createdAt"
  `;
  return mapResult(row);
};

export const createEvaluationJob = async (input: {
  sessionId: string;
  specId: string;
  engineRunId?: string | null;
  kind: EvaluationJob["kind"];
  datasetVersionIds: string[];
  configJson?: unknown;
}) => {
  const [row] = await sql<EvalJobRow[]>`
    insert into evaluation_jobs (
      session_id, spec_id, engine_run_id, status, kind, dataset_version_ids, config_json
    ) values (
      ${input.sessionId}, ${input.specId}, ${input.engineRunId ?? null}, 'queued', ${input.kind},
      ${sql.json(input.datasetVersionIds as JsonValue)},
      ${sql.json((input.configJson ?? {}) as JsonValue)}
    )
    returning
      id, session_id::text as "sessionId", spec_id::text as "specId", engine_run_id::text as "engineRunId",
      status, kind, dataset_version_ids as "datasetVersionIds", config_json as "configJson",
      result_id::text as "resultId", error, started_at as "startedAt", finished_at as "finishedAt",
      created_at as "createdAt"
  `;
  return mapEvalJob(row);
};

export const updateEvaluationJob = async (input: {
  id: string;
  status?: EvaluationJob["status"];
  resultId?: string | null;
  error?: string | null;
  started?: boolean;
  finished?: boolean;
}) => {
  const [row] = await sql<EvalJobRow[]>`
    update evaluation_jobs
    set status = coalesce(${input.status ?? null}, status),
        result_id = coalesce(${input.resultId ?? null}::uuid, result_id),
        error = coalesce(${input.error ?? null}, error),
        started_at = case when ${input.started ?? false} then coalesce(started_at, now()) else started_at end,
        finished_at = case when ${input.finished ?? false} then now() else finished_at end
    where id = ${input.id}
    returning
      id, session_id::text as "sessionId", spec_id::text as "specId", engine_run_id::text as "engineRunId",
      status, kind, dataset_version_ids as "datasetVersionIds", config_json as "configJson",
      result_id::text as "resultId", error, started_at as "startedAt", finished_at as "finishedAt",
      created_at as "createdAt"
  `;
  return row ? mapEvalJob(row) : null;
};

export const listEvaluationJobs = async (sessionId: string) => {
  const rows = await sql<EvalJobRow[]>`
    select
      ej.id, ej.session_id::text as "sessionId", ej.spec_id::text as "specId",
      ej.engine_run_id::text as "engineRunId",
      ej.status, ej.kind, ej.dataset_version_ids as "datasetVersionIds", ej.config_json as "configJson",
      ej.result_id::text as "resultId", ej.error, ej.started_at as "startedAt", ej.finished_at as "finishedAt",
      ej.created_at as "createdAt"
    from evaluation_jobs ej
    where ej.session_id = ${sessionId}
    order by ej.created_at desc
  `;
  return rows.map(mapEvalJob);
};

export const getEvaluationJob = async (jobId: string) => {
  const [row] = await sql<EvalJobRow[]>`
    select
      ej.id, ej.session_id::text as "sessionId", ej.spec_id::text as "specId",
      ej.engine_run_id::text as "engineRunId",
      ej.status, ej.kind, ej.dataset_version_ids as "datasetVersionIds", ej.config_json as "configJson",
      ej.result_id::text as "resultId", ej.error, ej.started_at as "startedAt", ej.finished_at as "finishedAt",
      ej.created_at as "createdAt"
    from evaluation_jobs ej
    where ej.id = ${jobId}
    limit 1
  `;
  if (!row) return null;
  if (!row.resultId) return mapEvalJob(row);

  const [resultRow] = await sql<EvalResultRow[]>`
    select
      id, session_id::text as "sessionId", spec_id::text as "specId",
      metrics_json as "metricsJson", split_summary_json as "splitSummaryJson",
      artifacts_json as "artifactsJson", gates_json as "gatesJson", created_at as "createdAt"
    from evaluation_results
    where id = ${row.resultId}
    limit 1
  `;

  return {
    ...mapEvalJob(row),
    result: resultRow ? mapResult(resultRow) : null
  };
};

export const createResearchMemory = async (input: {
  sessionId?: string | null;
  scopeType: ResearchMemory["scopeType"];
  scopeKey: string;
  title: string;
  memoryText: string;
  evidenceJson?: unknown;
  confidence?: number;
}) => {
  const [row] = await sql<MemoryRow[]>`
    insert into research_memories (
      session_id, scope_type, scope_key, title, memory_text, evidence_json, confidence
    ) values (
      ${input.sessionId ?? null},
      ${input.scopeType},
      ${input.scopeKey},
      ${input.title},
      ${input.memoryText},
      ${sql.json((input.evidenceJson ?? {}) as JsonValue)},
      ${input.confidence ?? 0.5}
    )
    returning
      id, session_id::text as "sessionId", scope_type as "scopeType", scope_key as "scopeKey",
      title, memory_text as "memoryText", evidence_json as "evidenceJson",
      confidence::float8 as confidence, active, created_at as "createdAt", updated_at as "updatedAt"
  `;
  return mapMemory(row);
};

export const listResearchMemories = async (sessionId?: string) => {
  const rows = sessionId
    ? await sql<MemoryRow[]>`
        select
          id, session_id::text as "sessionId", scope_type as "scopeType", scope_key as "scopeKey",
          title, memory_text as "memoryText", evidence_json as "evidenceJson",
          confidence::float8 as confidence, active, created_at as "createdAt", updated_at as "updatedAt"
        from research_memories
        where session_id = ${sessionId}
        order by created_at desc
      `
    : await sql<MemoryRow[]>`
        select
          id, session_id::text as "sessionId", scope_type as "scopeType", scope_key as "scopeKey",
          title, memory_text as "memoryText", evidence_json as "evidenceJson",
          confidence::float8 as confidence, active, created_at as "createdAt", updated_at as "updatedAt"
        from research_memories
        order by created_at desc
        limit 200
      `;
  return rows.map(mapMemory);
};

export const updateResearchMemory = async (input: {
  id: string;
  active?: boolean;
  memoryText?: string;
  confidence?: number;
}) => {
  const [row] = await sql<MemoryRow[]>`
    update research_memories
    set active = coalesce(${input.active ?? null}, active),
        memory_text = coalesce(${input.memoryText ?? null}, memory_text),
        confidence = coalesce(${input.confidence ?? null}::numeric, confidence),
        updated_at = now()
    where id = ${input.id}
    returning
      id, session_id::text as "sessionId", scope_type as "scopeType", scope_key as "scopeKey",
      title, memory_text as "memoryText", evidence_json as "evidenceJson",
      confidence::float8 as confidence, active, created_at as "createdAt", updated_at as "updatedAt"
  `;
  return row ? mapMemory(row) : null;
};
