import type { AgentStep } from "@cosmu/shared";
import {
  createAgentStep,
  finishAgentStep,
  createResearchCandidate,
  getResearchExperiment,
  listResearchDataSources,
  updateResearchExperiment
} from "../lib/store.js";

type ResearchStepOutput = {
  outputText: string;
  outputJson: Record<string, unknown>;
};

const extractSymbols = (text: string) => {
  const explicitPairs = text.match(/\b[A-Z0-9]{2,10}USD[TC]\b/g) ?? [];
  const cashtags = (text.match(/\$[A-Za-z0-9]{2,10}\b/g) ?? []).map((value) => value.slice(1).toUpperCase());
  const knownAssets = [
    "BTC",
    "ETH",
    "SOL",
    "BNB",
    "DOGE",
    "XRP",
    "ADA",
    "AVAX",
    "LINK",
    "NVDA",
    "TSLA",
    "AAPL",
    "MSFT",
    "SPY",
    "QQQ"
  ];
  const knownMentions = knownAssets.filter((asset) =>
    new RegExp(`\\b${asset}\\b`, "i").test(text)
  );
  return Array.from(new Set([...explicitPairs, ...cashtags, ...knownMentions].map((value) => value.toUpperCase()))).slice(0, 12);
};

const inferDataKinds = (hypothesis: string) => {
  const h = hypothesis.toLowerCase();
  const kinds = new Set<string>(["market"]);
  if (/(news|headline|macro|fed|sec|earnings)/.test(h)) kinds.add("news");
  if (/(web|google|search|article)/.test(h)) kinds.add("web");
  if (/(tweet|x |twitter|social|sentiment)/.test(h)) kinds.add("social");
  if (/(weather|temperature|rain|storm|wind)/.test(h)) kinds.add("weather");
  if (/(astro|moon|lunar|planet|mercury|mars)/.test(h)) kinds.add("astro");
  if (/(tradingview|pine|indicator|script)/.test(h)) kinds.add("tradingview");
  if (/(stock|equity|ibkr|nasdaq|nyse)/.test(h)) kinds.add("ibkr");
  if (/(polymarket|prediction|market odds|election)/.test(h)) kinds.add("polymarket");
  return Array.from(kinds);
};

const runStep = async (
  scopeId: string,
  agentKey: string,
  agentLabel: string,
  inputJson: unknown,
  fn: () => Promise<ResearchStepOutput>
) => {
  const stepId = await createAgentStep({
    scopeType: "research_experiment",
    scopeId,
    agentKey,
    agentLabel,
    inputJson
  });

  try {
    const result = await fn();
    await finishAgentStep({
      id: stepId,
      status: "success",
      outputText: result.outputText,
      outputJson: result.outputJson
    });
    return result.outputJson;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await finishAgentStep({
      id: stepId,
      status: "failure",
      outputText: null,
      outputJson: null,
      error: message
    });
    throw error;
  }
};

