import cors from "cors";
import express from "express";
import { env } from "./env.js";
import { getBotSetupById, getDashboard, getDueBots } from "./lib/store.js";
import { runBot } from "./services/run-bot.js";

const app = express();

app.use(cors());
app.use(express.json());

app.get("/health", async (_request, response) => {
  response.json({
    ok: true,
    mode: "runtime"
  });
});

app.get("/dashboard", async (_request, response, next) => {
  try {
    response.json(await getDashboard());
  } catch (error) {
    next(error);
  }
});

app.post("/bots/:botId/run", async (request, response, next) => {
  try {
    const bot = await getBotSetupById(request.params.botId);
    if (!bot) {
      response.status(404).json({ error: "Bot not found" });
      return;
    }

    const result = await runBot(bot);
    response.json(result);
  } catch (error) {
    next(error);
  }
});

app.post("/internal/scheduler/tick", async (_request, response, next) => {
  try {
    const dueBots = await getDueBots();
    const results = [];

    for (const bot of dueBots) {
      try {
        results.push(await runBot(bot));
      } catch (error) {
        results.push({
          botId: bot.id,
          status: "failure",
          error: error instanceof Error ? error.message : "Unknown run error"
        });
      }
    }

    response.json({
      checkedAt: new Date().toISOString(),
      dueBotCount: dueBots.length,
      results
    });
  } catch (error) {
    next(error);
  }
});

app.use((error: unknown, _request: express.Request, response: express.Response, _next: express.NextFunction) => {
  console.error(error);
  response.status(500).json({
    error: error instanceof Error ? error.message : "Unknown server error"
  });
});

app.listen(env.API_PORT, () => {
  console.log(`API listening on http://localhost:${env.API_PORT}`);
});
