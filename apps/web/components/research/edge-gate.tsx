"use client";

// module: Edge Gate surface. The system's stop-or-go decision — "does an exploitable edge exist
// after costs?" — made monitorable: one-click run, a plain pass/fail checklist against the
// pre-registered bar, and an honest data-source badge. Conceptually upstream of the Lab.

import { useEffect, useState, useTransition } from "react";
import { Check, FlaskConical, Play, X } from "lucide-react";
import type { GateStatusResponse, GateVerdictResponse } from "@cosmu/contracts-ts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const ENGINE = process.env.NEXT_PUBLIC_ENGINE_API_URL ?? "";

function pct(x: number) {
  return `${x >= 0 ? "+" : ""}${(x * 100).toFixed(1)}%`;
}

function checklist(v: GateVerdictResponse) {
  const bar = v.bar as Record<string, number>;
  return [
    { label: `Statistically significant edge (deflated Sharpe ≥ ${bar.min_deflated_sharpe_prob ?? 0.95})`, ok: v.deflated_sharpe_prob >= (bar.min_deflated_sharpe_prob ?? 0.95), value: v.deflated_sharpe_prob.toFixed(2) },
    { label: `Not overfit (CSCV PBO < ${bar.max_cscv_pbo ?? 0.5})`, ok: v.cscv_pbo < (bar.max_cscv_pbo ?? 0.5), value: v.cscv_pbo.toFixed(2) },
    { label: "Beats buy & hold (net of fees)", ok: v.best_return > v.buy_and_hold_return, value: `${pct(v.best_return)} vs ${pct(v.buy_and_hold_return)}` },
    { label: `Works in ≥ ${bar.min_regimes_positive ?? 2} market regimes`, ok: v.regimes_positive >= (bar.min_regimes_positive ?? 2), value: `${v.regimes_positive}` },
    { label: `Enough trades (≥ ${bar.min_trades ?? 30})`, ok: v.num_trades >= (bar.min_trades ?? 30), value: `${v.num_trades}` },
    { label: `Drawdown under ${Math.round((bar.max_drawdown ?? 0.25) * 100)}%`, ok: v.max_drawdown < (bar.max_drawdown ?? 0.25), value: pct(-v.max_drawdown) }
  ];
}

export function EdgeGate() {
  const [verdict, setVerdict] = useState<GateVerdictResponse | null>(null);
  const [offline, setOffline] = useState(!ENGINE);
  const [running, startRun] = useTransition();

  useEffect(() => {
    if (!ENGINE) {
      setOffline(true);
      return;
    }
    fetch(`${ENGINE}/research/gate`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("offline"))))
      .then((s: GateStatusResponse) => {
        setVerdict(s.verdict);
        setOffline(false);
      })
      .catch(() => setOffline(true));
  }, []);

  function run() {
    setOffline(false);
    if (!ENGINE) {
      setOffline(true);
      return;
    }
    startRun(async () => {
      try {
        const res = await fetch(`${ENGINE}/research/gate`, { method: "POST" });
        if (!res.ok) throw new Error("offline");
        setVerdict((await res.json()) as GateVerdictResponse);
        setOffline(false);
      } catch {
        setOffline(true);
      }
    });
  }

  const passed = verdict?.passed;

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle className="flex items-center gap-2">
            <FlaskConical className="size-4 text-iris-soft" /> Edge gate
          </CardTitle>
          <CardDescription>Does an exploitable edge exist on Binance spot, after costs? Prove it before the Lab tests strategies.</CardDescription>
        </div>
        <Button onClick={run} disabled={running} size="sm">
          <Play className="size-3.5" /> {running ? "Running…" : "Run edge gate"}
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {!verdict ? (
          <p className="text-[13px] text-muted">
            {offline
              ? "Engine not connected — run the edge gate once the engine is up. No demo verdict is shown."
              : "No run yet. Press “Run edge gate” to get a stop-or-go verdict."}
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <Badge variant={passed ? "up" : "down"} className="text-[12px]">
                {passed ? "PASS — an edge cleared the wall" : "STOP — no edge cleared the wall"}
              </Badge>
              <span className="text-[12px] text-quiet">
                best signal <span className="text-muted">{verdict.best_signal}</span> · {verdict.attempts} attempts
              </span>
              <Badge variant={verdict.data_source === "live" ? "info" : "warn"}>
                {verdict.data_source === "live" ? "live data" : "synthetic data — wire LunarCrush for a real verdict"}
              </Badge>
            </div>

            <ul className="grid gap-1.5 sm:grid-cols-2">
              {checklist(verdict).map((c) => (
                <li key={c.label} className="flex items-center justify-between gap-2 rounded-md border border-border/50 bg-surface-2/30 px-3 py-2">
                  <span className="flex items-center gap-2 text-[12.5px]">
                    <span className={cn("flex size-4 shrink-0 items-center justify-center rounded-full", c.ok ? "bg-up/20 text-up" : "bg-down/20 text-down")}>
                      {c.ok ? <Check className="size-3" strokeWidth={3} /> : <X className="size-3" strokeWidth={3} />}
                    </span>
                    <span className="text-foreground">{c.label}</span>
                  </span>
                  <span className="tabular shrink-0 text-[12px] text-muted">{c.value}</span>
                </li>
              ))}
            </ul>

            <p className="text-[11.5px] leading-relaxed text-quiet">
              {passed
                ? "A signal cleared the deterministic wall (deflated Sharpe, CSCV overfit, regimes, costs). Proceed to the Lab and paper."
                : "Nothing cleared the wall. That is a real result — the alt-data thesis isn’t worth building further on this data."}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
