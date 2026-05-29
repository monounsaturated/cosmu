// module: Agent steps (per-agent execution records) + the generic human-approval gate.
import { z } from "zod";

export const agentStepStatusSchema = z.enum(["queued", "running", "success", "failure", "skipped"]);
export const agentScopeTypeSchema = z.enum(["bot_run", "research"]);

export const agentStepSchema = z.object({
  id: z.string().uuid(),
  scopeType: agentScopeTypeSchema,
  scopeId: z.string().uuid(),
  agentKey: z.string(),
  agentLabel: z.string(),
  status: agentStepStatusSchema,
  inputJson: z.unknown().nullable(),
  outputText: z.string().nullable(),
  outputJson: z.unknown().nullable(),
  toolCalls: z.unknown().nullable(),
  modelProvider: z.string().nullable(),
  model: z.string().nullable(),
  inputTokens: z.number().nullable(),
  outputTokens: z.number().nullable(),
  latencyMs: z.number().nullable(),
  error: z.string().nullable(),
  startedAt: z.string().datetime(),
  finishedAt: z.string().datetime().nullable()
});

export type AgentStep = z.infer<typeof agentStepSchema>;

export const approvalRequestSchema = z.object({
  id: z.string().uuid(),
  requestType: z.enum(["dangerous_action", "connector_permission"]),
  status: z.enum(["pending", "approved", "rejected", "cancelled"]),
  title: z.string(),
  body: z.string().nullable(),
  payload: z.unknown(),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime(),
  resolvedAt: z.string().datetime().nullable()
});

export type ApprovalRequest = z.infer<typeof approvalRequestSchema>;
