"use client";

// module: "Needs you" inbox — the human-overview/approval surface. The autonomous machine PROPOSES;
// the human disposes here. Each recommendation gets a plain-language body + Approve / Dismiss
// (POST /recommendations/{id}/approve|dismiss), optimistic UI, and an honest empty state.
//
// PRINCIPLES: approving a recommendation never itself moves money — the deterministic Gate/scorer
// disposes and the human arms live separately; approve just lets a proposal proceed. LLM-OPTIONAL +
// OFFLINE-safe: with no engine we surface an honest not-connected note and never fabricate a result.
// Optimistic: the row leaves the list immediately and is restored if the engine rejects the call.

import { useState, useTransition } from "react";
import { Check, Inbox, PlugZap, X } from "lucide-react";
import type { Recommendation } from "@cosmu/contracts-ts";
import type { ApproveResult, DismissResult } from "@/app/autonomy-contracts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/honest-state";
import { ENGINE_CONFIGURED, engineFetch } from "@/lib/engine";

type Resolved = { id: string; label: string; tone: "up" | "muted" };

export function NeedsYouInbox({
  initial,
  connected,
  configured
}: {
  initial: Recommendation[];
  connected: boolean;
  configured: boolean;
}) {
  // Only open recommendations need the human; the engine may already mark some approved/dismissed.
  const [items, setItems] = useState<Recommendation[]>(initial.filter((r) => r.state === "open"));
  const [resolved, setResolved] = useState<Resolved[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [, startTransition] = useTransition();

  function act(rec: Recommendation, kind: "approve" | "dismiss") {
    setNote(null);
    const prev = items;
    // Optimistic: drop the row immediately.
    setItems((list) => list.filter((r) => r.id !== rec.id));
    startTransition(async () => {
      if (!ENGINE_CONFIGURED) {
        setItems(prev);
        setNote("Engine not connected — set API_BASE_URL to approve or dismiss.");
        return;
      }
      try {
        const res = await engineFetch(`/recommendations/${rec.id}/${kind}`, { method: "POST" });
        if (!res.ok) throw new Error("engine unavailable");
        if (kind === "approve") {
          const data = (await res.json()) as ApproveResult;
          if (!data.ok) {
            setItems(prev);
            setNote(data.reason ?? "The engine could not approve this recommendation.");
            return;
          }
          setResolved((r) => [
            { id: rec.id, label: data.applied ? "Approved · applied" : "Approved · queued", tone: "up" },
            ...r
          ]);
        } else {
          const data = (await res.json()) as DismissResult;
          if (!data.ok) {
            setItems(prev);
            setNote("The engine could not dismiss this recommendation.");
            return;
          }
          setResolved((r) => [{ id: rec.id, label: "Dismissed", tone: "muted" }, ...r]);
        }
      } catch {
        setItems(prev);
        setNote(`Engine not connected — could not ${kind} this recommendation.`);
      }
    });
  }

  const [expanded, setExpanded] = useState(false);
  const PREVIEW_COUNT = 3;
  const visibleItems = expanded ? items : items.slice(0, PREVIEW_COUNT);
  const hiddenCount = items.length - PREVIEW_COUNT;

  return (
    <div className="space-y-2.5">
      {items.length === 0 && resolved.length === 0 ? (
        <EmptyState
          title={connected ? "Nothing needs you right now." : "Machine status unknown."}
          hint={
            connected
              ? "When the machine proposes a decision that needs your call, it lands here."
              : configured
                ? "The engine is configured but did not respond. Approvals appear once it is up."
                : "Set API_BASE_URL to see what the machine needs from you."
          }
          icon={<Inbox className="size-5" />}
        />
      ) : null}

      {visibleItems.map((rec) => (
        <div key={rec.id} className="rounded-md border border-border/60 bg-surface-2/40 p-3">
          <Badge variant="warn">{rec.kind.replace(/_/g, " ")}</Badge>
          <p className="mt-2 text-[12.5px] leading-relaxed text-muted">{rec.body}</p>
          <div className="mt-3 flex items-center gap-2">
            <Button variant="primary" size="sm" type="button" onClick={() => act(rec, "approve")}>
              <Check /> Approve
            </Button>
            <Button variant="ghost" size="sm" type="button" onClick={() => act(rec, "dismiss")}>
              <X /> Dismiss
            </Button>
          </div>
        </div>
      ))}

      {!expanded && hiddenCount > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="w-full rounded-md border border-border/50 bg-surface-2/30 py-2 text-[12px] font-medium text-muted transition-colors hover:bg-surface-2/50 hover:text-foreground"
        >
          +{hiddenCount} more
        </button>
      )}

      {resolved.slice(0, 3).map((r) => (
        <div
          key={`resolved-${r.id}`}
          className="flex items-center gap-2 rounded-md border border-border/40 bg-surface-2/20 px-3 py-2 text-[12px] text-quiet"
        >
          <Badge variant={r.tone}>{r.label}</Badge>
        </div>
      ))}

      {note ? (
        <div className="flex items-center gap-2 rounded-md border border-warn/35 bg-warn/10 px-3 py-2 text-[12px] text-warn">
          <PlugZap className="size-3.5 shrink-0" />
          <span>{note}</span>
        </div>
      ) : null}
    </div>
  );
}
