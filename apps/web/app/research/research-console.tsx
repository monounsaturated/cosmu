"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import type {
  AgentStep,
  Dataset,
  DatasetVersion,
  EvaluationJob,
  ExperimentSpec,
  ResearchCandidate,
  ResearchDataSource,
  ResearchSession
} from "@cosmu/shared";
import { AgentTimeline } from "../agent-timeline";
import { LocalTime } from "../local-time";

type Props = {
  initialCommand?: string;
  initialDataSources: ResearchDataSource[];
  initialCandidates: ResearchCandidate[];
  initialDatasets: Dataset[];
  initialSessions: ResearchSession[];
};

type CandidateAction = "paper-bot" | "promote";

type ModelProfile = {
  id: string;
  name: string;
  provider: string;
  model: string;
};

const DATA_SOURCE_KINDS: ResearchDataSource["kind"][] = [
  "market",
  "news",
  "web",
  "social",
  "weather",
  "astro",
  "tradingview",
  "csv",
  "custom_api",
  "ibkr",
  "polymarket"
];

const RESEARCH_TOOL_OPTIONS = [
  { id: "web_search", label: "Web search" },
  { id: "x_search", label: "X search" },
  { id: "market_data", label: "Market data" },
  { id: "paper_backtest", label: "Paper backtest" }
];

const statusBadge = (status: string) => {
  if (status.includes("candidate") || status.includes("ready") || status.includes("success")) return "badge-success";
  if (status.includes("rejected") || status.includes("failure")) return "badge-failure";
  if (status.includes("running") || status.includes("queued")) return "badge-running";
  return "badge-neutral";
};

const formatMetricValue = (value: unknown): string => {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isFinite(value) ? value.toFixed(2) : "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
};

const HIDDEN_METRIC_KEYS = new Set(["paperBotId"]);

const candidateMetrics = (candidate: ResearchCandidate): Array<[string, string]> => {
  if (!candidate.metrics || typeof candidate.metrics !== "object") return [];
  return Object.entries(candidate.metrics as Record<string, unknown>)
    .filter(([key]) => !HIDDEN_METRIC_KEYS.has(key))
    .map(([key, value]) => [key, formatMetricValue(value)]);
};

