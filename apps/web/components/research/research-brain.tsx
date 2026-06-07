// module: Research brain panel. The single, scannable answer to "what is the machine doing right now?"
// Reads GET /research/brain (server-fetched via data.ts; renders an honest empty state when the engine
// is unreachable — no demo fallback, no synthetic numbers) and lays it out with progressive disclosure:
// a summary row (LLM state, regime, gate funnel) up top, then survivors, the survival-model ranking,
// the graveyard, and the active sources + bus tools.
//
// PRINCIPLE surfaced honestly in the copy: the deterministic SCORER/gate decides survival; the ML
// survival model NEVER vetoes — it only ORDERS the validation queue (which candidate to compute first)
// and flags overfit. Cold-start = cheap/random ordering until enough labeled outcomes exist to train +
// OOS-validate, so a useless early model can't strangle discovery.
//
// Types are locally-typed against the shared snake_case contract in data.ts until @cosmu/contracts-ts
// ships them (will be reconciled). The Graveyard list is the only interactive piece (expand/collapse).

import { Brain, Database, Radio, Skull, Sparkles, Wrench } from "lucide-react";
import type { BrainResponse } from "@/app/data";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";
import { formatPct } from "@/lib/utils";
import { Graveyard } from "./research-brain-graveyard";

const SURVIVAL_SCORE_HINT =
  "Survival score = the model's estimate this edge persists out-of-sample. It only ORDERS the validation queue — it never vetoes an idea.";

const RANKING_HINT = (
  <div className="space-y-1.5">
    <p>
      The survival model picks <span className="font-semibold text-foreground">which candidate to validate first</span> — it
      prioritizes compute, it never kills an idea.
    </p>
    <p>
      <span className="font-semibold text-warn">Cold-start</span> — too few labeled outcomes to train yet, so ordering is
      cheap/random. Once enough exist the model trains, is OOS-validated, then takes over.
    </p>
  </div>
);

const LLM_HINT =
  "The LLM only authors and mutates ideas. It is OUT of the survival path — the deterministic scorer/gate decides what lives.";

function FunnelStep({ label, value, tone }: { label: string; value: number | string; tone: string }) {
  return (
    <div className="rounded-md border border-border/60 bg-surface-2/40 px-3 py-2">
      <div className="text-[10.5px] uppercase tracking-wide text-quiet">{label}</div>
      <div className={`mt-0.5 text-lg font-semibold tabular ${tone}`}>{value}</div>
    </div>
  );
}

