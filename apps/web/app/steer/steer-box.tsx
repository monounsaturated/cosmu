"use client";

// module: Steer box. Natural-language OPS steering, NOT authoring (authoring moved to Claude Code +
// the Overview "Needs you" inbox). Two slim asks:
//   - Steer command   -> POST /console/command  (policy/routing nudges; money-adjacent ones need approval)
//   - ML-through-NL    -> POST /lab/ml           (ask the survival model to re-rank / retrain in words)
// Both are LLM-optional and offline-safe: with no engine, we show an honest "not connected" note and
// never fabricate a reply. The deterministic Gate/scorer still disposes — this only nudges research.

import { useState, useTransition } from "react";
import { BrainCircuit, Send, ShieldCheck } from "lucide-react";
import type { CommandResponse } from "@cosmu/contracts-ts";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ENGINE_CONFIGURED, engineFetch } from "@/lib/engine";

type Reply = { md: string; applied: boolean; needsApproval: boolean } | { md: string; offline: true };

export function SteerBox() {
  const [text, setText] = useState("");
  const [reply, setReply] = useState<Reply | null>(null);
  const [mlText, setMlText] = useState("");
  const [mlReply, setMlReply] = useState<string | null>(null);
  const [steering, startSteer] = useTransition();
  const [asking, startAsk] = useTransition();

  function steer() {
    setReply(null);
    startSteer(async () => {
      if (!ENGINE_CONFIGURED) {
        setReply({ md: "Engine not connected — set API_BASE_URL to send steer commands.", offline: true });
        return;
      }
      try {
        const res = await engineFetch("/console/command", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ text })
        });
        if (!res.ok) throw new Error("engine unavailable");
        const data = (await res.json()) as CommandResponse;
        const needsApproval = Boolean((data.parsed_policy as { requires_money_move?: boolean }).requires_money_move);
        setReply({ md: data.reply_md, applied: data.applied, needsApproval });
      } catch {
        setReply({ md: "Engine not connected — could not send the steer command.", offline: true });
      }
    });
  }

  function askMl() {
    setMlReply(null);
    startAsk(async () => {
      if (!ENGINE_CONFIGURED) {
        setMlReply("Engine not connected — set API_BASE_URL to ask the survival model.");
        return;
      }
      try {
        const res = await engineFetch("/lab/ml", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ text: mlText })
        });
        if (!res.ok) throw new Error("engine unavailable");
        const data = (await res.json()) as { reply_md?: string };
        setMlReply(data.reply_md ?? "Request received. The model re-ranks the validation queue; it never vetoes.");
      } catch {
        setMlReply("Engine not connected — could not reach the survival model. The deterministic Gate still decides survival.");
      }
    });
  }

  return (
    <div className="space-y-6">
      {/* NL steer command */}
      <div className="space-y-3">
        <textarea
          className="min-h-24 w-full resize-y rounded-md border border-border bg-background/60 p-3 text-[13.5px] leading-relaxed text-foreground outline-none transition-colors placeholder:text-quiet focus-visible:border-iris/60 focus-visible:ring-2 focus-visible:ring-ring/40"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Steer research in plain language — e.g. 'prioritise funding-aware crypto ideas', 'pause the equity lane', 'tighten the per-strategy cap'."
        />
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11.5px] text-quiet">Money-adjacent changes are recorded but need approval.</span>
          <Button variant="primary" size="sm" type="button" onClick={steer} disabled={steering || !text.trim()}>
            <Send /> {steering ? "Sending…" : "Send steer"}
          </Button>
        </div>
        {reply ? (
          <div className="space-y-2 rounded-md border border-border/60 bg-surface-2/40 p-3.5">
            <div className="flex flex-wrap items-center gap-1.5">
              {"offline" in reply ? (
                <Badge variant="warn">engine not connected</Badge>
              ) : reply.applied ? (
                <Badge variant="up"><ShieldCheck className="size-3" /> applied</Badge>
              ) : reply.needsApproval ? (
                <Badge variant="warn">approval required</Badge>
              ) : (
                <Badge variant="info">recorded</Badge>
              )}
            </div>
            <p className="text-[12.5px] leading-relaxed text-muted">{reply.md}</p>
          </div>
        ) : null}
      </div>

      {/* ML-through-NL ask */}
      <div className="space-y-3 border-t border-border/50 pt-5">
        <div className="flex items-center gap-2 text-[12.5px] font-medium text-foreground">
          <BrainCircuit className="size-4 text-iris-soft" /> Ask the survival model
        </div>
        <textarea
          className="min-h-20 w-full resize-y rounded-md border border-border bg-background/60 p-3 text-[13.5px] leading-relaxed text-foreground outline-none transition-colors placeholder:text-quiet focus-visible:border-iris/60 focus-visible:ring-2 focus-visible:ring-ring/40"
          value={mlText}
          onChange={(e) => setMlText(e.target.value)}
          placeholder="Ask in words — e.g. 'retrain on the latest outcomes', 're-rank the validation queue toward low-PBO survivors'."
        />
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11.5px] text-quiet">The model only ORDERS the validation queue — it never vetoes survival.</span>
          <Button variant="secondary" size="sm" type="button" onClick={askMl} disabled={asking || !mlText.trim()}>
            <Send /> {asking ? "Asking…" : "Ask model"}
          </Button>
        </div>
        {mlReply ? (
          <div className="rounded-md border border-border/60 bg-surface-2/40 p-3.5 text-[12.5px] leading-relaxed text-muted">{mlReply}</div>
        ) : null}
      </div>
    </div>
  );
}
