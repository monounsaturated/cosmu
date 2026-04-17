#!/usr/bin/env node
/**
 * Cosmu Binance MCP Server
 *
 * A Model Context Protocol server that exposes Binance market data and account
 * tools over JSON-RPC 2.0 on stdio. Compatible with Claude Desktop, Claude Code,
 * and any MCP-compatible client.
 *
 * Usage:
 *   BINANCE_API_KEY=... BINANCE_API_SECRET=... npx tsx apps/mcp-server/src/index.ts
 *
 * Claude Desktop config (~/.claude/claude_desktop_config.json):
 *   {
 *     "mcpServers": {
 *       "cosmu-binance": {
 *         "command": "node",
 *         "args": ["<path>/apps/mcp-server/dist/apps/mcp-server/src/index.js"],
 *         "env": { "BINANCE_API_KEY": "...", "BINANCE_API_SECRET": "..." }
 *       }
 *     }
 *   }
 */
import "./env.js"; // validate env early
import { createInterface } from "node:readline";
import { tools } from "./tools.js";

const SERVER_NAME = "cosmu-binance";
const SERVER_VERSION = "0.1.0";
const PROTOCOL_VERSION = "2024-11-05";

/* ── JSON-RPC helpers ── */

type JsonRpcRequest = {
  jsonrpc: "2.0";
  id?: string | number | null;
  method: string;
  params?: Record<string, unknown>;
};

function jsonRpcResponse(id: string | number | null, result: unknown) {
  return JSON.stringify({ jsonrpc: "2.0", id, result });
}

function jsonRpcError(id: string | number | null, code: number, message: string) {
  return JSON.stringify({ jsonrpc: "2.0", id, error: { code, message } });
}

/* ── MCP method handlers ── */

function handleInitialize(id: string | number | null) {
  return jsonRpcResponse(id, {
    protocolVersion: PROTOCOL_VERSION,
    capabilities: {
      tools: {}
    },
    serverInfo: {
      name: SERVER_NAME,
      version: SERVER_VERSION
    }
  });
}

function handleToolsList(id: string | number | null) {
  return jsonRpcResponse(id, {
    tools: tools.map((t) => ({
      name: t.name,
      description: t.description,
      inputSchema: t.inputSchema
    }))
  });
}

async function handleToolsCall(id: string | number | null, params: Record<string, unknown>) {
  const toolName = params.name as string;
  const args = (params.arguments ?? {}) as Record<string, unknown>;

  const tool = tools.find((t) => t.name === toolName);
  if (!tool) {
    return jsonRpcResponse(id, {
      content: [{ type: "text", text: `Unknown tool: ${toolName}` }],
      isError: true
    });
  }

  try {
    const result = await tool.handler(args);
    const text = typeof result === "string" ? result : JSON.stringify(result, null, 2);
    return jsonRpcResponse(id, {
      content: [{ type: "text", text }]
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return jsonRpcResponse(id, {
      content: [{ type: "text", text: `Error: ${message}` }],
      isError: true
    });
  }
}

/* ── Main loop ── */

const rl = createInterface({ input: process.stdin, terminal: false });

rl.on("line", async (line) => {
  const trimmed = line.trim();
  if (!trimmed) return;

  let request: JsonRpcRequest;
  try {
    request = JSON.parse(trimmed);
  } catch {
    process.stdout.write(jsonRpcError(null, -32700, "Parse error") + "\n");
    return;
  }

  const { id, method, params } = request;

  // Notifications (no id) — just ack silently
  if (id === undefined || id === null) {
    // "notifications/initialized" is the only expected notification
    return;
  }

  let response: string;

  switch (method) {
    case "initialize":
      response = handleInitialize(id);
      break;
    case "tools/list":
      response = handleToolsList(id);
      break;
    case "tools/call":
      response = await handleToolsCall(id, (params ?? {}) as Record<string, unknown>);
      break;
    case "ping":
      response = jsonRpcResponse(id, {});
      break;
    default:
      response = jsonRpcError(id, -32601, `Method not found: ${method}`);
  }

  process.stdout.write(response + "\n");
});

rl.on("close", () => {
  process.exit(0);
});

// Log to stderr so it doesn't pollute the JSON-RPC stream
process.stderr.write(`[${SERVER_NAME}] MCP server started (protocol ${PROTOCOL_VERSION})\n`);
