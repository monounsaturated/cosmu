// module: API entrypoint — express bootstrap, auth gate, router mounting, error handler.
import cors from "cors";
import express from "express";
import { env } from "./env.js";
import { buildCorsOptions } from "./cors-options.js";
import { agentsRouter } from "./routes/agents.js";
import { researchRouter } from "./routes/research.js";
import { signalsRouter } from "./routes/signals.js";
import { tradingAgentsRouter } from "./routes/trading-agents.js";
import { systemRouter } from "./routes/system.js";
import { settingsRouter } from "./routes/settings.js";
import { venuesRouter } from "./routes/venues.js";
import { modelsRouter } from "./routes/models.js";
import { botsRouter } from "./routes/bots.js";
import { startRuntimeAutomation } from "./services/background-jobs.js";

const app = express();

process.on("unhandledRejection", (reason) => {
  console.error("[process] unhandled rejection:", reason);
});

process.on("uncaughtException", (error) => {
  console.error("[process] uncaught exception:", error);
  throw error;
});

const corsOptions = buildCorsOptions();
app.use(corsOptions ? cors(corsOptions) : cors());
app.use(express.json());

app.use((request, response, next) => {
  if (request.path === "/health") {
    return next();
  }

  const apiKey = request.headers["x-api-key"];
  if (apiKey !== env.API_SECRET_KEY) {
    response.status(401).json({ error: "Unauthorized" });
    return;
  }

  next();
});

app.use(agentsRouter);
app.use(researchRouter);
app.use(signalsRouter);
app.use(tradingAgentsRouter);
app.use(systemRouter);
app.use(settingsRouter);
app.use(venuesRouter);
app.use(modelsRouter);
app.use(botsRouter);

app.use((error: unknown, _request: express.Request, response: express.Response, _next: express.NextFunction) => {
  console.error(error);
  response.status(500).json({
    error: error instanceof Error ? error.message : "Unknown server error"
  });
});

app.listen(env.API_PORT, "0.0.0.0", () => {
  console.log(`API listening on http://0.0.0.0:${env.API_PORT}`);
  void startRuntimeAutomation();
});
