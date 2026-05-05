"use client";

import { useEffect, useState } from "react";
import type { AgentStep } from "@cosmu/shared";
import { ChevronDown, ChevronRight } from "lucide-react";
import { LocalTime } from "./local-time";

type Props = {
  scopeType: AgentStep["scopeType"];
  scopeId: string;
  title?: string;
  initialSteps?: AgentStep[];
};

const statusClass = (status: AgentStep["status"]) => {
  if (status === "success") return "badge-success";
  if (status === "failure") return "badge-failure";
  if (status === "running") return "badge-running";
  if (status === "skipped") return "badge-inactive";
  return "badge-neutral";
};

const JsonBlock = ({ value }: { value: unknown }) => {
  if (value == null) return null;
  return (
    <pre className="timeline-json">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
};

export function AgentTimeline({ scopeType, scopeId, title = "Agent Timeline", initialSteps }: Props) {
  const [steps, setSteps] = useState<AgentStep[] | null>(initialSteps ?? null);
  const [expanded, setExpanded] = useState(false);
  const [openStep, setOpenStep] = useState<string | null>(null);

  useEffect(() => {
    if (!expanded || steps) return;
    const params = new URLSearchParams({ scopeType, scopeId });
    fetch(`/api/agent-steps?${params.toString()}`, { cache: "no-store" })
      .then((res) => res.ok ? res.json() : { steps: [] })
      .then((data) => setSteps(Array.isArray(data.steps) ? data.steps : []))
      .catch(() => setSteps([]));
  }, [expanded, scopeId, scopeType, steps]);

  return (
    <section className="timeline-panel">
      <button className="timeline-title" type="button" onClick={() => setExpanded((value) => !value)}>
        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <span>{title}</span>
        <span className="badge badge-neutral">{steps?.length ?? "load"}</span>
      </button>
      {expanded && (
        <div className="timeline-list">
          {steps === null && <p className="muted">Loading timeline...</p>}
          {steps?.length === 0 && <p className="muted">No agent steps recorded yet.</p>}
          {steps?.map((step) => {
            const open = openStep === step.id;
            return (
              <article key={step.id} className="timeline-step">
                <button className="timeline-step-main" type="button" onClick={() => setOpenStep(open ? null : step.id)}>
                  <span className={`timeline-dot timeline-dot-${step.status}`} />
                  <span className="timeline-step-label">{step.agentLabel}</span>
                  <span className={`badge ${statusClass(step.status)}`}>{step.status}</span>
                  {step.latencyMs != null && <span className="muted">{(step.latencyMs / 1000).toFixed(1)}s</span>}
                  <span className="muted"><LocalTime value={step.startedAt} /></span>
                </button>
                {open && (
                  <div className="timeline-step-detail">
                    {step.outputText && <p>{step.outputText}</p>}
                    {step.error && <p className="error-text">{step.error}</p>}
                    <div className="timeline-detail-grid">
                      <div>
                        <p className="label">Input</p>
                        <JsonBlock value={step.inputJson} />
                      </div>
                      <div>
                        <p className="label">Output</p>
                        <JsonBlock value={step.outputJson} />
                      </div>
                      <div>
                        <p className="label">Tool Calls</p>
                        <JsonBlock value={step.toolCalls} />
                      </div>
                    </div>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

