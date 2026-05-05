import type { ResearchEngine } from "@cosmu/shared";
import type { ResearchEngineAdapter } from "./types.js";

const nativeEngine: ResearchEngineAdapter = {
  key: "native",
  async run(input) {
    const universe = Array.from(new Set(input.spec.universe as string[] ?? ["BTCUSDT", "ETHUSDT"])).slice(0, 12);
    return {
      summary: `Native engine prepared a TradingAgents-style research brief for ${universe.join(", ")}.`,
      proposedSpec: {
        ...input.spec,
        hypothesis: input.hypothesis,
        universe,
        methodology: {
          split: "train/validation/test temporal split",
          validation: "walk_forward",
          feesSlippage: true,
          benchmark: "buy_and_hold"
        }
      },
      memoryNotes: [
        {
          title: "Native engine research brief",
          text: "Spec drafted with temporal split, walk-forward, and cost realism requirements.",
          confidence: 0.65
        }
      ],
      logs: "native_engine:spec_ready"
    };
  }
};

const externalStub = (key: Extract<ResearchEngine, "hermes" | "autoresearch" | "openclaw">): ResearchEngineAdapter => ({
  key,
  async run(input) {
    return {
      summary: `${key} sidecar is not wired yet. Run request stored with objective and dataset scope.`,
      proposedSpec: {
        ...input.spec,
        requestedEngine: key,
        sidecarStatus: "stubbed",
        objective: input.objective
      },
      memoryNotes: [
        {
          title: `${key} sidecar placeholder`,
          text: `Run captured for ${key} sidecar execution. External adapter wiring pending.`,
          confidence: 0.4
        }
      ],
      logs: `${key}_sidecar:placeholder`
    };
  }
});

const engines: Record<ResearchEngine, ResearchEngineAdapter> = {
  native: nativeEngine,
  hermes: externalStub("hermes"),
  autoresearch: externalStub("autoresearch"),
  openclaw: externalStub("openclaw")
};

export const getResearchEngine = (key: ResearchEngine) => engines[key];
