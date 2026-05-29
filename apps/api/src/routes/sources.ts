// module: Source routes — list and fetch auditable read-only data sources.
import { Router, type Router as ExpressRouter } from "express";
import { fetchSourceToObservations, getSourceDefinition, listSourceDefinitions } from "../sources/registry.js";

export const sourcesRouter: ExpressRouter = Router();

sourcesRouter.get("/sources", async (_request, response, next) => {
  try {
    response.json({ sources: listSourceDefinitions() });
  } catch (error) {
    next(error);
  }
});

sourcesRouter.get("/sources/:sourceKey", async (request, response, next) => {
  try {
    const source = getSourceDefinition(request.params.sourceKey);
    if (!source) {
      response.status(404).json({ error: "Source not found" });
      return;
    }
    response.json({ source });
  } catch (error) {
    next(error);
  }
});

sourcesRouter.post("/sources/:sourceKey/fetch", async (request, response, next) => {
  try {
    response.json(await fetchSourceToObservations(request.params.sourceKey, request.body));
  } catch (error) {
    next(error);
  }
});
