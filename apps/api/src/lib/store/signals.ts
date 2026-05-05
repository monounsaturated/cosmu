import type { RawObservation, StandardizedSignal } from "@cosmu/shared";
import { sql } from "../../db.js";
import { parseJson, type JsonValue } from "./helpers.js";

type RawObservationRow = Omit<RawObservation, "observedAt" | "capturedAt"> & {
  observedAt: Date;
  capturedAt: Date;
};

type StandardizedSignalRow = Omit<StandardizedSignal, "createdAt" | "updatedAt"> & {
  createdAt: Date;
  updatedAt: Date;
};

const mapObservation = (row: RawObservationRow): RawObservation => ({
  ...row,
  sourceUrl: row.sourceUrl ?? null,
  rawJson: row.rawJson == null ? null : parseJson(row.rawJson),
  contentHash: row.contentHash ?? null,
  observedAt: row.observedAt.toISOString(),
  capturedAt: row.capturedAt.toISOString()
});

const mapSignal = (row: StandardizedSignalRow): StandardizedSignal => ({
  ...row,
  observationId: row.observationId ?? null,
  symbol: row.symbol ?? null,
  horizon: row.horizon ?? null,
  evidenceJson: parseJson(row.evidenceJson),
  reasoningSummary: row.reasoningSummary ?? null,
  createdAt: row.createdAt.toISOString(),
  updatedAt: row.updatedAt.toISOString()
});

export const listRawObservations = async (limit = 50) => {
  const rows = await sql<RawObservationRow[]>`
    select
      id, source_kind as "sourceKind", source_name as "sourceName", source_url as "sourceUrl",
      observed_at as "observedAt", captured_at as "capturedAt",
      title, content, raw_json as "rawJson", content_hash as "contentHash"
    from raw_observations
    order by observed_at desc, captured_at desc
    limit ${Math.min(Math.max(limit, 1), 200)}
  `;
  return rows.map(mapObservation);
};

export const listStandardizedSignals = async (input: {
  limit?: number;
  status?: StandardizedSignal["status"];
  asset?: string;
} = {}) => {
  const limit = Math.min(Math.max(input.limit ?? 50, 1), 200);
  const rows = await sql<StandardizedSignalRow[]>`
    select
      id, observation_id::text as "observationId", asset, symbol, topic, direction,
      sentiment_score::float8 as "sentimentScore",
      confidence::float8 as confidence,
      urgency, horizon, summary, evidence_json as "evidenceJson",
      reasoning_summary as "reasoningSummary", status,
      created_at as "createdAt", updated_at as "updatedAt"
    from standardized_signals
    where (${input.status ?? null}::text is null or status = ${input.status ?? null})
      and (${input.asset ?? null}::text is null or lower(asset) = lower(${input.asset ?? null}))
    order by created_at desc
    limit ${limit}
  `;
  return rows.map(mapSignal);
};

export const createRawObservation = async (input: {
  sourceKind: RawObservation["sourceKind"];
  sourceName: string;
  sourceUrl?: string | null;
  observedAt?: string | null;
  title: string;
  content: string;
  rawJson?: unknown;
  contentHash?: string | null;
}) => {
  const [row] = await sql<RawObservationRow[]>`
    insert into raw_observations (
      source_kind, source_name, source_url, observed_at, title, content, raw_json, content_hash
    ) values (
      ${input.sourceKind},
      ${input.sourceName},
      ${input.sourceUrl ?? null},
      coalesce(${input.observedAt ?? null}::timestamptz, now()),
      ${input.title},
      ${input.content},
      ${sql.json((input.rawJson ?? null) as JsonValue)},
      ${input.contentHash ?? null}
    )
    on conflict (content_hash) where content_hash is not null do update
      set captured_at = now()
    returning
      id, source_kind as "sourceKind", source_name as "sourceName", source_url as "sourceUrl",
      observed_at as "observedAt", captured_at as "capturedAt",
      title, content, raw_json as "rawJson", content_hash as "contentHash"
  `;
  return mapObservation(row);
};

export const createStandardizedSignal = async (input: {
  observationId?: string | null;
  asset: string;
  symbol?: string | null;
  topic: string;
  direction: StandardizedSignal["direction"];
  sentimentScore: number;
  confidence: number;
  urgency: StandardizedSignal["urgency"];
  horizon?: string | null;
  summary: string;
  evidenceJson?: unknown;
  reasoningSummary?: string | null;
  status?: StandardizedSignal["status"];
}) => {
  const [row] = await sql<StandardizedSignalRow[]>`
    insert into standardized_signals (
      observation_id, asset, symbol, topic, direction, sentiment_score, confidence,
      urgency, horizon, summary, evidence_json, reasoning_summary, status
    ) values (
      ${input.observationId ?? null}::uuid,
      ${input.asset},
      ${input.symbol ?? null},
      ${input.topic},
      ${input.direction},
      ${input.sentimentScore},
      ${input.confidence},
      ${input.urgency},
      ${input.horizon ?? null},
      ${input.summary},
      ${sql.json((input.evidenceJson ?? []) as JsonValue)},
      ${input.reasoningSummary ?? null},
      ${input.status ?? "new"}
    )
    returning
      id, observation_id::text as "observationId", asset, symbol, topic, direction,
      sentiment_score::float8 as "sentimentScore",
      confidence::float8 as confidence,
      urgency, horizon, summary, evidence_json as "evidenceJson",
      reasoning_summary as "reasoningSummary", status,
      created_at as "createdAt", updated_at as "updatedAt"
  `;
  return mapSignal(row);
};

export const updateStandardizedSignalStatus = async (input: {
  id: string;
  status: StandardizedSignal["status"];
}) => {
  const [row] = await sql<StandardizedSignalRow[]>`
    update standardized_signals
    set status = ${input.status},
        updated_at = now()
    where id = ${input.id}
    returning
      id, observation_id::text as "observationId", asset, symbol, topic, direction,
      sentiment_score::float8 as "sentimentScore",
      confidence::float8 as confidence,
      urgency, horizon, summary, evidence_json as "evidenceJson",
      reasoning_summary as "reasoningSummary", status,
      created_at as "createdAt", updated_at as "updatedAt"
  `;
  return row ? mapSignal(row) : null;
};
