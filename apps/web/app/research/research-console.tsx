"use client";

import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import type { AgentStep, ResearchCandidate, ResearchDataSource, ResearchExperiment } from "@cosmu/shared";
import { AgentTimeline } from "../agent-timeline";
import { LocalTime } from "../local-time";

type Props = {
  initialCommand?: string;
  initialExperiments: ResearchExperiment[];
  initialDataSources: ResearchDataSource[];
  initialCandidates: ResearchCandidate[];
};

const statusBadge = (status: string) => {
  if (status.includes("candidate") || status.includes("ready")) return "badge-success";
  if (status.includes("rejected") || status.includes("failure")) return "badge-failure";
  if (status.includes("running")) return "badge-running";
  return "badge-neutral";
};

export function ResearchConsole({
  initialCommand = "",
  initialExperiments,
  initialDataSources,
  initialCandidates
}: Props) {
  const [hypothesis, setHypothesis] = useState(initialCommand);
  const [experiments, setExperiments] = useState(initialExperiments);
  const [candidates, setCandidates] = useState(initialCandidates);
  const [selectedExperimentId, setSelectedExperimentId] = useState(initialExperiments[0]?.id ?? null);
  const [selectedSteps, setSelectedSteps] = useState<AgentStep[] | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  return (
    <div className="research-layout">
      <section className="command-panel">
        <div>
          <p className="muted">Cosmu Research</p>
          <h1>Autonomous paper research</h1>
          <p className="field-help">
            Ask in natural language. Research v1 creates an observable paper-only experiment and blocks live trading.
          </p>
        </div>
        <form className="research-command" onSubmit={submit}>
          <textarea
            value={hypothesis}
            onChange={(event) => setHypothesis(event.target.value)}
            placeholder="Example: test whether weather anomalies affect BTC volatility, with strict anti-overfit review"
            rows={4}
          />
          <div className="command-panel-footer">
            <span className="field-help">Paper-only. Live promotion remains approval-gated.</span>
            <button className="btn btn-primary" type="submit" disabled={submitting || hypothesis.trim().length < 5}>
              {submitting ? "Running..." : "Run research"}
            </button>
          </div>
          {error && <p className="feedback feedback-error">{error}</p>}
        </form>
      </section>

      <section className="ops-grid">
        <article className="panel">
          <h3>Experiments</h3>
          <div className="dense-list">
            {experiments.length === 0 && <p className="muted">No experiments yet.</p>}
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
                  <span className="muted"><LocalTime value={experiment.createdAt} /></span>
                </span>
                <span className={`badge ${statusBadge(experiment.status)}`}>{experiment.status}</span>
              </button>
            ))}
          </div>
        </article>

        <article className="panel">
          <h3>Paper Candidates</h3>
          <div className="dense-list">
            {candidates.length === 0 && <p className="muted">No paper candidates yet.</p>}
            {candidates.map((candidate) => (
              <div key={candidate.id} className="dense-row-static">
                <span>
                  <strong>{candidate.name}</strong>
                  <span className="muted">{candidate.thesis}</span>
                </span>
                <span className={`badge ${statusBadge(candidate.status)}`}>{candidate.status}</span>
              </div>
            ))}
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
            title="Research Agent Timeline"
            initialSteps={selectedSteps ?? undefined}
          />
        </section>
      )}

      <section className="panel">
        <h3>Data Sources</h3>
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
