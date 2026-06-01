"use client";

import { useState, useTransition } from "react";
import { Database, Send, ShieldCheck, Sparkles, TriangleAlert } from "lucide-react";
import type { AuthorResponse } from "@cosmu/contracts-ts";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const ENGINE = process.env.NEXT_PUBLIC_ENGINE_API_URL ?? "";

const OFFLINE_DRAFT: AuthorResponse = {
  name: "Fade oversold RSI on crypto (chat)",
  rationale: "Fade oversold RSI on crypto with a tight stop, swing horizon.",
  base_template: "mean_reversion",
  features: ["rsi", "bb_z"],
  data_sources: ["parquet_bars"],
  venues: ["binance"],
  valid: true,
  issues: [],
  requires_approval: false,
  guardrails: [
    "structure only — thresholds live in param_space, fit from data (no magic numbers)",
    "the scorer and gates judge it; they stay out of this authoring path",
    "draft is research-only; live capital stays gated"
  ],
  notes: ["model router disabled (offline) — deterministic template match used"],
  spec: {}
};

export function ConsoleBox() {
  const [brief, setBrief] = useState("Fade oversold RSI on crypto with a tight stop, swing horizon.");
  const [draft, setDraft] = useState<AuthorResponse | null>(null);
  const [sent, setSent] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const [drafting, startDraft] = useTransition();
  const [sending, startSend] = useTransition();

  function authorDraft() {
    setSent(null);
    startDraft(async () => {
      try {
        const res = await fetch(`${ENGINE}/lab/author`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ brief })
        });
        if (!res.ok) throw new Error("engine unavailable");
        setDraft((await res.json()) as AuthorResponse);
        setOffline(false);
      } catch {
        setDraft({ ...OFFLINE_DRAFT, rationale: brief, name: `${brief.slice(0, 40)} (chat)` });
        setOffline(true);
      }
    });
  }

  function sendToFarm() {
    startSend(async () => {
      try {
        const res = await fetch(`${ENGINE}/lab/author/run`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ brief, cohort_size: 80 })
        });
        if (!res.ok) throw new Error("engine unavailable");
        const data = (await res.json()) as { generated: number; passed: number };
        setSent(`Seeded a cohort of ${data.generated} — ${data.passed} cleared the gates into paper.`);
      } catch {
        setSent("Offline: the brief would seed a cohort and farm alongside mutations and wildcards.");
      }
    });
  }

  return (
    <div className="space-y-3">
      <textarea
        className="min-h-28 w-full resize-y rounded-md border border-border bg-background/60 p-3 text-[13.5px] leading-relaxed text-foreground outline-none transition-colors placeholder:text-quiet focus-visible:border-iris/60 focus-visible:ring-2 focus-visible:ring-ring/40"
        value={brief}
        onChange={(e) => setBrief(e.target.value)}
        placeholder="Describe a strategy idea — features, market, horizon, risk. e.g. 'momentum breakout on equities, daily bars'"
      />
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11.5px] text-quiet">Plain-language brief → typed, validated draft</span>
        <Button variant="primary" size="sm" type="button" onClick={authorDraft} disabled={drafting}>
          <Sparkles /> {drafting ? "Drafting…" : "Draft strategy"}
        </Button>
      </div>

      {draft ? (
        <div className="space-y-3 rounded-md border border-border/60 bg-surface-2/40 p-3.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-[13px] font-medium text-foreground">{draft.name}</span>
            <div className="flex items-center gap-1.5">
              <Badge variant="info">{draft.base_template.replace(/_/g, " ")}</Badge>
              {draft.valid ? (
                <Badge variant="up"><ShieldCheck className="size-3" /> validated</Badge>
              ) : (
                <Badge variant="down"><TriangleAlert className="size-3" /> invalid</Badge>
              )}
              {draft.requires_approval ? <Badge variant="warn">approval required</Badge> : null}
              {offline ? <Badge variant="warn">offline</Badge> : null}
            </div>
          </div>

          <div className="flex flex-wrap gap-1.5">
            {draft.features.map((f) => (
              <span key={f} className="rounded border border-iris/30 bg-iris/10 px-1.5 py-0.5 font-mono text-[10.5px] text-iris-soft">{f}</span>
            ))}
          </div>
          <div className="flex items-center gap-1.5 text-[11.5px] text-muted">
            <Database className="size-3.5 text-quiet" />
            sources: {draft.data_sources.join(", ")} · venues: {draft.venues.join(", ")}
          </div>

          <ul className="space-y-1 border-t border-border/50 pt-2">
            {draft.guardrails.map((g) => (
              <li key={g} className="flex items-start gap-1.5 text-[11.5px] leading-snug text-quiet">
                <ShieldCheck className="mt-0.5 size-3 shrink-0 text-up" /> {g}
              </li>
            ))}
          </ul>

          <div className="flex items-center justify-between gap-2 border-t border-border/50 pt-2">
            <span className="text-[11.5px] text-muted">{sent ?? "Send the draft into the farm to test it against mutations + wildcards."}</span>
            <Button variant="secondary" size="sm" type="button" onClick={sendToFarm} disabled={sending}>
              <Send /> {sending ? "Seeding…" : "Send to farm"}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
