"use client";

// Plain-language idea intake: one input → POST /ideas/dump → polling status: received → testing → verdict.
// The deterministic Gate alone decides survival; this surface only queues and reports.

import { useCallback, useState } from "react";
import { Lightbulb, Send } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { engineFetch } from "@/lib/engine";

type Phase = "idle" | "received" | "testing" | "verdict";

export function IdeaDump({ connected }: { connected: boolean }) {
  const [text, setText] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [verdict, setVerdict] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const poll = useCallback(async (id: string) => {
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 1500));
      try {
        const res = await engineFetch(`/ideas/dump/${id}`);
        if (!res.ok) break;
        const data = (await res.json()) as { status: Phase; verdict?: string | null };
        setPhase(data.status);
        if (data.status === "verdict") {
          setVerdict(data.verdict ?? null);
          setBusy(false);
          return;
        }
      } catch {
        break;
      }
    }
    setPhase("verdict");
    setVerdict("Timed out — idea was queued but verdict is still pending.");
    setBusy(false);
  }, []);

  async function submit() {
    const body = text.trim();
    if (!body || busy) return;
    setError(null);
    setVerdict(null);
    setBusy(true);
    try {
      const res = await engineFetch("/ideas/dump", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text: body }),
      });
      if (!res.ok) throw new Error("engine unavailable");
      const data = (await res.json()) as { dump_id: string; status: string };
      setPhase("received");
      setText("");
      poll(data.dump_id);
    } catch {
      setError("Engine not connected — could not submit the idea.");
      setBusy(false);
    }
  }

  const badge =
    phase === "received" ? <Badge variant="muted">idea received</Badge>
    : phase === "testing" ? <Badge variant="info">testing</Badge>
    : phase === "verdict" ? <Badge variant="up">verdict</Badge>
    : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <Lightbulb className="size-4 text-iris-soft" /> Try an idea
        </CardTitle>
        <span className="text-[11px] text-quiet">Plain language → triage → verdict</span>
      </CardHeader>
      <CardContent className="space-y-3">
        <input
          className="w-full rounded-md border border-border bg-background/60 px-3 py-2.5 text-[13.5px] text-foreground outline-none transition-colors placeholder:text-quiet focus-visible:border-iris/60 focus-visible:ring-2 focus-visible:ring-ring/40 disabled:opacity-50"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && submit()}
          placeholder="e.g. buy BTC dips when funding flips negative"
          disabled={busy}
        />
        <div className="flex items-center justify-between gap-2">
          {badge ?? <span className="text-[11.5px] text-quiet">One field. One verdict.</span>}
          <Button
            variant="primary"
            size="sm"
            type="button"
            onClick={submit}
            disabled={!text.trim() || busy || !connected}
          >
            <Send /> {busy ? "…" : "Submit"}
          </Button>
        </div>

        {verdict ? (
          <p className="rounded-md border border-up/30 bg-up/5 px-3 py-2.5 text-[12.5px] leading-relaxed text-muted">
            {verdict}
          </p>
        ) : null}
        {error ? (
          <p className="rounded-md border border-warn/30 bg-warn/5 px-3 py-2.5 text-[12.5px] leading-relaxed text-warn">
            {error}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