export function ResearchBrain({ brain }: { brain: BrainResponse }) {
  const { llm, gated, survivors, graveyard, sources, tools, regime, survival_ranking } = brain;
  const anyTrained = survival_ranking.some((r) => r.trained);

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <Brain className="size-4 text-iris-soft" /> Research brain
          </CardTitle>
          <p className="mt-1 text-[13px] leading-snug text-muted">What the machine is doing right now — authoring, gating, and ranking what to validate next.</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5">
            <Badge variant={llm === "on" ? "up" : "muted"}>
              <Sparkles className="size-3" /> LLM {llm}
            </Badge>
            <Tooltip content={LLM_HINT} />
          </span>
        </div>
      </CardHeader>

      <CardContent className="space-y-5">
        {/* Summary: regime + gate funnel */}
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="iris">regime · {regime.label}</Badge>
          <Badge variant="muted">vol {regime.vol_bucket}</Badge>
          <Badge variant={regime.trend === "up" ? "up" : regime.trend === "down" ? "down" : "muted"}>trend {regime.trend}</Badge>
        </div>

        <div>
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-quiet">Gate funnel</div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <FunnelStep label="Generated" value={gated.generated} tone="text-foreground" />
            <FunnelStep label="Passed" value={gated.passed} tone="text-up" />
            <FunnelStep label="Killed" value={gated.killed} tone="text-down" />
            <FunnelStep label="Kill rate" value={formatPct(gated.kill_rate * 100, 1)} tone="text-warn" />
          </div>
        </div>

        {/* Survivors */}
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-quiet">
            Survivors <Tooltip content={SURVIVAL_SCORE_HINT} />
          </div>
          {survivors.length === 0 ? (
            <p className="text-[12.5px] text-muted">No survivors yet — nothing has cleared the deterministic gate.</p>
          ) : (
            <ul className="space-y-1.5">
              {survivors.map((s) => (
                <li
                  key={s.version_id}
                  className="flex items-center justify-between gap-3 rounded-md border border-border/50 bg-surface-2/30 px-3 py-2"
                >
                  <span className="min-w-0 truncate text-[12.5px] font-medium text-foreground">{s.name}</span>
                  <span className="flex shrink-0 items-center gap-3">
                    <span className={`tabular text-[12.5px] ${s.net_pct >= 0 ? "text-up" : "text-down"}`}>{formatPct(s.net_pct)}</span>
                    <Badge variant="iris">score {s.survival_score.toFixed(2)}</Badge>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Survival-model ranking — orders the validation queue, never vetoes */}
        <div>
          <div className="mb-2 flex flex-wrap items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-quiet">
            Validation queue ranking <Tooltip content={RANKING_HINT} />
            <Badge variant={anyTrained ? "up" : "warn"} className="ml-1 normal-case">
              {anyTrained ? "model trained" : "cold-start · cheap ordering"}
            </Badge>
          </div>
          {survival_ranking.length === 0 ? (
            <p className="text-[12.5px] text-muted">No candidates queued for validation.</p>
          ) : (
            <ol className="space-y-1.5">
              {survival_ranking.map((r, i) => (
                <li
                  key={r.version_id}
                  className="flex items-center justify-between gap-3 rounded-md border border-border/50 bg-surface-2/30 px-3 py-2"
                >
                  <span className="flex min-w-0 items-center gap-2.5">
                    <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-iris/12 text-[11px] font-semibold tabular text-iris-soft">
                      {i + 1}
                    </span>
                    <span className="min-w-0 truncate text-[12.5px] font-medium text-foreground">{r.name}</span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    <span className="tabular text-[12px] text-muted">{r.score.toFixed(2)}</span>
                    <Badge variant={r.trained ? "up" : "warn"}>{r.trained ? "trained" : "cold-start"}</Badge>
                  </span>
                </li>
              ))}
            </ol>
          )}
        </div>

        {/* Graveyard (progressive disclosure) */}
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-quiet">
            <Skull className="size-3.5" /> Graveyard · why ideas died
          </div>
          <Graveyard rows={graveyard} />
        </div>

        {/* Sources + tools */}
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-quiet">
              <Database className="size-3.5" /> Data sources
            </div>
            {sources.length === 0 ? (
              <p className="text-[12.5px] text-muted">No data sources wired yet.</p>
            ) : (
              <ul className="space-y-1.5">
                {sources.map((src) => (
                  <li
                    key={src.name}
                    className="flex items-center justify-between gap-2 rounded-md border border-border/50 bg-surface-2/30 px-3 py-2"
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <Radio className={`size-3.5 shrink-0 ${src.low_confidence ? "text-warn" : "text-up"}`} />
                      <span className="min-w-0 truncate text-[12.5px] text-foreground">{src.name}</span>
                    </span>
                    <span className="flex shrink-0 items-center gap-1.5">
                      <Badge variant="muted">{src.kind}</Badge>
                      {src.low_confidence ? (
                        <span className="inline-flex items-center gap-1">
                          <Badge variant="warn">low-confidence</Badge>
                          <Tooltip content="OSINT plane — treated as low-confidence: it can suggest ideas but carries less weight in the gate." />
                        </span>
                      ) : null}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-quiet">
              <Wrench className="size-3.5" /> Tools on the bus
            </div>
            {tools.length === 0 ? (
              <p className="text-[12.5px] text-muted">No tools registered.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {tools.map((t) => (
                  <Badge key={t} variant="muted">
                    {t.replace(/_/g, " ")}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
