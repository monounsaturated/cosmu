"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { ApprovalRequest } from "@cosmu/shared";
import { LocalTime } from "../local-time";

type Props = {
  initialApprovals: ApprovalRequest[];
};

type Pending = { id: string; action: "approve" | "reject" } | null;

const formatPayloadValue = (value: unknown): string => {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
};

const PAYLOAD_DISPLAY_KEYS: Record<string, string> = {
  candidateId: "Candidate",
  experimentId: "Experiment",
  suggestedMode: "Suggested mode",
  suggestedVenue: "Suggested venue"
};

export function ProApprovals({ initialApprovals }: Props) {
  const router = useRouter();
  const [approvals, setApprovals] = useState(initialApprovals);
  const [pending, setPending] = useState<Pending>(null);
  const [error, setError] = useState<string | null>(null);
  const [, startTransition] = useTransition();

  const act = async (approval: ApprovalRequest, action: "approve" | "reject") => {
    setPending({ id: approval.id, action });
    setError(null);
    try {
      const res = await fetch(`/api/agent-control/approvals/${approval.id}/${action}`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Action failed");
      setApprovals((current) => current.filter((item) => item.id !== approval.id));
      startTransition(() => router.refresh());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setPending(null);
    }
  };

  return (
    <section className="panel" style={{ marginTop: "20px" }}>
      <div className="section-header">
        <h3>Approval inbox</h3>
        <span className="muted">{approvals.length} pending</span>
      </div>
      <p className="field-help">
        Promotion requests from Cosmu Research. Approving creates a Pro bot with execution disabled — a human still has
        to enable trading on the bot detail page.
      </p>
      {error && <p className="feedback feedback-error">{error}</p>}
      <div className="approval-list">
        {approvals.length === 0 && (
          <p className="muted">Inbox empty. Promotions from Research will appear here for review.</p>
        )}
        {approvals.map((approval) => {
          const payload = (approval.payload && typeof approval.payload === "object"
            ? (approval.payload as Record<string, unknown>)
            : {}) as Record<string, unknown>;
          const payloadEntries = Object.entries(payload).filter(([key]) => key in PAYLOAD_DISPLAY_KEYS);
          const isApproving = pending?.id === approval.id && pending.action === "approve";
          const isRejecting = pending?.id === approval.id && pending.action === "reject";
          return (
            <article key={approval.id} className="approval-row">
              <div className="approval-row-head">
                <div>
                  <strong>{approval.title}</strong>
                  <span className="muted">
                    {approval.requestType.replace(/_/g, " ")} · <LocalTime value={approval.createdAt} />
                  </span>
                </div>
                <span className="badge badge-running">{approval.status}</span>
              </div>
              {approval.body && <p className="muted candidate-risk">{approval.body}</p>}
              {payloadEntries.length > 0 && (
                <dl className="approval-payload">
                  {payloadEntries.map(([key, value]) => (
                    <div key={key}>
                      <dt>{PAYLOAD_DISPLAY_KEYS[key]}</dt>
                      <dd>{formatPayloadValue(value)}</dd>
                    </div>
                  ))}
                </dl>
              )}
              <div className="approval-actions">
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => act(approval, "approve")}
                  disabled={Boolean(pending)}
                >
                  {isApproving ? "Approving..." : "Approve & spawn Pro bot"}
                </button>
                <button
                  type="button"
                  className="btn btn-danger"
                  onClick={() => act(approval, "reject")}
                  disabled={Boolean(pending)}
                >
                  {isRejecting ? "Rejecting..." : "Reject"}
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