export function ResearchConsole({
  initialCommand = "",
  initialDataSources,
  initialCandidates,
  initialDatasets,
  initialSessions
}: Props) {
  const router = useRouter();
  const [objective, setObjective] = useState(initialCommand);
  const [engine, setEngine] = useState<ResearchSession["engine"]>("native");
  const [autonomyMode, setAutonomyMode] = useState<ResearchSession["autonomyMode"]>("assisted");
  const [modelProfileId, setModelProfileId] = useState("");
  const [maxIterations, setMaxIterations] = useState(3);
  const [maxRuntimeMinutes, setMaxRuntimeMinutes] = useState(30);
  const [maxCostUsd, setMaxCostUsd] = useState(10);
  const [allowedTools, setAllowedTools] = useState<string[]>(["web_search", "x_search", "market_data"]);
  const [datasetName, setDatasetName] = useState("");
  const [datasetSourceKind, setDatasetSourceKind] = useState<Dataset["sourceKind"]>("manual");
  const [datasetDescription, setDatasetDescription] = useState("");
  const [datasetTags, setDatasetTags] = useState("");
  const [datasetRowsJson, setDatasetRowsJson] = useState("");
  const [sourceName, setSourceName] = useState("");
  const [sourceKind, setSourceKind] = useState<ResearchDataSource["kind"]>("market");
  const [sourceEnabled, setSourceEnabled] = useState(true);
  const [sourceConfigJson, setSourceConfigJson] = useState("{}");

  const [dataSources, setDataSources] = useState(initialDataSources);
  const [candidates, setCandidates] = useState(initialCandidates);
  const [datasets, setDatasets] = useState(initialDatasets);
  const [sessions, setSessions] = useState(initialSessions);
  const [models, setModels] = useState<ModelProfile[]>([]);
  const [datasetVersionsByDataset, setDatasetVersionsByDataset] = useState<Record<string, DatasetVersion[]>>({});
  const [selectedDatasetVersionIds, setSelectedDatasetVersionIds] = useState<string[]>([]);
  const [loadingDatasetVersions, setLoadingDatasetVersions] = useState<Record<string, boolean>>({});
  const [specDrafts, setSpecDrafts] = useState<Record<string, string>>({});
  const [specStatuses, setSpecStatuses] = useState<Record<string, ExperimentSpec["status"]>>({});
  const [sourceDrafts, setSourceDrafts] = useState<Record<string, string>>({});

  const [selectedSessionId, setSelectedSessionId] = useState(initialSessions[0]?.id ?? null);

  const [sessionDetails, setSessionDetails] = useState<Record<string, {
    specs: ExperimentSpec[];
    evaluations: EvaluationJob[];
    steps: AgentStep[];
    loading: boolean;
    error?: string;
  }>>({});

  const [sessionSubmitting, setSessionSubmitting] = useState(false);
  const [datasetSubmitting, setDatasetSubmitting] = useState(false);
  const [sourceSubmitting, setSourceSubmitting] = useState(false);
  const [savingSpecId, setSavingSpecId] = useState<string | null>(null);
  const [savingSourceId, setSavingSourceId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingCandidate, setPendingCandidate] = useState<{ id: string; action: CandidateAction } | null>(null);
  const [actionFeedback, setActionFeedback] = useState<{ id: string; tone: "success" | "error"; message: string } | null>(null);
  const [, startTransition] = useTransition();

  useEffect(() => {
    if (!initialCommand) return;
    setObjective(initialCommand);
  }, [initialCommand]);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/models", { cache: "no-store" })
      .then(async (res) => res.ok ? await res.json() as ModelProfile[] : [])
      .then((items) => {
        if (cancelled) return;
        setModels(items);
        setModelProfileId((current) => current || items[0]?.id || "");
      })
      .catch(() => {
        if (!cancelled) setModels([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const loadDatasetVersions = async (datasetId: string) => {
    if (datasetVersionsByDataset[datasetId] || loadingDatasetVersions[datasetId]) return;
    setLoadingDatasetVersions((current) => ({ ...current, [datasetId]: true }));
    try {
      const res = await fetch(`/api/research/datasets/${datasetId}/versions`, { cache: "no-store" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Failed to load dataset versions");
      setDatasetVersionsByDataset((current) => ({
        ...current,
        [datasetId]: Array.isArray(data.versions) ? data.versions : []
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dataset versions");
    } finally {
      setLoadingDatasetVersions((current) => ({ ...current, [datasetId]: false }));
    }
  };

  const toggleDatasetVersion = (versionId: string) => {
    setSelectedDatasetVersionIds((current) =>
      current.includes(versionId) ? current.filter((id) => id !== versionId) : [...current, versionId]
    );
  };

  const toggleTool = (toolId: string) => {
    setAllowedTools((current) =>
      current.includes(toolId) ? current.filter((id) => id !== toolId) : [...current, toolId]
    );
  };

  const selectedSession = useMemo(
    () => sessions.find((session) => session.id === selectedSessionId) ?? null,
    [sessions, selectedSessionId]
  );
  const selectedSessionDetail = selectedSessionId ? sessionDetails[selectedSessionId] : undefined;

  useEffect(() => {
    const sessionId = selectedSessionId;
    if (!sessionId || sessionDetails[sessionId]) return;
    setSessionDetails((current) => ({ ...current, [sessionId]: { specs: [], evaluations: [], steps: [], loading: true } }));
    fetch(`/api/research/sessions/${sessionId}`, { cache: "no-store" })
      .then(async (res) => {
        const data = await res.json();
        if (!res.ok) throw new Error(data.error ?? "Failed to load session");
        setSessionDetails((current) => ({
          ...current,
          [sessionId]: {
            specs: Array.isArray(data.specs) ? data.specs : [],
            evaluations: Array.isArray(data.evaluations) ? data.evaluations : [],
            steps: Array.isArray(data.steps) ? data.steps : [],
            loading: false
          }
        }));
      })
      .catch((err) => {
        setSessionDetails((current) => ({
          ...current,
          [sessionId]: {
            specs: [],
            evaluations: [],
            steps: [],
            loading: false,
            error: err instanceof Error ? err.message : "Failed to load session"
          }
        }));
      });
  }, [selectedSessionId, sessionDetails]);

  const submitSession = async (event: FormEvent) => {
    event.preventDefault();
    const objectiveText = objective.trim();
    if (objectiveText.length < 5) return;
    setSessionSubmitting(true);
    setError(null);
    try {
      const res = await fetch("/api/research/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: objectiveText,
          objective: objectiveText,
          hypothesis: objectiveText,
          engine,
          autonomyMode,
          datasetVersionIds: selectedDatasetVersionIds,
          allowedTools,
          modelProfileId: modelProfileId || null,
          maxIterations,
          maxRuntimeMinutes,
          maxCostUsd
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Session creation failed");
      if (data.session) {
        setSessions((current) => [data.session, ...current.filter((item) => item.id !== data.session.id)]);
        setSelectedSessionId(data.session.id);
      }
      setObjective("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Session creation failed");
    } finally {
      setSessionSubmitting(false);
    }
  };

  const submitDataset = async (event: FormEvent) => {
    event.preventDefault();
    const name = datasetName.trim();
    if (name.length < 2) return;
    setDatasetSubmitting(true);
    setError(null);
    try {
      const parsedRows = datasetRowsJson.trim().length > 0 ? JSON.parse(datasetRowsJson) : null;
      const res = await fetch("/api/research/datasets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          sourceKind: datasetSourceKind,
          description: datasetDescription.trim() || null,
          tags: datasetTags.split(",").map((tag) => tag.trim()).filter(Boolean),
          version: parsedRows
            ? {
                schemaJson: { columns: ["ts", "close"] },
                metadataJson: { uploadedFromUi: true },
                rowCount: Array.isArray(parsedRows) ? parsedRows.length : null,
                contentJson: parsedRows
              }
            : undefined
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Dataset creation failed");
      if (data.dataset) {
        setDatasets((current) => [data.dataset, ...current.filter((item) => item.id !== data.dataset.id)]);
      }
      if (data.dataset && data.version) {
        setDatasetVersionsByDataset((current) => ({
          ...current,
          [data.dataset.id]: [data.version, ...(current[data.dataset.id] ?? [])]
        }));
        setSelectedDatasetVersionIds((current) => [data.version.id, ...current.filter((id) => id !== data.version.id)]);
      }
      setDatasetName("");
      setDatasetDescription("");
      setDatasetTags("");
      setDatasetRowsJson("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Dataset creation failed");
    } finally {
      setDatasetSubmitting(false);
    }
  };

  const submitDataSource = async (event: FormEvent) => {
    event.preventDefault();
    const name = sourceName.trim();
    if (!name) return;
    setSourceSubmitting(true);
    setError(null);
    try {
      const config = sourceConfigJson.trim() ? JSON.parse(sourceConfigJson) : {};
      const res = await fetch("/api/research/data-sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, kind: sourceKind, enabled: sourceEnabled, config })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Data source creation failed");
      if (data.dataSource) {
        setDataSources((current) => [data.dataSource, ...current.filter((source) => source.id !== data.dataSource.id)]);
      }
      setSourceName("");
      setSourceConfigJson("{}");
      setSourceEnabled(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Data source creation failed");
    } finally {
      setSourceSubmitting(false);
    }
  };

  const updateDataSource = async (source: ResearchDataSource, patch: Partial<Pick<ResearchDataSource, "name" | "kind" | "enabled">> & { config?: unknown }) => {
    setSavingSourceId(source.id);
    setError(null);
    try {
      const res = await fetch(`/api/research/data-sources/${source.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch)
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Data source update failed");
      if (data.dataSource) {
        setDataSources((current) => current.map((item) => item.id === source.id ? data.dataSource : item));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Data source update failed");
    } finally {
      setSavingSourceId(null);
    }
  };

  const saveDataSourceConfig = async (source: ResearchDataSource) => {
    const draft = sourceDrafts[source.id] ?? JSON.stringify(source.config ?? {}, null, 2);
    await updateDataSource(source, { config: draft.trim() ? JSON.parse(draft) : {} });
  };

  const runEvaluation = async () => {
    if (!selectedSession || !selectedSessionDetail || selectedSessionDetail.specs.length === 0) return;
    const latestSpec = selectedSessionDetail.specs[0];
    try {
      const res = await fetch("/api/research/evaluations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: selectedSession.id,
          specId: latestSpec.id,
          datasetVersionIds: selectedSession.datasetVersionIds,
          kind: "paper_backtest",
          runNow: true
        })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Evaluation failed");
      const job = data.job as EvaluationJob;
      setSessionDetails((current) => ({
        ...current,
        [selectedSession.id]: {
          ...(current[selectedSession.id] ?? { specs: [], evaluations: [], steps: [], loading: false }),
          evaluations: [job, ...(current[selectedSession.id]?.evaluations ?? [])]
        }
      }));
      startTransition(() => router.refresh());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Evaluation failed");
    }
  };

  const saveSpec = async (spec: ExperimentSpec) => {
    setSavingSpecId(spec.id);
    setError(null);
    try {
      const draft = specDrafts[spec.id] ?? JSON.stringify(spec.specJson, null, 2);
      const status = specStatuses[spec.id] ?? spec.status;
      const res = await fetch(`/api/research/specs/${spec.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ specJson: JSON.parse(draft), status })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Spec update failed");
      if (data.spec) {
        setSessionDetails((current) => {
          const detail = current[data.spec.sessionId];
          if (!detail) return current;
          return {
            ...current,
            [data.spec.sessionId]: {
              ...detail,
              specs: detail.specs.map((item) => item.id === data.spec.id ? data.spec : item)
            }
          };
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Spec update failed");
    } finally {
      setSavingSpecId(null);
    }
  };

  const runCandidateAction = async (candidate: ResearchCandidate, action: CandidateAction) => {
    setPendingCandidate({ id: candidate.id, action });
    setActionFeedback(null);
    try {
      const path = action === "paper-bot" ? "paper-bot" : "promote-to-pro";
      const res = await fetch(`/api/research/candidates/${candidate.id}/${path}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Action failed");

      if (action === "paper-bot") {
        setCandidates((current) =>
          current.map((item) =>
            item.id === candidate.id
              ? {
                  ...item,
                  status: "paper_running",
                  metrics: {
                    ...((item.metrics ?? {}) as Record<string, unknown>),
                    paperBotId: data.botId,
                    paperBotStatus: "created_testnet_disabled"
                  }
                }
              : item
          )
        );
        setActionFeedback({
          id: candidate.id,
          tone: "success",
          message: "Research bot created in workspace."
        });
        startTransition(() => router.refresh());
      } else {
        setCandidates((current) =>
          current.map((item) => (item.id === candidate.id ? { ...item, status: "live_candidate" } : item))
        );
        setActionFeedback({
          id: candidate.id,
          tone: "success",
          message: "Promotion request created. Review it on Cosmu Pro."
        });
      }
    } catch (err) {
      setActionFeedback({
        id: candidate.id,
        tone: "error",
        message: err instanceof Error ? err.message : "Action failed"
      });
    } finally {
      setPendingCandidate(null);
    }
  };

  return (
    <div className="research-layout">
      <section className="command-panel">
        <div>
          <p className="eyebrow">Strategy Lab</p>
          <h1>Research, but bounded.</h1>
          <p className="field-help">
            Start with a clear thesis, choose the model and data it can use, then evaluate the result before it becomes a bot.
          </p>
          <div className="inline-actions" style={{ marginTop: "14px" }}>
            <button className="btn btn-secondary" type="button" onClick={() => router.push("/signals")}>
              Capture signal first
            </button>
          </div>
        </div>
        <form className="research-command" onSubmit={submitSession}>
          <textarea
            value={objective}
            onChange={(event) => setObjective(event.target.value)}
            placeholder="Session objective: find robust BTC volatility regime strategy with walk-forward validation"
            rows={3}
          />
          <div className="form-grid-two">
            <label className="field">
              <span>Engine</span>
              <select value={engine} onChange={(event) => setEngine(event.target.value as ResearchSession["engine"])}>
                <option value="native">native</option>
                <option value="hermes">hermes (sidecar)</option>
                <option value="autoresearch">autoresearch (sidecar)</option>
                <option value="openclaw">openclaw (sidecar)</option>
              </select>
            </label>
            <label className="field">
              <span>Autonomy</span>
              <select
                value={autonomyMode}
                onChange={(event) => setAutonomyMode(event.target.value as ResearchSession["autonomyMode"])}
              >
                <option value="manual">manual</option>
                <option value="assisted">assisted</option>
                <option value="autonomous">autonomous</option>
              </select>
            </label>
            <label className="field">
              <span>Model</span>
              <select value={modelProfileId} onChange={(event) => setModelProfileId(event.target.value)}>
                <option value="">Latest configured model</option>
                {models.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name} · {model.model}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="form-grid-three">
            <label className="field">
              <span>Iterations</span>
              <input
                type="number"
                min={1}
                max={12}
                value={maxIterations}
                onChange={(event) => setMaxIterations(Number(event.target.value))}
              />
            </label>
            <label className="field">
              <span>Runtime minutes</span>
              <input
                type="number"
                min={5}
                max={240}
                value={maxRuntimeMinutes}
                onChange={(event) => setMaxRuntimeMinutes(Number(event.target.value))}
              />
            </label>
            <label className="field">
              <span>Cost cap USD</span>
              <input
                type="number"
                min={0}
                step={1}
                value={maxCostUsd}
                onChange={(event) => setMaxCostUsd(Number(event.target.value))}
              />
            </label>
          </div>
          <div className="selector-panel">
            <span className="field-help">Allowed tools</span>
            <div className="checkbox-row">
              {RESEARCH_TOOL_OPTIONS.map((tool) => (
                <label key={tool.id} className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={allowedTools.includes(tool.id)}
                    onChange={() => toggleTool(tool.id)}
                  />
                  <span>{tool.label}</span>
                </label>
              ))}
            </div>
          </div>
          <details className="selector-panel">
            <summary>
              Datasets
              <span className="muted">{selectedDatasetVersionIds.length} versions selected</span>
            </summary>
            <div className="data-source-grid">
              {datasets.length === 0 && <p className="muted">No datasets yet. Add one below, then attach its version here.</p>}
              {datasets.map((dataset) => {
                const versions = datasetVersionsByDataset[dataset.id] ?? [];
                return (
                  <div key={dataset.id} className="data-source-tile data-source-tile-editable">
                    <div>
                      <strong>{dataset.name}</strong>
                      <span className="muted">{dataset.sourceKind}{dataset.description ? ` · ${dataset.description}` : ""}</span>
                    </div>
                    <button type="button" className="btn btn-xs" onClick={() => loadDatasetVersions(dataset.id)}>
                      {loadingDatasetVersions[dataset.id] ? "Loading..." : versions.length ? "Refresh" : "Load versions"}
                    </button>
                    {versions.length > 0 && (
                      <div className="version-picker">
                        {versions.map((version) => (
                          <label key={version.id} className="checkbox-label">
                            <input
                              type="checkbox"
                              checked={selectedDatasetVersionIds.includes(version.id)}
                              onChange={() => toggleDatasetVersion(version.id)}
                            />
                            <span>v{version.versionNumber} · {version.rowCount ?? "?"} rows</span>
                          </label>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </details>
          <div className="command-panel-footer">
            <span className="field-help">Start a bounded session with visible steps, specs, and evaluations.</span>
            <button className="btn btn-primary" type="submit" disabled={sessionSubmitting || objective.trim().length < 5}>
              {sessionSubmitting ? "Starting..." : "Start session"}
            </button>
          </div>
        </form>
        {error && <p className="feedback feedback-error">{error}</p>}
      </section>

      <section className="ops-grid">
        <article className="panel">
          <div className="section-header">
            <h3>Sessions</h3>
            <span className="muted">{sessions.length}</span>
          </div>
          <div className="dense-list">
            {sessions.length === 0 && <p className="muted">No sessions yet.</p>}
            {sessions.map((session) => (
              <button
                key={session.id}
                className={`dense-row ${selectedSessionId === session.id ? "dense-row-active" : ""}`}
                type="button"
                onClick={() => setSelectedSessionId(session.id)}
              >
                <span>
                  <strong>{session.title}</strong>
                  <span className="muted">
                    {session.engine} · {session.autonomyMode} · <LocalTime value={session.createdAt} />
                  </span>
                </span>
                <span className={`badge ${statusBadge(session.status)}`}>{session.status}</span>
              </button>
            ))}
          </div>
          <div className="inline-actions">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={runEvaluation}
              disabled={!selectedSessionDetail || selectedSessionDetail.specs.length === 0}
            >
              Run evaluation
            </button>
          </div>
        </article>

      </section>

      {selectedSession && (
        <section className="panel">
          <div className="section-header">
            <div>
              <h3 style={{ marginBottom: "4px" }}>Session detail</h3>
              <p className="muted">{selectedSession.objective}</p>
            </div>
            <span className={`badge ${statusBadge(selectedSession.status)}`}>{selectedSession.status}</span>
          </div>
          {selectedSessionDetail?.loading && <p className="muted">Loading session details...</p>}
          {selectedSessionDetail?.error && <p className="feedback feedback-error">{selectedSessionDetail.error}</p>}
          {selectedSessionDetail && !selectedSessionDetail.loading && (
            <div className="ops-grid">
              <article className="panel panel-sub">
                <div className="section-header">
                  <h4>Specs</h4>
                  <span className="muted">{selectedSessionDetail.specs.length}</span>
                </div>
                <div className="dense-list">
                  {selectedSessionDetail.specs.map((spec) => (
                    <details key={spec.id} className="editable-card">
                      <summary>
                        <span>
                          <strong>v{spec.versionNumber}</strong>
                          <span className="muted">{spec.hypothesis}</span>
                        </span>
                        <span className={`badge ${statusBadge(specStatuses[spec.id] ?? spec.status)}`}>
                          {specStatuses[spec.id] ?? spec.status}
                        </span>
                      </summary>
                      <label className="field">
                        <span>Status</span>
                        <select
                          value={specStatuses[spec.id] ?? spec.status}
                          onChange={(event) => setSpecStatuses((current) => ({
                            ...current,
                            [spec.id]: event.target.value as ExperimentSpec["status"]
                          }))}
                        >
                          <option value="draft">draft</option>
                          <option value="locked">locked</option>
                          <option value="superseded">superseded</option>
                        </select>
                      </label>
                      <textarea
                        value={specDrafts[spec.id] ?? JSON.stringify(spec.specJson, null, 2)}
                        onChange={(event) => setSpecDrafts((current) => ({ ...current, [spec.id]: event.target.value }))}
                        rows={8}
                      />
                      <div className="inline-actions">
                        <button
                          type="button"
                          className="btn btn-primary"
                          onClick={() => saveSpec(spec)}
                          disabled={savingSpecId === spec.id}
                        >
                          {savingSpecId === spec.id ? "Saving..." : "Save spec"}
                        </button>
                      </div>
                    </details>
                  ))}
                </div>
              </article>
              <article className="panel panel-sub">
                <div className="section-header">
                  <h4>Evaluations</h4>
                  <span className="muted">{selectedSessionDetail.evaluations.length}</span>
                </div>
                <div className="dense-list">
                  {selectedSessionDetail.evaluations.length === 0 && <p className="muted">No evaluations yet.</p>}
                  {selectedSessionDetail.evaluations.map((job) => (
                    <div key={job.id} className="dense-row">
                      <span>
                        <strong>{job.kind}</strong>
                        <span className="muted">
                          {job.result && typeof job.result.metricsJson === "object"
                            ? `avg: ${String((job.result.metricsJson as Record<string, unknown>).avgReturnPct ?? "—")} · sharpe: ${String((job.result.metricsJson as Record<string, unknown>).sharpe ?? "—")}`
                            : "queued"}
                        </span>
                      </span>
                      <span className={`badge ${statusBadge(job.status)}`}>{job.status}</span>
                    </div>
                  ))}
                </div>
              </article>
            </div>
          )}
          <AgentTimeline
            scopeType="research_experiment"
            scopeId={selectedSession.id}
            title="Session agent debate"
            initialSteps={selectedSessionDetail?.steps}
          />
        </section>
      )}

      <section className="panel">
        <div className="section-header">
          <h3>Datasets</h3>
          <span className="muted">{datasets.length}</span>
        </div>
        <form className="research-command" onSubmit={submitDataset}>
          <div className="form-grid-two">
            <label className="field">
              <span>Name</span>
              <input value={datasetName} onChange={(event) => setDatasetName(event.target.value)} placeholder="BTC 1h OHLCV" />
            </label>
            <label className="field">
              <span>Source</span>
              <select
                value={datasetSourceKind}
                onChange={(event) => setDatasetSourceKind(event.target.value as Dataset["sourceKind"])}
              >
                <option value="manual">manual</option>
                <option value="upload">upload</option>
                <option value="binance_ohlcv">binance_ohlcv</option>
                <option value="external_api">external_api</option>
              </select>
            </label>
            <label className="field">
              <span>Tags</span>
              <input value={datasetTags} onChange={(event) => setDatasetTags(event.target.value)} placeholder="btc, 1h, walk-forward" />
            </label>
          </div>
          <label className="field">
            <span>Description</span>
            <input
              value={datasetDescription}
              onChange={(event) => setDatasetDescription(event.target.value)}
              placeholder="What this dataset is good for and where it came from"
            />
          </label>
          <textarea
            value={datasetRowsJson}
            onChange={(event) => setDatasetRowsJson(event.target.value)}
            placeholder='Optional JSON rows: [{"ts":1711900800000,"close":70000}]'
            rows={3}
          />
          <div className="command-panel-footer">
            <button className="btn btn-secondary" type="submit" disabled={datasetSubmitting || datasetName.trim().length < 2}>
              {datasetSubmitting ? "Saving..." : "Add dataset"}
            </button>
          </div>
        </form>
        <div className="data-source-grid">
          {datasets.map((dataset) => {
            const versions = datasetVersionsByDataset[dataset.id] ?? [];
            return (
              <div key={dataset.id} className="data-source-tile data-source-tile-editable">
                <div>
                  <strong>{dataset.name}</strong>
                  <span className="muted">
                    {dataset.sourceKind}{dataset.tags.length ? ` · ${dataset.tags.join(", ")}` : ""}
                  </span>
                </div>
                <span className={`badge ${dataset.active ? "badge-success" : "badge-inactive"}`}>
                  {dataset.active ? "active" : "off"}
                </span>
                <button type="button" className="btn btn-xs" onClick={() => loadDatasetVersions(dataset.id)}>
                  {loadingDatasetVersions[dataset.id] ? "Loading..." : `${versions.length} versions`}
                </button>
                {versions.length > 0 && (
                  <div className="version-picker">
                    {versions.map((version) => (
                      <label key={version.id} className="checkbox-label">
                        <input
                          type="checkbox"
                          checked={selectedDatasetVersionIds.includes(version.id)}
                          onChange={() => toggleDatasetVersion(version.id)}
                        />
                        <span>Attach v{version.versionNumber} · {version.rowCount ?? "?"} rows</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {candidates.length > 0 && (
      <section className="panel">
        <div className="section-header">
          <h3>Paper candidates</h3>
          <span className="muted">{candidates.length}</span>
        </div>
        <div className="dense-list">
          {candidates.length === 0 && <p className="muted">No paper candidates yet.</p>}
          {candidates.map((candidate) => {
            const metrics = candidateMetrics(candidate);
            const feedback = actionFeedback?.id === candidate.id ? actionFeedback : null;
            const isPaperBotPending = pendingCandidate?.id === candidate.id && pendingCandidate.action === "paper-bot";
            const isPromotePending = pendingCandidate?.id === candidate.id && pendingCandidate.action === "promote";
            const hasPaperBot = Boolean((candidate.metrics as { paperBotId?: string } | null)?.paperBotId);
            const hasProBot = Boolean(candidate.promotedBotId);
            return (
              <div key={candidate.id} className="candidate-card">
                <div className="candidate-card-head">
                  <span>
                    <strong>{candidate.name}</strong>
                    <span className="muted">{candidate.thesis}</span>
                  </span>
                  <span className={`badge ${statusBadge(candidate.status)}`}>{candidate.status}</span>
                </div>
                {metrics.length > 0 && (
                  <dl className="candidate-metrics">
                    {metrics.map(([key, value]) => (
                      <div key={key}>
                        <dt>{key}</dt>
                        <dd>{value}</dd>
                      </div>
                    ))}
                  </dl>
                )}
                {candidate.riskNotes && <p className="muted candidate-risk">{candidate.riskNotes}</p>}
                <div className="candidate-actions">
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => runCandidateAction(candidate, "paper-bot")}
                    disabled={hasPaperBot || isPaperBotPending}
                  >
                    {hasPaperBot ? "Research bot exists" : isPaperBotPending ? "Creating..." : "Create research bot"}
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={() => runCandidateAction(candidate, "promote")}
                    disabled={isPromotePending || hasProBot}
                  >
                    {hasProBot ? "Pro bot exists" : isPromotePending ? "Requesting..." : "Promote to Pro"}
                  </button>
                </div>
                {feedback && (
                  <p className={`feedback ${feedback.tone === "error" ? "feedback-error" : "feedback-success"}`}>
                    {feedback.message}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </section>
      )}

      <section className="panel">
        <div className="section-header">
          <h3>Data sources</h3>
          <span className="muted">What Research can read</span>
        </div>
        <form className="research-command" onSubmit={submitDataSource}>
          <div className="form-grid-two">
            <label className="field">
              <span>Name</span>
              <input value={sourceName} onChange={(event) => setSourceName(event.target.value)} placeholder="X macro watchlist" />
            </label>
            <label className="field">
              <span>Kind</span>
              <select value={sourceKind} onChange={(event) => setSourceKind(event.target.value as ResearchDataSource["kind"])}>
                {DATA_SOURCE_KINDS.map((kind) => <option key={kind} value={kind}>{kind}</option>)}
              </select>
            </label>
          </div>
          <textarea
            value={sourceConfigJson}
            onChange={(event) => setSourceConfigJson(event.target.value)}
            rows={3}
            placeholder='Connector config JSON, e.g. {"symbols":["BTCUSDT"],"cadence":"15m"}'
          />
          <div className="command-panel-footer">
            <label className="checkbox-label">
              <input type="checkbox" checked={sourceEnabled} onChange={(event) => setSourceEnabled(event.target.checked)} />
              <span>Enabled</span>
            </label>
            <button className="btn btn-secondary" type="submit" disabled={sourceSubmitting || !sourceName.trim()}>
              {sourceSubmitting ? "Saving..." : "Add source"}
            </button>
          </div>
        </form>
        <div className="data-source-grid">
          {dataSources.length === 0 && <p className="muted">No sources yet. Add the first source above.</p>}
          {dataSources.map((source) => (
            <details key={source.id} className="data-source-tile data-source-tile-editable">
              <summary>
                <span>
                  <strong>{source.name}</strong>
                  <span className="muted">{source.kind} · health {source.healthStatus}</span>
                </span>
                <span className={`badge ${source.enabled ? "badge-success" : "badge-inactive"}`}>
                  {source.enabled ? "enabled" : "off"}
                </span>
              </summary>
              <div className="form-grid-two">
                <label className="field">
                  <span>Name</span>
                  <input
                    defaultValue={source.name}
                    onBlur={(event) => {
                      const name = event.target.value.trim();
                      if (name && name !== source.name) void updateDataSource(source, { name });
                    }}
                  />
                </label>
                <label className="field">
                  <span>Kind</span>
                  <select
                    value={source.kind}
                    onChange={(event) => void updateDataSource(source, { kind: event.target.value as ResearchDataSource["kind"] })}
                  >
                    {DATA_SOURCE_KINDS.map((kind) => <option key={kind} value={kind}>{kind}</option>)}
                  </select>
                </label>
              </div>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={source.enabled}
                  onChange={(event) => void updateDataSource(source, { enabled: event.target.checked })}
                />
                <span>Enabled</span>
              </label>
              <textarea
                value={sourceDrafts[source.id] ?? JSON.stringify(source.config ?? {}, null, 2)}
                onChange={(event) => setSourceDrafts((current) => ({ ...current, [source.id]: event.target.value }))}
                rows={5}
              />
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => void saveDataSourceConfig(source)}
                disabled={savingSourceId === source.id}
              >
                {savingSourceId === source.id ? "Saving..." : "Save source"}
              </button>
            </details>
          ))}
        </div>
      </section>
    </div>
  );
}
