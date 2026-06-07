"use client";

// module: idea intake — the ONE natural-language strategy-intake component, shared by the Overview and the
// Lab. The operator drops a strategy "vibe" in plain words; on submit it POSTs to /lab/inbox, which writes
// the prose as a brief into apps/engine/strategies/inbox/ and records an audited inbox_queued event. The
// next boot scan / autonomy tick turns each queued idea into a typed, GATED StrategySpec — this surface
// never authors, scores, or funds anything; it only queues prose and shows what is waiting. HONEST: with no
// engine it shows a not-connected note and never fabricates a queue; the deterministic Gate alone decides
// what survives.
//
// Two presentations from one core:
//   • variant="card"  — full Card with header + inline queue list (the Lab's "vibe loop" surface).
//   • variant="bare"  — chrome-free textarea + button, for embedding inside another card (the Overview,
//                       where the queue is already rendered separately).

import { useState, useTransition } from "react";
import { Lightbulb, Send, ShieldCheck } from "lucide-react";
import type { InboxIdeaResponse, InboxQueueItem, InboxQueueResponse } from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ENGINE_CONFIGURED, engineFetch } from "@/lib/engine";
import { timeAgo } from "@/lib/utils";

export function IdeaIntake({
  variant = "card",
  initial = [],
  connected = false,
  configured = false
}: {
  variant?: "card" | "bare";
  initial?: InboxQueueItem[];
  connected?: boolean;
  configured?: boolean;
}) {
  const [text, setText] = useState("");
  const [items, setItems] = useState<InboxQueueItem[]>(initial);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function submit() {
    setNote(null);
    setError(null);
    const body = text.trim();
    if (!body) return;
    if (!ENGINE_CONFIGURED) {
      setError("Engine not connected — set API_BASE_URL to queue ideas.");
      return;
    }
    startTransition(async () => {
      try {
        const res = await engineFetch("/lab/inbox", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ text: body })
        });
        if (!res.ok) throw new Error("engine unavailable");
        const data = (await res.json()) as InboxIdeaResponse;
        setNote(data.note);
        setText("");
        // Re-read the queue so the new idea shows with its real, audited status (never an optimistic fake).
        const listRes = await engineFetch("/lab/inbox");
        if (listRes.ok) {
          const list = (await listRes.json()) as InboxQueueResponse;
          setItems(list.items);
        }
      } catch {
        setError("Engine not connected — could not queue the idea.");
      }
    });
  }

  const form = (
    <>
      <textarea
        className="min-h-24 w-full resize-y rounded-md border border-border bg-background/60 p-3 text-[13.5px] leading-relaxed text-foreground outline-none transition-colors placeholder:text-quiet focus-visible:border-iris/60 focus-visible:ring-2 focus-visible:ring-ring/40"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Drop a strategy vibe in plain words — e.g. 'buy oversold BTC dips when funding flips negative', 'short the perp when liquidations cascade', 'momentum, but only when the trend is strong'."
      />
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11.5px] text-quiet">
          The next tick turns this into a typed spec the deterministic Gate judges.
        </span>
        <Button variant="primary" size="sm" type="button" onClick={submit} disabled={pending || !text.trim()}>
          <Send /> {pending ? "Queuing…" : "Queue idea"}
        </Button>
      </div>

      {note ? (
        <div className="flex items-start gap-2 rounded-md border border-up/30 bg-up/5 p-3 text-[12.5px] leading-relaxed text-muted">
          <ShieldCheck className="mt-0.5 size-3.5 shrink-0 text-up" />
          <span>{note}</span>
        </div>
      ) : null}
      {error ? (
        <div className="rounded-md border border-warn/30 bg-warn/5 p-3 text-[12.5px] leading-relaxed text-warn">{error}</div>
      ) : null}
    </>
  );

  // Bare variant — chrome-free, for embedding inside another card (the Overview pipeline). The queue is
  // rendered separately by the host, so we omit the inline list here.
  if (variant === "bare") {
    return <div className="space-y-3">{form}</div>;
  }

  // Card variant — the Lab's standalone "vibe loop" surface, with the inline queue list.
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <Lightbulb className="size-4 text-iris-soft" /> Idea inbox
        </CardTitle>
        <span className="text-[11px] text-quiet">Gated, never funded directly</span>
      </CardHeader>
      <CardContent className="space-y-3">
        {form}

        {/* Queued ideas — honest: read straight off the engine's event ledger. */}
        <div className="border-t border-border/50 pt-3">
          <div className="mb-2 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-quiet">Queue</div>
          {!connected ? (
            <p className="text-[12px] text-quiet">
              {configured
                ? "Engine not responding — queued ideas will appear here once it is up."
                : "Set API_BASE_URL to connect the engine and see queued ideas."}
            </p>
          ) : items.length === 0 ? (
            <p className="text-[12px] text-quiet">No ideas queued yet — drop one above and it joins the next gated cohort.</p>
          ) : (
            <ul className="space-y-1.5">
              {items.slice(0, 6).map((item) => (
                <li
                  key={item.filename}
                  className="flex items-center justify-between gap-3 rounded-md border border-border/50 bg-surface-2/30 px-3 py-2"
                >
                  <span className="min-w-0 truncate text-[12.5px] text-foreground">{item.name}</span>
                  <span className="flex shrink-0 items-center gap-2">
                    <span className="text-[11px] text-quiet">{timeAgo(item.ts) ?? ""}</span>
                    <Badge variant={item.status === "imported" ? "up" : "info"}>{item.status}</Badge>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
