import type {
  ResearchCandidate,
  ResearchDataSource,
  ResearchExperiment,
  dataSourceKindSchema
} from "@cosmu/shared";
import { sql } from "../../db.js";
import { parseJson, type JsonValue } from "./helpers.js";
import type { z } from "zod";

type DataSourceKind = z.infer<typeof dataSourceKindSchema>;

type ResearchExperimentRow = Omit<ResearchExperiment, "createdAt" | "updatedAt"> & {
  createdAt: Date;
  updatedAt: Date;
};

type ResearchDataSourceRow = Omit<ResearchDataSource, "createdAt" | "updatedAt" | "lastCheckedAt"> & {
  createdAt: Date;
  updatedAt: Date;
  lastCheckedAt: Date | null;
};

type ResearchCandidateRow = Omit<ResearchCandidate, "createdAt" | "updatedAt"> & {
  createdAt: Date;
  updatedAt: Date;
};

const mapExperiment = (row: ResearchExperimentRow): ResearchExperiment => ({
  ...row,
  planJson: row.planJson == null ? null : parseJson(row.planJson),
  resultJson: row.resultJson == null ? null : parseJson(row.resultJson),
  createdAt: row.createdAt.toISOString(),
  updatedAt: row.updatedAt.toISOString()
});

const mapDataSource = (row: ResearchDataSourceRow): ResearchDataSource => ({
  ...row,
  config: parseJson(row.config),
  lastCheckedAt: row.lastCheckedAt?.toISOString() ?? null,
  createdAt: row.createdAt.toISOString(),
  updatedAt: row.updatedAt.toISOString()
});

const mapCandidate = (row: ResearchCandidateRow): ResearchCandidate => ({
  ...row,
  metrics: row.metrics == null ? null : parseJson(row.metrics),
  createdAt: row.createdAt.toISOString(),
  updatedAt: row.updatedAt.toISOString()
});

export const createResearchExperiment = async (input: {
  title: string;
  hypothesis: string;
}) => {
  const [row] = await sql<ResearchExperimentRow[]>`
    insert into research_experiments (title, hypothesis, status, promotion_status)
    values (${input.title}, ${input.hypothesis}, 'draft', 'none')
    returning
      id,
      title,
      hypothesis,
      status,
      promotion_status as "promotionStatus",
      plan_json as "planJson",
      result_json as "resultJson",
      skeptic_verdict as "skepticVerdict",
      created_at as "createdAt",
      updated_at as "updatedAt"
  `;
  return mapExperiment(row);
};

export const updateResearchExperiment = async (input: {
  id: string;
  status?: ResearchExperiment["status"];
  promotionStatus?: ResearchExperiment["promotionStatus"];
  planJson?: unknown;
  resultJson?: unknown;
  skepticVerdict?: string | null;
}) => {
  const [row] = await sql<ResearchExperimentRow[]>`
    update research_experiments
    set status = coalesce(${input.status ?? null}, status),
        promotion_status = coalesce(${input.promotionStatus ?? null}, promotion_status),
        plan_json = coalesce(${sql.json((input.planJson ?? null) as JsonValue)}, plan_json),
        result_json = coalesce(${sql.json((input.resultJson ?? null) as JsonValue)}, result_json),
        skeptic_verdict = coalesce(${input.skepticVerdict ?? null}, skeptic_verdict),
        updated_at = now()
    where id = ${input.id}
    returning
      id,
      title,
      hypothesis,
      status,
      promotion_status as "promotionStatus",
      plan_json as "planJson",
      result_json as "resultJson",
      skeptic_verdict as "skepticVerdict",
      created_at as "createdAt",
      updated_at as "updatedAt"
  `;
  return row ? mapExperiment(row) : null;
};

export const getResearchExperiment = async (id: string) => {
  const [row] = await sql<ResearchExperimentRow[]>`
    select
      id,
      title,
      hypothesis,
      status,
      promotion_status as "promotionStatus",
      plan_json as "planJson",
      result_json as "resultJson",
      skeptic_verdict as "skepticVerdict",
      created_at as "createdAt",
      updated_at as "updatedAt"
    from research_experiments
    where id = ${id}
  `;
  return row ? mapExperiment(row) : null;
};

export const listResearchExperiments = async (limit = 50) => {
  const rows = await sql<ResearchExperimentRow[]>`
    select
      id,
      title,
      hypothesis,
      status,
      promotion_status as "promotionStatus",
      plan_json as "planJson",
      result_json as "resultJson",
      skeptic_verdict as "skepticVerdict",
      created_at as "createdAt",
      updated_at as "updatedAt"
    from research_experiments
    order by created_at desc
    limit ${Math.min(Math.max(limit, 1), 200)}
  `;
  return rows.map(mapExperiment);
};

export const listResearchDataSources = async () => {
  const rows = await sql<ResearchDataSourceRow[]>`
    select
      id,
      name,
      kind,
      enabled,
      config,
      health_status as "healthStatus",
      last_checked_at as "lastCheckedAt",
      created_at as "createdAt",
      updated_at as "updatedAt"
    from research_data_sources
    order by enabled desc, kind asc, name asc
  `;
  return rows.map(mapDataSource);
};

export const createResearchDataSource = async (input: {
  name: string;
  kind: DataSourceKind;
  enabled?: boolean;
  config?: unknown;
}) => {
  const [row] = await sql<ResearchDataSourceRow[]>`
    insert into research_data_sources (name, kind, enabled, config)
    values (
      ${input.name}, ${input.kind}, ${input.enabled ?? true},
      ${sql.json((input.config ?? {}) as JsonValue)}
    )
    returning
      id,
      name,
      kind,
      enabled,
      config,
      health_status as "healthStatus",
      last_checked_at as "lastCheckedAt",
      created_at as "createdAt",
      updated_at as "updatedAt"
  `;
  return mapDataSource(row);
};

export const createResearchCandidate = async (input: {
  experimentId: string;
  name: string;
  thesis: string;
  metrics?: unknown;
  riskNotes?: string | null;
}) => {
  const [row] = await sql<ResearchCandidateRow[]>`
    insert into research_candidates (experiment_id, name, status, thesis, metrics, risk_notes)
    values (
      ${input.experimentId}, ${input.name}, 'paper_ready', ${input.thesis},
      ${sql.json((input.metrics ?? null) as JsonValue)}, ${input.riskNotes ?? null}
    )
    returning
      id,
      experiment_id::text as "experimentId",
      name,
      status,
      thesis,
      metrics,
      risk_notes as "riskNotes",
      created_at as "createdAt",
      updated_at as "updatedAt"
  `;
  return mapCandidate(row);
};

export const listResearchCandidates = async (limit = 50) => {
  const rows = await sql<ResearchCandidateRow[]>`
    select
      id,
      experiment_id::text as "experimentId",
      name,
      status,
      thesis,
      metrics,
      risk_notes as "riskNotes",
      created_at as "createdAt",
      updated_at as "updatedAt"
    from research_candidates
    order by created_at desc
    limit ${Math.min(Math.max(limit, 1), 200)}
  `;
  return rows.map(mapCandidate);
};
