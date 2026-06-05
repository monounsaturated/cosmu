"use client";

// module: the Overview "Idea inbox" — a natural-language intake where the operator drops a strategy "vibe"
// in plain words. On submit it POSTs to /lab/inbox, which writes the prose as a brief into
// apps/engine/strategies/inbox/ and records an audited inbox_queued event. The next boot scan / autonomy
// tick turns each queued idea into a typed, GATED StrategySpec — this surface never authors or funds anything,
// it only queues prose and shows what is waiting. HONEST: with no engine it shows a not-connected note and
// never fabricates a queue; the deterministic Gate alone decides what survives.

import { useState, useTransition } from "react";
import Link from "next/link";
import { Eye, Lightbulb, Send, ShieldCheck } from "lucide-react";
import type { AuthorResponse, InboxIdeaResponse, InboxQueueItem, InboxQueueResponse } from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ENGINE_CONFIGURED, engineFetch } from "@/lib/engine";
import { timeAgo } from "@/lib/utils";

export function IdeaInbox({
  initial,
  connected,
  configured
}: {
  initial: InboxQueueItem[];
  connected: boolean;
  configured: boolean;
}) {
  const [text, setText] = useState("");
  const [items, setItems] = useState<InboxQueueItem[]>(initial ?? []);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [specPreview, setSpecPreview] = useState<AuthorResponse | null>(null);
  const [pending, startTransition] = useTransition();
  const [previewing, startPreview] = useTransition();

  function submit() {
    setNote(null);
    setError(null);
    setSpecPreview(null);
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
          setItems(list.items ?? []);
        }
      } catch {
        setError("Engine not connected — could not queue the idea.");
      }
    });
  }

  function previewSpec() {
    setSpecPreview(null);
    setError(null);
    const body = text.trim();
    if (!body) return;
    if (!ENGINE_CONFIGURED) {
      setError("Engine not connected — set API_BASE_URL to preview a spec.");
      return;
    }
    startPreview(async () => {
      try {
        const res = await engineFetch("/lab/author", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ brief: body })
        });
        if (!res.ok) throw new Error("engine unavailable");
        setSpecPreview((await res.json()) as AuthorResponse);
      } catch {
        setError("Engine not connected — could not preview the spec.");
      }
    });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <Lightbulb className="size-4 text-iris-soft" /> Idea inbox
        </CardTitle>
        <span className="text-[11px] text-quiet">Gated, never funded directly</span>
      </CardHeader>
      <CardContent className="space-y-3">
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
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" type="button" onClick={previewSpec} disabled={previewing || pending || !text.trim()}>
              <Eye /> {previewing ? "Previewing…" : "Preview spec"}
            </Button>
            <Button variant="primary" size="sm" type="button" onClick={submit} disabled={pending || previewing || !text.trim()}>
              <Send /> {pending ? "Queuing…" : "Queue idea"}
            </Button>
          </div>
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

        {/* Spec preview — read-only; the Gate alone decides if the authored spec survives. */}
        {specPreview ? (
          <div className="space-y-2 rounded-md border border-iris/20 bg-iris/5 p-3">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[12.5px] font-semibold text-foreground">{specPreview.name}</span>
              <Badge variant={specPreview.valid ? "up" : "warn"}>{specPreview.valid ? "valid" : "invalid"}</Badge>
              <span className="text-[11px] text-quiet">read-only preview</span>
            </div>
            {specPreview.rationale ? (
              <p className="text-[12px] leading-relaxed text-muted">{specPreview.rationale}</p>
            ) : null}
            {specPreview.features.length > 0 ? (
              <div>
                <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-quiet">Features</div>
                <div className="flex flex-wrap gap-1">
                  {specPreview.features.map((f) => (
                    <Badge key={f} variant="info">{f}</Badge>
                  ))}
                </div>
              </div>
            ) : null}
            {specPreview.issues.length > 0 ? (
              <ul className="space-y-0.5">
                {specPreview.issues.map((iss) => (
                  <li key={iss} className="text-[11.5px] text-warn">{iss}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}

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
                <li key={item.filename}>
                  {item.status === "imported" ? (
                    <Link
                      href="/strategies"
                      className="flex items-center justify-between gap-3 rounded-md border border-border/50 bg-surface-2/30 px-3 py-2 transition-colors hover:bg-surface-2/50"
                    >
                      <span className="min-w-0 truncate text-[12.5px] text-foreground">{item.name}</span>
                      <span className="flex shrink-0 items-center gap-2">
                        <span className="text-[11px] text-quiet">{timeAgo(item.ts) ?? ""}</span>
                        <Badge variant="up">{item.status}</Badge>
                      </span>
                    </Link>
                  ) : (
                    <div className="flex items-center justify-between gap-3 rounded-md border border-border/50 bg-surface-2/30 px-3 py-2">
                      <span className="min-w-0 truncate text-[12.5px] text-foreground">{item.name}</span>
                      <span className="flex shrink-0 items-center gap-2">
                        <span className="text-[11px] text-quiet">{timeAgo(item.ts) ?? ""}</span>
                        <Badge variant="info">{item.status}</Badge>
                      </span>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
