"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import type {
  AgentStep,
  ResearchCandidate,
  ResearchDataSource,
  ResearchExperiment
} from "@cosmu/shared";
import { AgentTimeline } from "../agent-timeline";
import { LocalTime } from "../local-time";

type Props = {
  initialCommand?: string;
  initialExperiments: ResearchExperiment[];
  initialDataSources: ResearchDataSource[];
  initialCandidates: ResearchCandidate[];
};

type CandidateAction = "paper-bot" | "promote";

const statusBadge = (status: string) => {
  if (status.includes("candidate") || status.includes("ready")) return "badge-success";
  if (status.includes("rejected") || status.includes("failure")) return "badge-failure";
  if (status.includes("running")) return "badge-running";
  return "badge-neutral";
};

const formatMetricValue = (value: unknown): string => {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isFinite(value) ? value.toString() : "—";
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
  initialCandidates
}: Props) {
  const router = useRouter();
  const [hypothesis, setHypothesis] = useState(initialCommand);
  const [experiments, setExperiments] = useState(initialExperiments);
  const [candidates, setCandidates] = useState(initialCandidates);
  const [selectedExperimentId, setSelectedExperimentId] = useState(initialExperiments[0]?.id ?? null);
  const [selectedSteps, setSelectedSteps] = useState<AgentStep[] | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingCandidate, setPendingCandidate] = useState<{ id: string; action: CandidateAction } | null>(null);
  const [actionFeedback, setActionFeedback] = useState<{ id: string; tone: "success" | "error"; message: string } | null>(null);
  const [, startTransition] = useTransition();

  useEffect(() => {
    if (!initialCommand) return;
    setHypothesis(initialCommand);
  }, [initialCommand]);

  const selectedExperiment = useMemo(
    () => experiments.find((experiment) => experiment.id === selectedExperimentId) ?? null,
    [experiments, selectedExperimentId]
  );

  const submit = async (event: FormEvent) => {
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
          message: "Paper bot created on testnet. Open the bot detail page to enable execution when you're ready."
        });
        startTransition(() => router.refresh());
      } else {
        setCandidates((current) =>
          current.map((item) => (item.id === candidate.id ? { ...item, status: "live_candidate" } : item))
        );
        setActionFeedback({
          id: candidate.id,
          tone: "success",
          message: "Promotion request created. Review it on Cosmu Pro to spawn a live agent."
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
          <p className="muted">Cosmu Research</p>
          <h1>Autonomous research lab</h1>
          <p className="field-help">
            Research is the hypothesis lab. Each idea runs through Planner → Data Scout → Feature Builder → Skeptic →
            Summary. Approved ideas become paper candidates here. Promotion to Cosmu Pro creates an approval request,
            never a direct live trade.
          </p>
          <ul className="research-rules">
            <li>Paper-only by default — research bots stay on Binance testnet.</li>
            <li>Light bots are not visible here; Light is a quick-iteration tool kept separate.</li>
            <li>Backtests, leakage checks, multiple-testing penalties, and cost realism gate any promotion.</li>
          </ul>
        </div>
        <form className="research-command" onSubmit={submit}>
          <textarea
            value={hypothesis}
            onChange={(event) => setHypothesis(event.target.value)}
            placeholder="Example: test whether weather anomalies in mining hubs predict 24h BTC volatility, with strict anti-overfit review"
            rows={4}
          />
          <div className="command-panel-footer">
            <span className="field-help">Paper-only. Promotion to Cosmu Pro is approval-gated.</span>
            <button className="btn btn-primary" type="submit" disabled={submitting || hypothesis.trim().length < 5}>
              {submitting ? "Running..." : "Run research"}
            </button>
          </div>
          {error && <p className="feedback feedback-error">{error}</p>}
        </form>
      </section>

      <section className="ops-grid">
        <article className="panel">
          <div className="section-header">
            <h3>Experiments</h3>
            <span className="muted">{experiments.length} total</span>
          </div>
          <div className="dense-list">
            {experiments.length === 0 && (
              <p className="muted">No experiments yet. Run a hypothesis to start.</p>
            )}
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

        <article className="panel">
          <div className="section-header">
            <h3>Paper candidates</h3>
            <span className="muted">{candidates.length} total</span>
          </div>
          <div className="dense-list">
            {candidates.length === 0 && (
              <p className="muted">No paper candidates yet. Approved hypotheses appear here.</p>
            )}
            {candidates.map((candidate) => {
              const metrics = candidateMetrics(candidate);
              const feedback = actionFeedback?.id === candidate.id ? actionFeedback : null;
              const isPaperBotPending = pendingCandidate?.id === candidate.id && pendingCandidate.action === "paper-bot";
              const isPromotePending = pendingCandidate?.id === candidate.id && pendingCandidate.action === "promote";
              const hasPaperBot = Boolean(
                (candidate.metrics as { paperBotId?: string } | null)?.paperBotId
              );
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
                      {hasPaperBot ? "Paper bot exists" : isPaperBotPending ? "Creating..." : "Create paper bot"}
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
        </article>
      </section>

      {selectedExperiment && (
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
            title="Research agent timeline"
            initialSteps={selectedSteps ?? undefined}
          />
        </section>
      )}

      <section className="panel">
        <div className="section-header">
          <h3>Data sources</h3>
          <span className="muted">Read/paper-only in Research v1</span>
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
    </div>
  );
}
