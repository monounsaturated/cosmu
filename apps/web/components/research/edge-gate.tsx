"use client";

// module: Edge Gate surface. The system's stop-or-go decision — "does an exploitable edge exist
// after costs?" — made monitorable: one-click run, a plain pass/fail checklist against the
// pre-registered bar, and an honest data-source badge. Conceptually upstream of the Lab.

import { useEffect, useState, useTransition } from "react";
import { Database, FlaskConical, Play } from "lucide-react";
import type { GateStatusResponse, GateVerdictResponse } from "@cosmu/contracts-ts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { InterlockStrip, type Interlock } from "@/components/ui/viz";
import { ENGINE_CONFIGURED, engineFetch } from "@/lib/engine";

function pct(x: number) {
  return `${x >= 0 ? "+" : ""}${(x * 100).toFixed(1)}%`;
}

// The Gate verdict as a row of safety-interlock chips — each carries its REAL measured value and the
// threshold it was judged against, so the operator sees exactly which interlock held and which broke.
function interlocks(v: GateVerdictResponse): Interlock[] {
  const bar = v.bar as Record<string, number>;
  const minDsr = bar.min_deflated_sharpe_prob ?? 0.95;
  const maxPbo = bar.max_cscv_pbo ?? 0.5;
  const minRegimes = bar.min_regimes_positive ?? 2;
  const minTrades = bar.min_trades ?? 30;
  const maxDd = bar.max_drawdown ?? 0.25;
  return [
    { label: "Significant edge", value: v.deflated_sharpe_prob.toFixed(2), threshold: `dSR ≥ ${minDsr}`, pass: v.deflated_sharpe_prob >= minDsr },
    { label: "Not overfit", value: v.cscv_pbo.toFixed(2), threshold: `PBO < ${maxPbo}`, pass: v.cscv_pbo < maxPbo },
    { label: "Beats buy & hold", value: `${pct(v.best_return)} vs ${pct(v.buy_and_hold_return)}`, threshold: "net of fees", pass: v.best_return > v.buy_and_hold_return },
    { label: "Regimes positive", value: `${v.regimes_positive}`, threshold: `≥ ${minRegimes}`, pass: v.regimes_positive >= minRegimes },
    { label: "Trades", value: `${v.num_trades}`, threshold: `≥ ${minTrades}`, pass: v.num_trades >= minTrades },
    { label: "Max drawdown", value: pct(-v.max_drawdown), threshold: `< ${Math.round(maxDd * 100)}%`, pass: v.max_drawdown < maxDd }
  ];
}

export function EdgeGate() {
  const [verdict, setVerdict] = useState<GateVerdictResponse | null>(null);
  const [offline, setOffline] = useState(!ENGINE_CONFIGURED);
  const [running, startRun] = useTransition();

  useEffect(() => {
    if (!ENGINE_CONFIGURED) {
      setOffline(true);
      return;
    }
    engineFetch("/research/gate")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("offline"))))
      .then((s: GateStatusResponse) => {
        setVerdict(s.verdict);
        setOffline(false);
      })
      .catch(() => setOffline(true));
  }, []);

  function run() {
    setOffline(false);
    if (!ENGINE_CONFIGURED) {
      setOffline(true);
      return;
    }
    startRun(async () => {
      try {
        const res = await engineFetch("/research/gate", { method: "POST" });
        if (!res.ok) throw new Error("offline");
        setVerdict((await res.json()) as GateVerdictResponse);
        setOffline(false);
      } catch {
        setOffline(true);
      }
    });
  }

  // HONESTY INVARIANT: a verdict computed on anything other than LIVE data is NOT a verdict we will
  // display. We never render a synthetic PASS/STOP or its checklist — only an explicit "needs real data"
  // state. The numbers would be meaningless and showing them would violate "never display synthetic data".
  const isLiveVerdict = verdict?.data_source === "live";
  const passed = isLiveVerdict ? verdict?.passed : undefined;

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
        ) : !isLiveVerdict ? (
          // The engine only has synthetic inputs wired so far. We refuse to show a pass/fail on fake
          // data — that would be a fabricated track record. Show an honest "needs real data" state instead.
          <div className="space-y-3 rounded-md border border-warn/30 bg-warn/5 p-4">
            <div className="flex items-center gap-2">
              <Database className="size-4 text-warn" />
              <span className="text-[13px] font-medium text-foreground">Needs real data</span>
            </div>
            <p className="text-[12.5px] leading-relaxed text-muted">
              The edge gate ran on a synthetic fixture, so there is <span className="font-medium text-foreground">no honest verdict to show</span>.
              We never display a pass/fail on fabricated data. Wire a real source (e.g. <span className="font-medium text-foreground">LUNARCRUSH_API_KEY</span> and
              market bars) on the engine, then re-run for a genuine stop-or-go result.
            </p>
            <p className="text-[11.5px] text-quiet">See Settings → Keys for what unlocks a real verdict.</p>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <Badge variant={passed ? "up" : "down"} className="text-[12px]">
                {passed ? "PASS — an edge cleared the wall" : "STOP — no edge cleared the wall"}
              </Badge>
              <span className="text-[12px] text-quiet">
                best signal <span className="text-muted">{verdict.best_signal}</span> · {verdict.attempts} attempts
              </span>
              <Badge variant="info">live data</Badge>
            </div>

            <InterlockStrip interlocks={interlocks(verdict)} />

            <p className="text-[11.5px] leading-relaxed text-quiet">
              {passed
                ? "A signal cleared the deterministic wall (deflated Sharpe, CSCV overfit, regimes, costs). Proceed to the Lab and promote to Paper."
                : "Nothing cleared the wall. That is a real result — the alt-data thesis isn’t worth building further on this data."}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
