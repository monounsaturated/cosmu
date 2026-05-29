// module: Machine-readable OpenAPI doc for agent/tool discovery. Public (no x-api-key), like /health.
// Hand-authored on purpose: schemas are defined by hand in @cosmu/shared (no generator dep), so this
// documents the main public endpoints + reuses tradingDecisionJsonSchema. Extend as routes stabilize.
import { Router, type Router as ExpressRouter } from "express";
import { tradingDecisionJsonSchema } from "@cosmu/shared";

export const OPENAPI_PUBLIC_PATH = "/openapi.json";

const okJson = { description: "OK", content: { "application/json": { schema: { type: "object" } } } } as const;

const openapiDocument = {
  openapi: "3.1.0",
  info: {
    title: "Cosmu API",
    version: "2.0.0",
    description:
      "Autonomous crypto-trading platform. Pipeline: Research -> Trader -> deterministic Validator -> Execution. All endpoints except /health and /openapi.json require an x-api-key header."
  },
  servers: [{ url: "/", description: "Cosmu API (Railway)" }],
  components: {
    securitySchemes: {
      apiKey: { type: "apiKey", in: "header", name: "x-api-key" }
    },
    schemas: {
      TradingDecision: tradingDecisionJsonSchema
    }
  },
  security: [{ apiKey: [] }],
  paths: {
    "/health": {
      get: { summary: "Liveness probe", security: [], responses: { "200": okJson } }
    },
    "/openapi.json": {
      get: { summary: "This document", security: [], responses: { "200": okJson } }
    },
    "/dashboard": {
      get: { summary: "Cached dashboard payload (prices, balances, agents, spend)", responses: { "200": okJson } }
    },
    "/mcp/tools": {
      get: { summary: "Registered agent-facing tool definitions", responses: { "200": okJson } }
    },
    "/bots": {
      get: { summary: "List bots/agents", responses: { "200": okJson } },
      post: { summary: "Create a bot/agent", responses: { "200": okJson } }
    },
    "/bots/{botId}": {
      get: { summary: "Get a bot/agent", parameters: [{ name: "botId", in: "path", required: true, schema: { type: "string" } }], responses: { "200": okJson } }
    },
    "/bots/{botId}/run": {
      post: { summary: "Run one pipeline cycle for a bot now", parameters: [{ name: "botId", in: "path", required: true, schema: { type: "string" } }], responses: { "200": okJson } }
    },
    "/bots/{botId}/kill": {
      post: { summary: "Disable a bot and liquidate its positions", parameters: [{ name: "botId", in: "path", required: true, schema: { type: "string" } }], responses: { "200": okJson } }
    },
    "/bots/{botId}/runs": {
      get: { summary: "List recent runs for a bot", parameters: [{ name: "botId", in: "path", required: true, schema: { type: "string" } }], responses: { "200": okJson } }
    },
    "/runs/{runId}": {
      get: { summary: "Run detail (decision, validation, executions, snapshots)", parameters: [{ name: "runId", in: "path", required: true, schema: { type: "string" } }], responses: { "200": okJson } }
    },
    "/runs/{runId}/llm-calls": {
      get: { summary: "Low-level LLM call telemetry for a run", parameters: [{ name: "runId", in: "path", required: true, schema: { type: "string" } }], responses: { "200": okJson } }
    },
    "/signals": { get: { summary: "List standardized signals", responses: { "200": okJson } } },
    "/indexes": { get: { summary: "List index configs", responses: { "200": okJson } } },
    "/internal/diagnostics": { get: { summary: "Runtime diagnostics (scheduler, providers, venue health)", responses: { "200": okJson } } }
  }
} as const;

export const openapiRouter: ExpressRouter = Router();

openapiRouter.get(OPENAPI_PUBLIC_PATH, (_request, response) => {
  response.json(openapiDocument);
});
