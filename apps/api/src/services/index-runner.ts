// module: Index scheduler — runs due index configs into snapshots.
// Same "one runtime, many agents" skeleton as the bot scheduler: claim → work → finish,
// but the output is a numeric/qualitative index snapshot rather than a trade.
import {
  getDueIndexConfigs,
  claimIndexRun,
  finishIndexRun,
  setIndexStatus,
  createIndexSnapshot,
  getLatestModelProfile,
  listStandardizedSignals,
  listRawObservations
} from "../lib/store.js";
import { getProvider } from "../providers/registry.js";
import type { LLMMessage } from "../providers/llm.js";
import type { IndexConfig } from "@cosmu/shared";

export type IndexSchedulerTrigger = "startup" | "interval" | "manual";

export const INDEX_SCHEDULER_INTERVAL_MS = 60 * 1000;

let indexTickRunning = false;
let indexLastTickAt: string | null = null;
let indexLastFinishedAt: string | null = null;
let indexLastError: string | null = null;
let indexLastDueCount = 0;
let indexLastResultCount = 0;

export const getIndexSchedulerStatus = () => ({
  enabled: true,
  intervalMs: INDEX_SCHEDULER_INTERVAL_MS,
  tickRunning: indexTickRunning,
  lastTickAt: indexLastTickAt,
  lastFinishedAt: indexLastFinishedAt,
  lastDueCount: indexLastDueCount,
  lastResultCount: indexLastResultCount,
  lastError: indexLastError
});

const extractJson = (text: string): string => {
  const trimmed = text.trim();
  const fenced = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fenced) return fenced[1].trim();
  const braceStart = trimmed.indexOf("{");
  if (braceStart >= 0) return trimmed.slice(braceStart);
  return trimmed;
};

type IndexSnapshotDraft = {
  value: number | null;
  label: string | null;
  summary: string;
  evidence: unknown;
};

const parseSnapshot = (rawText: string): IndexSnapshotDraft => {
  const parsed = JSON.parse(extractJson(rawText)) as Record<string, unknown>;
  const rawValue = parsed.value;
  const value =
    typeof rawValue === "number" && Number.isFinite(rawValue)
      ? rawValue
      : typeof rawValue === "string" && rawValue.trim() !== "" && Number.isFinite(Number(rawValue))
        ? Number(rawValue)
        : null;
  const summary =
    typeof parsed.summary === "string" && parsed.summary.trim().length > 0
      ? parsed.summary.trim()
      : "No summary produced.";
  return {
    value,
    label: typeof parsed.label === "string" ? parsed.label : null,
    summary,
    evidence: Array.isArray(parsed.evidence) ? parsed.evidence : []
  };
};

const buildContextBlock = async (config: IndexConfig) => {
  const [signals, observations] = await Promise.all([
    listStandardizedSignals({ limit: 40 }),
    listRawObservations(40)
  ]);

  const keyHints = config.sourceKeys.map((k) => k.toLowerCase());
  const relevant = observations.filter((o) =>
    keyHints.length === 0
      ? true
      : keyHints.some(
          (k) =>
            o.sourceName.toLowerCase().includes(k) || o.sourceKind.toLowerCase().includes(k)
        )
  );
  const observationPool = relevant.length > 0 ? relevant : observations;

  return {
    text: JSON.stringify(
      {
        sourceKeys: config.sourceKeys,
        recentSignals: signals.map((s) => ({
          asset: s.asset,
          topic: s.topic,
          direction: s.direction,
          sentimentScore: s.sentimentScore,
          summary: s.summary
        })),
        recentObservations: observationPool.slice(0, 25).map((o) => ({
          source: o.sourceName,
          observedAt: o.observedAt,
          title: o.title,
          content: o.content.slice(0, 600)
        }))
      },
      null,
      2
    ),
    counts: { signals: signals.length, observations: observationPool.length }
  };
};

const runIndexConfig = async (config: IndexConfig) => {
  const runId = await claimIndexRun(config.id);
  if (!runId) {
    return { indexId: config.id, slug: config.slug, skipped: true, reason: "already_running" };
  }

  const start = Date.now();
  try {
    const profile = await getLatestModelProfile();
    if (!profile) {
      throw new Error("No model profile configured to run index agents");
    }

    const { text: contextText, counts } = await buildContextBlock(config);
    const provider = getProvider(profile.provider);

    const systemPrompt = [
      config.promptBody.trim(),
      "",
      "Return ONLY a JSON object with these fields:",
      '{ "value": number|null, "label": string|null, "summary": string, "evidence": array }',
      "value is the headline number for this index (null if not numeric). summary is a concise human-readable readout.",
      "evidence is an array of short strings citing the observations/signals you used."
    ].join("\n");

    const messages: LLMMessage[] = [
      { role: "system", content: systemPrompt },
      { role: "user", content: `Data available to you:\n\n${contextText}` }
    ];

    const response = await provider.chat({ model: profile.model, messages });
    const snapshot = parseSnapshot(response.content);

    await createIndexSnapshot({
      indexId: config.id,
      runId,
      value: snapshot.value,
      label: snapshot.label,
      summary: snapshot.summary,
      evidence: snapshot.evidence
    });

    await finishIndexRun(runId, {
      status: "success",
      sourceCounts: counts,
      cost: {
        provider: provider.name,
        model: response.model,
        inputTokens: response.usage?.inputTokens ?? null,
        outputTokens: response.usage?.outputTokens ?? null,
        latencyMs: Date.now() - start
      }
    });

    return { indexId: config.id, slug: config.slug, skipped: false, value: snapshot.value };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await finishIndexRun(runId, { status: "failure", error: message });
    await setIndexStatus(config.id, "error");
    return { indexId: config.id, slug: config.slug, skipped: false, error: message };
  }
};

export const runIndexSchedulerTick = async (trigger: IndexSchedulerTrigger) => {
  if (indexTickRunning) {
    return {
      checkedAt: new Date().toISOString(),
      trigger,
      skipped: true,
      reason: "index_tick_already_running",
      results: []
    };
  }

  indexTickRunning = true;
  indexLastTickAt = new Date().toISOString();

  try {
    const dueConfigs = await getDueIndexConfigs();
    const results: Array<Record<string, unknown>> = [];

    if (dueConfigs.length > 0) {
      console.log(`[index-scheduler] ${trigger} tick found ${dueConfigs.length} due index(es)`);
    }

    for (const config of dueConfigs) {
      try {
        results.push(await runIndexConfig(config));
      } catch (error) {
        results.push({
          indexId: config.id,
          slug: config.slug,
          error: error instanceof Error ? error.message : String(error)
        });
      }
    }

    indexLastError = null;
    indexLastDueCount = dueConfigs.length;
    indexLastResultCount = results.length;
    indexLastFinishedAt = new Date().toISOString();

    return {
      checkedAt: indexLastFinishedAt,
      trigger,
      skipped: false,
      dueCount: dueConfigs.length,
      results
    };
  } catch (error) {
    indexLastError = error instanceof Error ? error.message : String(error);
    indexLastFinishedAt = new Date().toISOString();
    console.warn("[index-scheduler] tick failed:", indexLastError);
    throw error;
  } finally {
    indexTickRunning = false;
  }
};
