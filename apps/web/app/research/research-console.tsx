"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import type {
  AgentStep,
  Dataset,
  EvaluationJob,
  ExperimentSpec,
  ResearchCandidate,
  ResearchDataSource,
  ResearchExperiment,
  ResearchMemory,
  ResearchSession
} from "@cosmu/shared";
import { AgentTimeline } from "../agent-timeline";
import { LocalTime } from "../local-time";

type Props = {
  initialCommand?: string;
  initialExperiments: ResearchExperiment[];
  initialDataSources: ResearchDataSource[];
  initialCandidates: ResearchCandidate[];
  initialDatasets: Dataset[];
  initialSessions: ResearchSession[];
  initialMemories: ResearchMemory[];
};

type CandidateAction = "paper-bot" | "promote";

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
  initialExperiments,
  initialDataSources,
  initialCandidates,
  initialDatasets,
  initialSessions,
  initialMemories
}: Props) {
  const router = useRouter();
  const [hypothesis, setHypothesis] = useState(initialCommand);
  const [objective, setObjective] = useState(initialCommand);
  const [engine, setEngine] = useState<ResearchSession["engine"]>("native");
  const [autonomyMode, setAutonomyMode] = useState<ResearchSession["autonomyMode"]>("assisted");
  const [datasetName, setDatasetName] = useState("");
  const [datasetSourceKind, setDatasetSourceKind] = useState<Dataset["sourceKind"]>("manual");
  const [datasetRowsJson, setDatasetRowsJson] = useState("");

  const [experiments, setExperiments] = useState(initialExperiments);
  const [candidates, setCandidates] = useState(initialCandidates);
  const [datasets, setDatasets] = useState(initialDatasets);
  const [sessions, setSessions] = useState(initialSessions);
  const [memories] = useState(initialMemories);

  const [selectedSessionId, setSelectedSessionId] = useState(initialSessions[0]?.id ?? null);
  const [selectedExperimentId, setSelectedExperimentId] = useState(initialExperiments[0]?.id ?? null);
  const [selectedSteps, setSelectedSteps] = useState<AgentStep[] | null>(null);

  const [sessionDetails, setSessionDetails] = useState<Record<string, {
    specs: ExperimentSpec[];
    evaluations: EvaluationJob[];
    steps: AgentStep[];
    loading: boolean;
    error?: string;
  }>>({});

  const [submitting, setSubmitting] = useState(false);
  const [sessionSubmitting, setSessionSubmitting] = useState(false);
  const [datasetSubmitting, setDatasetSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingCandidate, setPendingCandidate] = useState<{ id: string; action: CandidateAction } | null>(null);
  const [actionFeedback, setActionFeedback] = useState<{ id: string; tone: "success" | "error"; message: string } | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [, startTransition] = useTransition();

  useEffect(() => {
    if (!initialCommand) return;
    setHypothesis(initialCommand);
    setObjective(initialCommand);
  }, [initialCommand]);

  const selectedExperiment = useMemo(
    () => experiments.find((experiment) => experiment.id === selectedExperimentId) ?? null,
    [experiments, selectedExperimentId]
  );
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

  const submitLegacyExperiment = async (event: FormEvent) => {
    event.preventDefault();
    const text = hypothesis.trim();
    if (!text) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch("/api/research/experiments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hypothesis: text, run: true })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Research request failed");
      if (data.experiment) {
        setExperiments((current) => [data.experiment, ...current.filter((item) => item.id !== data.experiment.id)]);
        setSelectedExperimentId(data.experiment.id);
      }
      if (data.candidate) {
        setCandidates((current) => [data.candidate, ...current]);
      }
      setSelectedSteps(Array.isArray(data.steps) ? data.steps : null);
      setHypothesis("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Research request failed");
    } finally {
      setSubmitting(false);
    }
  };

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
          datasetVersionIds: []
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
      setDatasetName("");
      setDatasetRowsJson("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Dataset creation failed");
    } finally {
      setDatasetSubmitting(false);
    }
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
            Keep this quiet: bounded sessions, visible steps, simulated evaluations. Hot qualitative data now belongs
            in Signals; Research is for slower strategy design.
          </p>
          <div className="inline-actions" style={{ marginTop: "14px" }}>
            <button className="btn btn-secondary" type="button" onClick={() => router.push("/signals")}>
              Open Signals
            </button>
            <button className="btn btn-secondary" type="button" onClick={() => setShowAdvanced((value) => !value)}>
              {showAdvanced ? "Hide advanced lab" : "Show advanced lab"}
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
          </div>
          <div className="command-panel-footer">
            <span className="field-help">Start a bounded session with visible steps, specs, and evaluations.</span>
            <button className="btn btn-primary" type="submit" disabled={sessionSubmitting || objective.trim().length < 5}>
              {sessionSubmitting ? "Starting..." : "Start session"}
            </button>
          </div>
        </form>
        {showAdvanced && (
          <form className="research-command" onSubmit={submitLegacyExperiment}>
            <textarea
              value={hypothesis}
              onChange={(event) => setHypothesis(event.target.value)}
              placeholder="Legacy /research/experiments flow (compatibility)"
              rows={3}
            />
            <div className="command-panel-footer">
              <button className="btn btn-secondary" type="submit" disabled={submitting || hypothesis.trim().length < 5}>
                {submitting ? "Running..." : "Run legacy experiment"}
              </button>
            </div>
            {error && <p className="feedback feedback-error">{error}</p>}
          </form>
        )}
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

        {showAdvanced && (
          <article className="panel">
            <div className="section-header">
              <h3>Legacy experiments</h3>
              <span className="muted">{experiments.length}</span>
            </div>
            <div className="dense-list">
              {experiments.length === 0 && <p className="muted">No legacy experiments yet.</p>}
              {experiments.map((experiment) => (
                <button
                  key={experiment.id}
                  className={`dense-row ${selectedExperimentId === experiment.id ? "dense-row-active" : ""}`}
                  type="button"
                  onClick={() => {
                    setSelectedExperimentId(experiment.id);
                    setSelectedSteps(null);
                  }}
                >
                  <span>
                    <strong>{experiment.title}</strong>
                    <span className="muted">
                      <LocalTime value={experiment.createdAt} />
                      {experiment.skepticVerdict ? ` · skeptic: ${experiment.skepticVerdict}` : ""}
                    </span>
                  </span>
                  <span className={`badge ${statusBadge(experiment.status)}`}>{experiment.status}</span>
                </button>
              ))}
            </div>
          </article>
        )}
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
                    <div key={spec.id} className="dense-row">
                      <span>
                        <strong>v{spec.versionNumber}</strong>
                        <span className="muted">{spec.hypothesis}</span>
                      </span>
                      <span className={`badge ${statusBadge(spec.status)}`}>{spec.status}</span>
                    </div>
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

      {showAdvanced && selectedExperiment && (
        <section className="panel">
          <div className="section-header">
            <div>
              <h3 style={{ marginBottom: "4px" }}>{selectedExperiment.title}</h3>
              <p className="muted">{selectedExperiment.hypothesis}</p>
            </div>
            <span className={`badge ${statusBadge(selectedExperiment.status)}`}>{selectedExperiment.status}</span>
          </div>
          <AgentTimeline
            scopeType="research_experiment"
            scopeId={selectedExperiment.id}
            title="Legacy experiment timeline"
            initialSteps={selectedSteps ?? undefined}
          />
        </section>
      )}

      {showAdvanced && (
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
          </div>
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
          {datasets.map((dataset) => (
            <div key={dataset.id} className="data-source-tile">
              <div>
                <strong>{dataset.name}</strong>
                <span className="muted">{dataset.sourceKind}</span>
              </div>
              <span className={`badge ${dataset.active ? "badge-success" : "badge-inactive"}`}>
                {dataset.active ? "active" : "off"}
              </span>
            </div>
          ))}
        </div>
      </section>
      )}

      {showAdvanced && (
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

      {showAdvanced && (
      <section className="panel">
        <div className="section-header">
          <h3>Research memory</h3>
          <span className="muted">{memories.length}</span>
        </div>
        <div className="dense-list">
          {memories.length === 0 && <p className="muted">No memories yet.</p>}
          {memories.map((memory) => (
            <div key={memory.id} className="dense-row">
              <span>
                <strong>{memory.title}</strong>
                <span className="muted">{memory.scopeType}:{memory.scopeKey} · confidence {memory.confidence.toFixed(2)}</span>
              </span>
              <span className={`badge ${memory.active ? "badge-success" : "badge-neutral"}`}>
                {memory.active ? "active" : "inactive"}
              </span>
            </div>
          ))}
        </div>
      </section>
      )}

      {showAdvanced && (
      <section className="panel">
        <div className="section-header">
          <h3>Data source registry</h3>
          <span className="muted">Connector status</span>
        </div>
        <div className="data-source-grid">
          {initialDataSources.map((source) => (
            <div key={source.id} className="data-source-tile">
              <div>
                <strong>{source.name}</strong>
                <span className="muted">{source.kind}</span>
              </div>
              <span className={`badge ${source.enabled ? "badge-success" : "badge-inactive"}`}>
                {source.enabled ? "enabled" : "off"}
              </span>
            </div>
          ))}
        </div>
      </section>
      )}
    </div>
  );
}
