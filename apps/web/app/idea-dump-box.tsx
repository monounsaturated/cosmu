"use client";

// module: idea-dump box — the operator's natural-language strategy intake on the Overview page. A loose
// idea (text) is POSTed to the engine's inbox, which writes it as a brief and queues it for the next scan
// to translate into a typed StrategySpec routed through the DETERMINISTIC Gate. This box never authors,
// scores, or funds — it only queues prose. LLM-optional + offline-safe: with no engine we show an honest
// "not connected" note and never fabricate a reply.
//
// NOTE: the intake endpoint is POST /lab/inbox (the engine's idea-dump). There is no /ideas/dump route.

import { useState, useTransition } from "react";
import { Send, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ENGINE_CONFIGURED, engineFetch } from "@/lib/engine";

type Reply = { md: string; queued: number } | { md: string; offline: true };

export function IdeaDumpBox() {
  const [text, setText] = useState("");
  const [reply, setReply] = useState<Reply | null>(null);
  const [sending, startSend] = useTransition();

  function dump() {
    setReply(null);
    startSend(async () => {
      if (!ENGINE_CONFIGURED) {
        setReply({ md: "Engine not connected — set API_BASE_URL to queue ideas.", offline: true });
        return;
      }
      try {
        const res = await engineFetch("/lab/inbox", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ text })
        });
        if (!res.ok) throw new Error("engine unavailable");
        const data = (await res.json()) as { note?: string; queued?: number };
        setReply({
          md: data.note ?? "Queued. The next tick translates it into a typed, gated spec — the Gate alone decides survival.",
          queued: data.queued ?? 0
        });
        setText("");
      } catch {
        setReply({ md: "Engine not connected — could not queue the idea.", offline: true });
      }
    });
  }

  return (
    <div className="space-y-3">
      <textarea
        className="min-h-24 w-full resize-y rounded-md border border-border bg-background/60 p-3 text-[13.5px] leading-relaxed text-foreground outline-none transition-colors placeholder:text-quiet focus-visible:border-iris/60 focus-visible:ring-2 focus-visible:ring-ring/40"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Dump a strategy idea in plain language — e.g. 'fade funding spikes on the top-10 perps', 'cross-sectional momentum, weekly rebalance, funding-contrarian filter'."
      />
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11.5px] text-quiet">Queued as prose. The deterministic Gate alone decides survival — never the model.</span>
        <Button variant="primary" size="sm" type="button" onClick={dump} disabled={sending || !text.trim()}>
          <Send /> {sending ? "Queuing…" : "Dump idea"}
        </Button>
      </div>
      {reply ? (
        <div className="space-y-2 rounded-md border border-border/60 bg-surface-2/40 p-3.5">
          <div className="flex flex-wrap items-center gap-1.5">
            {"offline" in reply ? (
              <Badge variant="warn">engine not connected</Badge>
            ) : (
              <Badge variant="up"><Sparkles className="size-3" /> queued{reply.queued ? ` · ${reply.queued} waiting` : ""}</Badge>
            )}
          </div>
          <p className="text-[12.5px] leading-relaxed text-muted">{reply.md}</p>
        </div>
      ) : null}
    </div>
  );
}
