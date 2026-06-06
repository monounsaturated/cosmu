"use client";

// module: conversational strategy box — the operator types a plain-language idea, hits "Author spec",
// and gets a typed StrategySpec back SYNCHRONOUSLY with features / validity / guardrails rendered inline.
// A "Run Gate" button then calls /lab/author/run and shows the PASS/FAIL verdict with net-of-fee numbers
// from the best survivor in the cohort. No async queue; no "Queued, come back later" — you see the verdict.
//
// LLM-optional + offline-safe: with no engine we show an honest "not connected" note and never fabricate.
// The deterministic Gate alone decides survival — the LLM only proposes a typed spec.

import { useState, useTransition } from "react";
import { Check, ChevronDown, ChevronUp, Play, Send, ShieldCheck, X } from "lucide-react";
import type { AuthorResponse, CohortSummaryResponse } from "@cosmu/contracts-ts";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ENGINE_CONFIGURED, engineFetch } from "@/lib/engine";
import { cn } from "@/lib/utils";

// ---- helpers ----------------------------------------------------------------

function pct(x: number) {
  return `${x >= 0 ? "+" : ""}${(x * 100).toFixed(1)}%`;
}

// ---- sub-components ---------------------------------------------------------

function SpecCard({ spec }: { spec: AuthorResponse }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-md border border-border/60 bg-surface-2/40 text-[12.5px]">
      {/* Header row */}
      <div className="flex flex-wrap items-center gap-2 px-3.5 pt-3 pb-2">
        <span className="font-semibold text-foreground">{spec.name}</span>
        <Badge variant={spec.valid ? "up" : "down"}>
          {spec.valid ? <Check className="size-3" strokeWidth={3} /> : <X className="size-3" strokeWidth={3} />}
          {spec.valid ? "valid" : "invalid"}
        </Badge>
        {spec.requires_approval && <Badge variant="warn">needs approval</Badge>}
        <span className="ml-auto text-[11px] text-quiet">{spec.base_template}</span>
      </div>

      {/* Rationale */}
      {spec.rationale ? (
        <p className="px-3.5 pb-2 leading-relaxed text-muted">{spec.rationale}</p>
      ) : null}

      {/* Features row */}
      {spec.features.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-3.5 pb-2">
          {spec.features.map((f) => (
            <Badge key={f} variant="muted">{f}</Badge>
          ))}
        </div>
      )}

      {/* Issues */}
      {spec.issues.length > 0 && (
        <div className="px-3.5 pb-2 space-y-1">
          {spec.issues.map((issue) => (
            <div key={issue} className="flex items-center gap-1.5 text-down">
              <X className="size-3 shrink-0" strokeWidth={3} />
              <span>{issue}</span>
            </div>
          ))}
        </div>
      )}

      {/* Guardrails — toggleable */}
      {spec.guardrails.length > 0 && (
        <div className="border-t border-border/50">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="flex w-full items-center justify-between gap-2 px-3.5 py-2 text-[11.5px] text-quiet hover:text-foreground"
          >
            <span>{spec.guardrails.length} guardrail{spec.guardrails.length === 1 ? "" : "s"}</span>
            {open ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
          </button>
          {open && (
            <ul className="px-3.5 pb-3 space-y-1">
              {spec.guardrails.map((g) => (
                <li key={g} className="flex items-center gap-1.5 text-quiet">
                  <ShieldCheck className="size-3 shrink-0 text-up/70" />
                  <span>{g}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function GateResult({ result }: { result: CohortSummaryResponse }) {
  const passed = result.passed > 0;
  const best = result.survivors[0] ?? result.graveyard[0] ?? null;
  return (
    <div className={cn(
      "rounded-md border px-3.5 py-3 space-y-2 text-[12.5px]",
      passed ? "border-up/30 bg-up/5" : "border-down/30 bg-down/5"
    )}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={passed ? "up" : "down"} className="text-[12px]">
          {passed ? <Check className="size-3" strokeWidth={3} /> : <X className="size-3" strokeWidth={3} />}
          {passed ? `PASS — ${result.passed} of ${result.generated} cleared the wall` : `STOP — 0 of ${result.generated} cleared the wall`}
        </Badge>
        <span className="text-[11px] text-quiet">
          kill rate {(result.kill_rate * 100).toFixed(0)}%
        </span>
      </div>

      {/* Best survivor (or best graveyard entry) stats */}
      {best && (
        <div className="flex flex-wrap items-center gap-3 text-[12px]">
          <span className="font-medium text-foreground">{best.name}</span>
          <span className={cn("tabular font-semibold", best.oos_return_pct >= 0 ? "text-up" : "text-down")}>
            {pct(best.oos_return_pct / 100)} net-of-fees OOS
          </span>
          <span className="text-quiet">
            DSR {best.deflated_sharpe.toFixed(2)}
          </span>
        </div>
      )}

      {/* Kill reasons from graveyard */}
      {!passed && result.graveyard.length > 0 && result.graveyard[0].reasons.length > 0 && (
        <p className="text-[11.5px] leading-relaxed text-quiet">
          Killed: {result.graveyard[0].reasons.slice(0, 3).join(", ")}
        </p>
      )}

      <p className="text-[11.5px] leading-relaxed text-quiet">
        {passed
          ? "This spec survived the deterministic Gate (deflated Sharpe, CSCV, regimes, costs). It is now in the forward-test queue."
          : "No variant cleared the deterministic wall. That is an honest result — the Gate disposed of what the LLM proposed."}
      </p>
    </div>
  );
}

// ---- main component ---------------------------------------------------------

export function IdeaDumpBox() {
  const [text, setText] = useState("");
  // brief is the original text submitted — kept so Run Gate can replay the same brief
  const [brief, setBrief] = useState("");
  const [spec, setSpec] = useState<AuthorResponse | null>(null);
  const [gateResult, setGateResult] = useState<CohortSummaryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [authoring, startAuthor] = useTransition();
  const [running, startRun] = useTransition();

  function author() {
    setSpec(null);
    setGateResult(null);
    setError(null);
    const briefText = text.trim();
    startAuthor(async () => {
      if (!ENGINE_CONFIGURED) {
        setError("Engine not connected — set API_BASE_URL to author a spec.");
        return;
      }
      try {
        const res = await engineFetch("/lab/author", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ brief: briefText })
        });
        if (!res.ok) throw new Error("engine unavailable");
        setBrief(briefText);
        setSpec((await res.json()) as AuthorResponse);
        setText("");
      } catch {
        setError("Engine not connected — could not author the spec.");
      }
    });
  }

  function runGate() {
    if (!spec) return;
    setGateResult(null);
    setError(null);
    startRun(async () => {
      if (!ENGINE_CONFIGURED) {
        setError("Engine not connected — set API_BASE_URL to run the Gate.");
        return;
      }
      try {
        const res = await engineFetch("/lab/author/run", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ brief })
        });
        if (!res.ok) throw new Error("engine unavailable");
        setGateResult((await res.json()) as CohortSummaryResponse);
      } catch {
        setError("Engine not connected — could not run the Gate.");
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
        disabled={authoring}
      />
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11.5px] text-quiet">Author a typed spec. Then press Run Gate — the deterministic Gate alone decides survival.</span>
        <Button variant="primary" size="sm" type="button" onClick={author} disabled={authoring || !text.trim()}>
          <Send /> {authoring ? "Authoring…" : "Author spec"}
        </Button>
      </div>

      {error ? (
        <div className="rounded-md border border-warn/30 bg-warn/5 p-3 text-[12.5px] leading-relaxed text-warn">{error}</div>
      ) : null}

      {spec ? (
        <div className="space-y-2">
          <SpecCard spec={spec} />
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11.5px] text-quiet">Spec authored. Run the Gate to get a stop-or-go verdict with real bars.</span>
            <Button
              variant="secondary"
              size="sm"
              type="button"
              onClick={runGate}
              disabled={running || !spec.valid}
            >
              <Play className="size-3.5" />
              {running ? "Running Gate…" : "Run Gate"}
            </Button>
          </div>
          {!spec.valid && spec.issues.length > 0 ? (
            <p className="text-[11.5px] text-down">Fix the issues above before running the Gate.</p>
          ) : null}
        </div>
      ) : null}

      {gateResult ? <GateResult result={gateResult} /> : null}
    </div>
  );
}
