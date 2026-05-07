import { Router, type Router as ExpressRouter } from "express";

export const tradingAgentsRouter: ExpressRouter = Router();

const TRADING_AGENTS_URL = process.env.TRADING_AGENTS_URL || "http://localhost:8100";

async function proxy(path: string, options?: RequestInit) {
  const res = await fetch(`${TRADING_AGENTS_URL}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`TradingAgents service error (${res.status}): ${text}`);
  }
  return res.json();
}

tradingAgentsRouter.get("/trading-agents/health", async (_req, res, next) => {
  try {
    const data = await proxy("/health");
    res.json(data);
  } catch (error) {
    res.json({ status: "unavailable", error: String(error) });
  }
});

tradingAgentsRouter.post("/trading-agents/analyze", async (req, res, next) => {
  try {
    const data = await proxy("/analyze", {
      method: "POST",
      body: JSON.stringify(req.body),
    });
    res.json(data);
  } catch (error) {
    next(error);
  }
});

tradingAgentsRouter.get("/trading-agents/status/:requestId", async (req, res, next) => {
  try {
    const data = await proxy(`/status/${req.params.requestId}`);
    res.json(data);
  } catch (error) {
    next(error);
  }
});

tradingAgentsRouter.get("/trading-agents/results", async (_req, res, next) => {
  try {
    const data = await proxy("/results");
    res.json(data);
  } catch (error) {
    res.json([]);
  }
});
