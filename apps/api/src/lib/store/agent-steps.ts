// module: Persist/read agent_steps — the product-level timeline of agent/tool phases.
import type { AgentStep } from "@cosmu/shared";
import { sql } from "../../db.js";
import { type JsonValue } from "./helpers.js";

type AgentStepRow = {
  id: string;
  scopeType: AgentStep["scopeType"];
  scopeId: string;
  agentKey: string;
  agentLabel: string;
  status: AgentStep["status"];
  inputJson: unknown | null;
  outputText: string | null;
  outputJson: unknown | null;
  toolCalls: unknown | null;
  modelProvider: string | null;
  model: string | null;
  inputTokens: number | null;
  outputTokens: number | null;
  latencyMs: number | null;
  error: string | null;
  startedAt: Date;
  finishedAt: Date | null;
};

const mapAgentStep = (row: AgentStepRow): AgentStep => ({
  ...row,
  startedAt: row.startedAt.toISOString(),
  finishedAt: row.finishedAt?.toISOString() ?? null
});

export type AgentStepInput = {
  scopeType: AgentStep["scopeType"];
  scopeId: string;
  agentKey: string;
  agentLabel: string;
  inputJson?: unknown;
  modelProvider?: string | null;
  model?: string | null;
};

export const createAgentStep = async (input: AgentStepInput) => {
  const [row] = await sql<{ id: string }[]>`
    insert into agent_steps (
      scope_type, scope_id, agent_key, agent_label, status,
      input_json, model_provider, model, started_at
    ) values (
      ${input.scopeType}, ${input.scopeId}, ${input.agentKey}, ${input.agentLabel}, 'running',
      ${sql.json((input.inputJson ?? null) as JsonValue)},
      ${input.modelProvider ?? null}, ${input.model ?? null}, now()
    )
    returning id
  `;
  return row.id;
};

export const finishAgentStep = async (input: {
  id: string;
  status: Extract<AgentStep["status"], "success" | "failure" | "skipped">;
  outputText?: string | null;
  outputJson?: unknown;
  toolCalls?: unknown;
  inputTokens?: number | null;
  outputTokens?: number | null;
  error?: string | null;
}) => {
  await sql`
    update agent_steps
    set status = ${input.status},
        output_text = ${input.outputText ?? null},
        output_json = ${sql.json((input.outputJson ?? null) as JsonValue)},
        tool_calls = ${sql.json((input.toolCalls ?? null) as JsonValue)},
        input_tokens = ${input.inputTokens ?? null},
        output_tokens = ${input.outputTokens ?? null},
        latency_ms = greatest(0, floor(extract(epoch from (now() - started_at)) * 1000))::int,
        error = ${input.error ?? null},
        finished_at = now()
    where id = ${input.id}
  `;
};

export const recordAgentStep = async (input: AgentStepInput & {
  status?: Extract<AgentStep["status"], "success" | "failure" | "skipped">;
  outputText?: string | null;
  outputJson?: unknown;
  toolCalls?: unknown;
  inputTokens?: number | null;
  outputTokens?: number | null;
  error?: string | null;
}) => {
  const stepId = await createAgentStep(input);
  await finishAgentStep({
    id: stepId,
    status: input.status ?? "success",
    outputText: input.outputText,
    outputJson: input.outputJson,
    toolCalls: input.toolCalls,
    inputTokens: input.inputTokens,
    outputTokens: input.outputTokens,
    error: input.error
  });
  return stepId;
};

export const listAgentSteps = async (input: {
  scopeType?: AgentStep["scopeType"];
  scopeId?: string;
  limit?: number;
}) => {
  const limit = Math.min(Math.max(input.limit ?? 100, 1), 500);
  const rows = await sql<AgentStepRow[]>`
    select
      id,
      scope_type as "scopeType",
      scope_id::text as "scopeId",
      agent_key as "agentKey",
      agent_label as "agentLabel",
      status,
      input_json as "inputJson",
      output_text as "outputText",
      output_json as "outputJson",
      tool_calls as "toolCalls",
      model_provider as "modelProvider",
      model,
      input_tokens as "inputTokens",
      output_tokens as "outputTokens",
      latency_ms as "latencyMs",
      error,
      started_at as "startedAt",
      finished_at as "finishedAt"
    from agent_steps
    where (${input.scopeType ?? null}::text is null or scope_type = ${input.scopeType ?? null})
      and (${input.scopeId ?? null}::uuid is null or scope_id = ${input.scopeId ?? null})
    order by started_at asc
    limit ${limit}
  `;
  return rows.map(mapAgentStep);
};

