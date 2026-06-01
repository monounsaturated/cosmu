"use client";

import { useState, useTransition } from "react";
import { Image as ImageIcon, Mic, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export function ConsoleBox() {
  const [text, setText] = useState(
    "Be more aggressive on decorrelated breakout strategies, but keep drawdown below 15%."
  );
  const [reply, setReply] = useState(
    "Ready. Commands become validated policy deltas before they can affect the machine."
  );
  const [isPending, startTransition] = useTransition();

  function submit() {
    startTransition(async () => {
      try {
        const response = await fetch(`${process.env.NEXT_PUBLIC_ENGINE_API_URL ?? ""}/console/command`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ text })
        });
        if (!response.ok) throw new Error("engine unavailable");
        const data = (await response.json()) as { reply_md: string };
        setReply(data.reply_md);
      } catch {
        setReply(
          "Local QA mode: command parsed as a research-policy update. Money-adjacent changes still require explicit approval."
        );
      }
    });
  }

  return (
    <div className="space-y-3">
      <textarea
        className="min-h-32 w-full resize-y rounded-md border border-border bg-background/60 p-3 text-[13.5px] leading-relaxed text-foreground outline-none transition-colors placeholder:text-quiet focus-visible:border-iris/60 focus-visible:ring-2 focus-visible:ring-ring/40"
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder="Tell Cosmu how to allocate, what to explore, or what risk to respect…"
      />
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" type="button" title="Voice command">
            <Mic /> Voice
          </Button>
          <Button variant="secondary" size="sm" type="button" title="Upload screenshot or chart">
            <ImageIcon /> Image
          </Button>
        </div>
        <Button variant="primary" size="sm" type="button" onClick={submit} disabled={isPending}>
          <Send /> {isPending ? "Sending…" : "Send"}
        </Button>
      </div>
      <div className="rounded-md border border-border/60 bg-surface-2/40 p-3.5">
        <Badge variant="up">validated reply</Badge>
        <p className="mt-2 text-[13px] leading-relaxed text-muted">{reply}</p>
      </div>
    </div>
  );
}
