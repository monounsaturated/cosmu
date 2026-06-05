"use client";

import { useState, useTransition } from "react";
import { Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ENGINE_CONFIGURED, engineFetch } from "@/lib/engine";

export function IdeaInput() {
  const [text, setText] = useState("");
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const [pending, start] = useTransition();

  function submit() {
    setResult(null);
    start(async () => {
      if (!ENGINE_CONFIGURED) {
        setResult({ ok: false, msg: "Engine not connected — set API_BASE_URL to queue ideas." });
        return;
      }
      try {
        const res = await engineFetch("/lab/inbox", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ brief: text.trim() }),
        });
        if (!res.ok) throw new Error("engine error");
        setResult({ ok: true, msg: "Queued — the machine will pick it up next tick." });
        setText("");
      } catch {
        setResult({ ok: false, msg: "Could not reach the engine. Try again." });
      }
    });
  }

  return (
    <div className="space-y-3">
      <textarea
        className="min-h-[72px] w-full resize-y rounded-md border border-border bg-background/60 p-3 text-[13.5px] leading-relaxed text-foreground outline-none transition-colors placeholder:text-quiet focus-visible:border-iris/60 focus-visible:ring-2 focus-visible:ring-ring/40"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Describe a strategy idea in plain language — e.g. 'momentum on funding rate divergence across crypto perps'"
      />
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11.5px] text-quiet">Queued ideas are picked up on the next autonomous tick.</span>
        <Button variant="primary" size="sm" type="button" onClick={submit} disabled={pending || !text.trim()}>
          <Send className="size-3.5" /> {pending ? "Sending…" : "Queue idea"}
        </Button>
      </div>
      {result ? (
        <p className={`text-[12.5px] ${result.ok ? "text-up" : "text-warn"}`}>{result.msg}</p>
      ) : null}
    </div>
  );
}
