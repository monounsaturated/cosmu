// The analyst panel — a TradingAgents-style team of perspectives that each read the agent's existing signals
// and debate one standardized market read. The consensus card summarizes the vote; the stance cards show every
// perspective's lean, conviction and why. A reasoning surface only — the railguard says so out loud.

import { Brain, Scale, ShieldCheck } from "lucide-react";
import type { MindResponse, MindStance } from "@cosmu/contracts-ts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const LEAN: Record<string, { label: string; variant: "up" | "down" | "muted" | "outline"; bar: string }> = {
  bullish: { label: "Bullish", variant: "up", bar: "bg-up" },
  bearish: { label: "Bearish", variant: "down", bar: "bg-down" },
  neutral: { label: "Neutral", variant: "muted", bar: "bg-muted" },
  abstain: { label: "Abstaining", variant: "outline", bar: "bg-border-strong" }
};

function ConvictionBar({ value, bar }: { value: number; bar: string }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
      <div className={cn("h-full rounded-full transition-all", bar)} style={{ width: `${Math.round(value * 100)}%` }} />
    </div>
  );
}

function StanceCard({ stance }: { stance: MindStance }) {
  const lean = LEAN[stance.lean] ?? LEAN.neutral;
  return (
    <div className="rounded-lg border border-border/60 bg-surface-2/30 p-3.5">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <span className="text-[13px] font-semibold text-foreground">{stance.perspective}</span>
          {stance.low_confidence ? <Badge variant="outline">low confidence</Badge> : null}
        </div>
        <Badge variant={lean.variant}>{lean.label}</Badge>
      </div>
      <p className="text-[12.5px] font-medium text-muted">{stance.headline}</p>
      {stance.lean !== "abstain" ? (
        <div className="mt-2.5 space-y-1">
          <div className="flex items-center justify-between text-[10.5px] uppercase tracking-wide text-quiet">
            <span>Conviction</span>
            <span className="tabular">{Math.round(stance.conviction * 100)}%</span>
          </div>
          <ConvictionBar value={stance.conviction} bar={lean.bar} />
        </div>
      ) : null}
      <p className="mt-2.5 text-[11.5px] leading-relaxed text-quiet">{stance.rationale}</p>
      {stance.evidence.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1">
          {stance.evidence.map((e) => (
            <span key={e} className="rounded bg-surface-2/60 px-1.5 py-0.5 font-mono text-[10px] text-muted">{e}</span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function AnalystPanel({ mind }: { mind: MindResponse }) {
  const market = mind.stances.filter((s) => s.kind === "market");
  const process = mind.stances.filter((s) => s.kind === "process");
  const consensus = LEAN[mind.consensus] ?? LEAN.neutral;

  return (
    <div className="space-y-4">
      {/* The debate's consensus */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            <Scale className="size-4 text-iris-soft" /> Consensus read
          </CardTitle>
          <Badge variant="muted">
            <ShieldCheck className="size-3" /> Reasons · never funds
          </Badge>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <Badge variant={consensus.variant} className="text-[13px]">{consensus.label}</Badge>
            {mind.contested ? <Badge variant="warn">Contested</Badge> : null}
            <div className="flex flex-1 flex-wrap gap-4">
              <Meter label="Conviction" value={mind.conviction} bar={consensus.bar} />
              <Meter label="Panel agreement" value={mind.agreement} bar="bg-iris" />
            </div>
          </div>
          {mind.narrative ? <p className="text-[12.5px] leading-relaxed text-muted">{mind.narrative}</p> : null}
          {(mind.bull_case.length > 0 || mind.bear_case.length > 0) && (
            <div className="grid gap-3 sm:grid-cols-2">
              <CaseColumn title="Bull case" perspectives={mind.bull_case} tone="up" />
              <CaseColumn title="Bear case" perspectives={mind.bear_case} tone="down" />
            </div>
          )}
        </CardContent>
      </Card>

      {/* Market analysts */}
      <div>
        <h3 className="mb-2.5 flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
          <Brain className="size-4 text-iris-soft" /> The panel
        </h3>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {market.map((s) => (
            <StanceCard key={s.perspective} stance={s} />
          ))}
        </div>
      </div>

      {/* Process pillars: ML + memory (self-knowledge, not a price call) */}
      {process.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {process.map((s) => (
            <div key={s.perspective} className="rounded-lg border border-border/60 bg-surface-2/20 p-3.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[13px] font-semibold text-foreground">{s.perspective}</span>
                <span className="tabular text-[11px] text-quiet">{Math.round(s.conviction * 100)}%</span>
              </div>
              <p className="mt-1 text-[12.5px] font-medium text-muted">{s.headline}</p>
              <p className="mt-1.5 text-[11.5px] leading-relaxed text-quiet">{s.rationale}</p>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function Meter({ label, value, bar }: { label: string; value: number; bar: string }) {
  return (
    <div className="min-w-[120px] flex-1 space-y-1">
      <div className="flex items-center justify-between text-[10.5px] uppercase tracking-wide text-quiet">
        <span>{label}</span>
        <span className="tabular">{Math.round(value * 100)}%</span>
      </div>
      <ConvictionBar value={value} bar={bar} />
    </div>
  );
}

function CaseColumn({ title, perspectives, tone }: { title: string; perspectives: string[]; tone: "up" | "down" }) {
  return (
    <div className="rounded-md border border-border/50 bg-surface-2/20 px-3 py-2.5">
      <div className={cn("mb-1.5 text-[11px] font-semibold uppercase tracking-wide", tone === "up" ? "text-up" : "text-down")}>
        {title}
      </div>
      {perspectives.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {perspectives.map((p) => (
            <Badge key={p} variant={tone}>{p}</Badge>
          ))}
        </div>
      ) : (
        <p className="text-[11.5px] text-quiet">No perspective on this side.</p>
      )}
    </div>
  );
}