export type ApprovalRequest = {
  id: string;
  requestType: "dangerous_action" | "connector_permission";
  status: "pending" | "approved" | "rejected" | "cancelled";
  title: string;
  body: string | null;
  payload: unknown;
  createdAt: string;
  updatedAt: string;
  resolvedAt: string | null;
};

type ApprovalRequestRow = Omit<ApprovalRequest, "createdAt" | "updatedAt" | "resolvedAt"> & {
  createdAt: Date;
  updatedAt: Date;
  resolvedAt: Date | null;
};

const mapApproval = (row: ApprovalRequestRow): ApprovalRequest => ({
  ...row,
  payload: typeof row.payload === "string" ? JSON.parse(row.payload) : row.payload,
  createdAt: row.createdAt.toISOString(),
  updatedAt: row.updatedAt.toISOString(),
  resolvedAt: row.resolvedAt?.toISOString() ?? null
});

export const createApprovalRequest = async (input: {
  requestType: ApprovalRequest["requestType"];
  title: string;
  body?: string | null;
  payload?: unknown;
}) => {
  const [row] = await sql<ApprovalRequestRow[]>`
    insert into approval_requests (request_type, title, body, payload)
    values (
      ${input.requestType}, ${input.title}, ${input.body ?? null},
      ${sql.json((input.payload ?? {}) as JsonValue)}
    )
    returning
      id,
      request_type as "requestType",
      status,
      title,
      body,
      payload,
      created_at as "createdAt",
      updated_at as "updatedAt",
      resolved_at as "resolvedAt"
  `;
  return mapApproval(row);
};

export const listApprovalRequests = async (filter?: { status?: ApprovalRequest["status"] }) => {
  const rows = filter?.status
    ? await sql<ApprovalRequestRow[]>`
        select
          id,
          request_type as "requestType",
          status,
          title,
          body,
          payload,
          created_at as "createdAt",
          updated_at as "updatedAt",
          resolved_at as "resolvedAt"
        from approval_requests
        where status = ${filter.status}
        order by created_at desc
        limit 100
      `
    : await sql<ApprovalRequestRow[]>`
        select
          id,
          request_type as "requestType",
          status,
          title,
          body,
          payload,
          created_at as "createdAt",
          updated_at as "updatedAt",
          resolved_at as "resolvedAt"
        from approval_requests
        order by created_at desc
        limit 100
      `;
  return rows.map(mapApproval);
};

export const getApprovalRequest = async (id: string) => {
  const [row] = await sql<ApprovalRequestRow[]>`
    select
      id,
      request_type as "requestType",
      status,
      title,
      body,
      payload,
      created_at as "createdAt",
      updated_at as "updatedAt",
      resolved_at as "resolvedAt"
    from approval_requests
    where id = ${id}
  `;
  return row ? mapApproval(row) : null;
};

export const updateApprovalStatus = async (input: {
  id: string;
  status: Extract<ApprovalRequest["status"], "approved" | "rejected" | "cancelled">;
}) => {
  const [row] = await sql<ApprovalRequestRow[]>`
    update approval_requests
    set status = ${input.status},
        updated_at = now(),
        resolved_at = now()
    where id = ${input.id}
      and status = 'pending'
    returning
      id,
      request_type as "requestType",
      status,
      title,
      body,
      payload,
      created_at as "createdAt",
      updated_at as "updatedAt",
      resolved_at as "resolvedAt"
  `;
  return row ? mapApproval(row) : null;
};

export const getAgentControlSummary = async () => {
  const [row] = await sql<{
    runningAgents: number;
    failedAgents: number;
    pendingApprovals: number;
    runningResearch: number;
  }[]>`
    select
      (select count(*)::int from agent_steps where status = 'running') as "runningAgents",
      (select count(*)::int from agent_steps where status = 'failure' and started_at > now() - interval '24 hours') as "failedAgents",
      (select count(*)::int from approval_requests where status = 'pending') as "pendingApprovals",
      (select count(*)::int from research_experiments where status = 'running') as "runningResearch"
  `;
  return {
    ...(row ?? { runningAgents: 0, failedAgents: 0, pendingApprovals: 0, runningResearch: 0 }),
    liveActionsGated: true,
    cappedAutoliveEnabled: false
  };
};