export const runResearchExperiment = async (experimentId: string) => {
  const experiment = await getResearchExperiment(experimentId);
  if (!experiment) throw new Error("Research experiment not found");

  await updateResearchExperiment({ id: experimentId, status: "running" });

  try {
    const planner = await runStep(
      experimentId,
      "planner",
      "Planner",
      { hypothesis: experiment.hypothesis },
      async () => {
        const symbols = extractSymbols(experiment.hypothesis);
        const dataKinds = inferDataKinds(experiment.hypothesis);
        const plan = {
          title: experiment.title,
          hypothesis: experiment.hypothesis,
          universe: symbols.length > 0 ? symbols : ["BTC", "ETH"],
          dataKinds,
          validationMethod: "paper-first walk-forward or out-of-sample required before live eligibility",
          primaryMetric: "risk-adjusted net return after fees/slippage",
          rejectionCriteria: [
            "data leakage",
            "tiny sample",
            "untracked multiple testing",
            "unstable signal across regimes",
            "result disappears after costs"
          ],
          liveEligible: false
        };
        return {
          outputText: `Planned paper-only experiment for ${plan.universe.join(", ")} using ${dataKinds.join(", ")} data.`,
          outputJson: plan
        };
      }
    );

    const dataScout = await runStep(
      experimentId,
      "data_scout",
      "Data Scout",
      { requestedKinds: planner.dataKinds },
      async () => {
        const sources = await listResearchDataSources();
        const requested = new Set((planner.dataKinds as string[]) ?? []);
        const selected = sources.filter((source) => requested.has(source.kind));
        const missing = Array.from(requested).filter((kind) => !selected.some((source) => source.kind === kind));
        return {
          outputText: selected.length > 0
            ? `Selected ${selected.length} configured source(s); missing ${missing.length}.`
            : "No configured source matched the requested kinds yet.",
          outputJson: {
            selectedSources: selected.map((source) => ({
              id: source.id,
              name: source.name,
              kind: source.kind,
              enabled: source.enabled,
              healthStatus: source.healthStatus
            })),
            missingKinds: missing,
            sourcePolicy: "sources are read/paper-only in Research v1"
          }
        };
      }
    );

    const featureBuilder = await runStep(
      experimentId,
      "feature_builder",
      "Feature Builder",
      { hypothesis: experiment.hypothesis, dataScout },
      async () => {
        const dataKinds = (planner.dataKinds as string[]) ?? [];
        const features = [
          dataKinds.includes("market") && "lagged returns, volatility, volume regime",
          dataKinds.includes("news") && "fresh headline count and sentiment bucket",
          dataKinds.includes("web") && "retrieved-source freshness and claim count",
          dataKinds.includes("weather") && "weather anomaly z-score by market-relevant region",
          dataKinds.includes("astro") && "calendar/astro phase bucket with strict multiple-testing penalty",
          dataKinds.includes("tradingview") && "indicator signal state from imported Pine/script logic",
          dataKinds.includes("ibkr") && "equity returns, volume, earnings/calendar flags",
          dataKinds.includes("polymarket") && "odds change, liquidity, spread, event resolution horizon"
        ].filter(Boolean);
        return {
          outputText: `Drafted ${features.length} feature family/families. No live eligibility without backtest evidence.`,
          outputJson: {
            features,
            executionAssumptions: {
              feesIncluded: true,
              slippageIncluded: true,
              latencySensitive: false,
              liveEligible: false
            }
          }
        };
      }
    );

    const skeptic = await runStep(
      experimentId,
      "skeptic",
      "Skeptic / Anti-Noise Review",
      { planner, dataScout, featureBuilder },
      async () => {
        const riskFlags = [
          "No backtest has run yet, so this is not live eligible.",
          "Multiple-testing risk must be tracked, especially for exotic data.",
          "Out-of-sample or walk-forward evidence is required before promotion.",
          "Costs and slippage must be included before comparing candidates."
        ];
        const verdict = experiment.hypothesis.trim().length < 20 ? "reject_too_vague" : "paper_only";
        return {
          outputText: verdict === "paper_only"
            ? "Approved only for paper exploration. Live trading remains blocked."
            : "Rejected: hypothesis is too vague to test safely.",
          outputJson: {
            verdict,
            liveEligible: false,
            riskFlags
          }
        };
      }
    );

    const shouldCreateCandidate = skeptic.verdict === "paper_only";
    const candidate = shouldCreateCandidate
      ? await createResearchCandidate({
          experimentId,
          name: `${experiment.title} paper candidate`,
          thesis: experiment.hypothesis,
          metrics: {
            evidenceLevel: "hypothesis_only",
            backtestStatus: "not_run",
            liveEligible: false
          },
          riskNotes: "Auto-created by Research v1. Requires backtest and skeptic pass before live approval."
        })
      : null;

    const summary = await runStep(
      experimentId,
      "summarizer",
      "Summary",
      { planner, dataScout, featureBuilder, skeptic, candidateId: candidate?.id ?? null },
      async () => ({
        outputText: candidate
          ? `Created paper candidate ${candidate.name}. Next step: run a real backtest/paper job.`
          : "Experiment rejected before candidate creation.",
        outputJson: {
          candidate,
          nextActions: candidate
            ? ["run_backtest", "collect_more_data", "keep_live_blocked"]
            : ["rewrite_hypothesis"],
          liveEligible: false
        }
      })
    );

    const updated = await updateResearchExperiment({
      id: experimentId,
      status: candidate ? "paper_candidate" : "rejected",
      promotionStatus: candidate ? "paper_auto" : "none",
      planJson: planner,
      resultJson: summary,
      skepticVerdict: String(skeptic.verdict ?? "unknown")
    });

    return { experiment: updated, candidate, summary };
  } catch (error) {
    await updateResearchExperiment({
      id: experimentId,
      status: "rejected",
      resultJson: { error: error instanceof Error ? error.message : String(error) },
      skepticVerdict: "failed"
    });
    throw error;
  }
};

export const LIGHT_AGENT_LABELS: Array<{
  key: string;
  label: string;
  scopeType: AgentStep["scopeType"];
}> = [
  { key: "research", label: "Research", scopeType: "light_run" },
  { key: "trader", label: "Trader", scopeType: "light_run" },
  { key: "validator", label: "Validator", scopeType: "light_run" },
  { key: "execution", label: "Execution", scopeType: "light_run" }
];
