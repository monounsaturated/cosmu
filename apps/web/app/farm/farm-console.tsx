"use client";

import { useState, useTransition } from "react";
import { FileCode, FlaskConical, Play, Skull, Sprout, Upload, Wand2 } from "lucide-react";
import type { CohortSummaryResponse, PineTranslateResponse } from "@cosmu/contracts-ts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { formatPct } from "@/lib/utils";

const ENGINE = process.env.NEXT_PUBLIC_ENGINE_API_URL ?? "";

const laneStyle: Record<string, "iris" | "up" | "warn" | "info"> = {
  seed: "info",
  exploit: "iris",
  explore: "warn",
  pine: "up"
};

const PINE_LIBRARY: Record<string, string> = {
  "RSI + MA cross": `//@version=5
strategy("RSI + MA cross", overlay=true)
rsiVal = ta.rsi(close, 14)
fast = ta.sma(close, 10)
slow = ta.ema(close, 30)
longCondition = ta.crossover(fast, slow) and rsiVal < 35
strategy.exit("x", stop=0.05, limit=0.12)`,
  "Golden cross trend": `//@version=5
strategy("Golden Cross", overlay=true)
fast = ta.sma(close, 50)
slow = ta.sma(close, 200)
longCondition = ta.crossover(fast, slow)
strategy.entry("Long", strategy.long, when=longCondition)
strategy.exit("Exit", stop=0.08, limit=0.2)`,
  "Bollinger breakout": `//@version=5
strategy("Bollinger Breakout", overlay=true)
length = input.int(20)
mult = input.float(2.0)
basis = ta.sma(close, length)
dev = mult * ta.stdev(close, length)
upper = basis + dev
longCondition = close > upper
strategy.entry("L", strategy.long, when=longCondition)
strategy.exit("X", stop=0.05, limit=0.15)`,
  "ADX trend filter": `//@version=5
strategy("ADX Trend", overlay=true)
adxVal = ta.adx(14)
rsiVal = ta.rsi(close, 14)
longCondition = adxVal > 25 and rsiVal > 50
strategy.entry("L", strategy.long, when=longCondition)
strategy.exit("X", stop=0.06, limit=0.14)`
};

const SAMPLE_PINE = PINE_LIBRARY["RSI + MA cross"];

export function FarmConsole({ fallback }: { fallback: CohortSummaryResponse }) {
  const [cohortSize, setCohortSize] = useState(120);
  const [explorePct, setExplorePct] = useState(0.3);
  const [pine, setPine] = useState(SAMPLE_PINE);
  const [usePine, setUsePine] = useState(false);
  const [result, setResult] = useState<CohortSummaryResponse>(fallback);
  const [preview, setPreview] = useState<PineTranslateResponse | null>(null);
  const [offline, setOffline] = useState(false);
  const [running, startRun] = useTransition();
  const [translating, startTranslate] = useTransition();

  function runCohort() {
    startRun(async () => {
      try {
        const res = await fetch(`${ENGINE}/evolution/run`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            cohort_size: cohortSize,
            explore_pct: explorePct,
            pine_scripts: usePine && pine.trim() ? [pine] : null
          })
        });
        if (!res.ok) throw new Error("engine unavailable");
        setResult((await res.json()) as CohortSummaryResponse);
        setOffline(false);
      } catch {
        setResult({ ...fallback, cohort_id: `demo-${Date.now().toString(36)}` });
        setOffline(true);
      }
    });
  }

  function translatePine() {
    startTranslate(async () => {
      try {
        const res = await fetch(`${ENGINE}/strategy/pine`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ source: pine })
        });
        if (!res.ok) throw new Error("engine unavailable");
        setPreview((await res.json()) as PineTranslateResponse);
        setUsePine(true);
        setOffline(false);
      } catch {
        setPreview({
          name: "RSI + MA cross (pine)",
          param_count: 5,
          indicators: ["rsiVal=ta.rsi", "fast=ta.sma", "slow=ta.ema"],
          conditions: ["ta.crossover(fast, slow)", "rsiVal < 35"],
          notes: ["offline preview — thresholds 35 / 0.05 / 0.12 lifted into a fitted param_space"],
          lifted_params: { th_rsi: 35, stop: 0.05, take: 0.12 },
          spec: {}
        });
        setUsePine(true);
        setOffline(true);
      }
    });
  }

  const passPct = result.generated ? (result.passed / result.generated) * 100 : 0;
  const killPct = result.kill_rate * 100;

  return (
    <div className="space-y-3">
      {/* Controls */}
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Run an autonomous cohort</CardTitle>
            <CardDescription>
              Generate a wide population, screen every candidate through the out-of-reach scorer, keep the survivors.
            </CardDescription>
          </div>
          <FlaskConical className="size-4 text-iris-soft" />
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="space-y-1.5">
              <div className="flex items-center justify-between text-[12px] text-muted">
                <span>Cohort size</span>
                <span className="tabular text-foreground">{cohortSize}</span>
              </div>
              <input
                type="range"
                min={20}
                max={400}
                step={20}
                value={cohortSize}
                onChange={(e) => setCohortSize(Number(e.target.value))}
                className="w-full accent-[var(--color-iris)]"
              />
            </label>
            <label className="space-y-1.5">
              <div className="flex items-center justify-between text-[12px] text-muted">
                <span>Explore budget (wildcards)</span>
                <span className="tabular text-foreground">{Math.round(explorePct * 100)}%</span>
              </div>
              <input
                type="range"
                min={0}
                max={0.7}
                step={0.05}
                value={explorePct}
                onChange={(e) => setExplorePct(Number(e.target.value))}
                className="w-full accent-[var(--color-iris)]"
              />
            </label>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="primary" onClick={runCohort} disabled={running}>
              <Play /> {running ? "Farming…" : "Run cohort"}
            </Button>
            <label className="flex items-center gap-2 text-[12.5px] text-muted">
              <input type="checkbox" checked={usePine} onChange={(e) => setUsePine(e.target.checked)} className="accent-[var(--color-iris)]" />
              include Pine import in cohort
            </label>
            {offline ? <Badge variant="warn">offline demo data</Badge> : <Badge variant="up">live engine</Badge>}
          </div>
        </CardContent>
      </Card>

      {/* Funnel */}
      <div className="grid gap-3 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Cohort funnel</CardTitle>
              <CardDescription>
                <span className="font-mono text-[11.5px]">{result.cohort_id}</span> · seed {result.seed}
              </CardDescription>
            </div>
            <Badge variant="down">
              <Skull className="size-3" /> {formatPct(killPct, 1)} killed
            </Badge>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-3 gap-3">
              <Funnel label="Generated" value={result.generated} tone="text-foreground" />
              <Funnel label="Survivors" value={result.passed} tone="text-up" />
              <Funnel label="Graveyard" value={result.killed} tone="text-down" />
            </div>
            <div>
              <div className="mb-1.5 flex items-center justify-between text-[11.5px] text-quiet">
                <span>explore wide · gate hard at the money valve</span>
                <span className="tabular">{passPct.toFixed(1)}% survive</span>
              </div>
              <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-surface-2">
                <div className="h-full bg-up" style={{ width: `${Math.max(passPct, 1.5)}%` }} />
                <div className="h-full bg-down/70" style={{ width: `${100 - passPct}%` }} />
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(result.lanes).map(([lane, n]) => (
                <Badge key={lane} variant={laneStyle[lane] ?? "muted"}>
                  {lane === "seed" ? <Sprout className="size-3" /> : lane === "pine" ? <FileCode className="size-3" /> : <Wand2 className="size-3" />}
                  {lane} · {Number(n)}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Pine import */}
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Pine Script import</CardTitle>
              <CardDescription>Magic numbers become a fitted search space.</CardDescription>
            </div>
            <FileCode className="size-4 text-quiet" />
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <select
                onChange={(e) => e.target.value && setPine(PINE_LIBRARY[e.target.value])}
                defaultValue=""
                className="h-8 rounded-md border border-border bg-surface-2/60 px-2 text-[12px] text-foreground outline-none focus-visible:border-iris/60"
              >
                <option value="">Load community sample…</option>
                {Object.keys(PINE_LIBRARY).map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
              <label className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md border border-border bg-surface-2/60 px-2.5 text-[12px] text-muted hover:text-foreground">
                <Upload className="size-3.5" /> Upload .pine
                <input
                  type="file"
                  accept=".pine,.txt,text/plain"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) file.text().then(setPine);
                  }}
                />
              </label>
            </div>
            <textarea
              value={pine}
              onChange={(e) => setPine(e.target.value)}
              spellCheck={false}
              className="h-36 w-full resize-y rounded-md border border-border bg-background/60 p-2.5 font-mono text-[11.5px] leading-relaxed text-iris-soft outline-none focus-visible:border-iris/60 focus-visible:ring-2 focus-visible:ring-ring/40"
            />
            <Button variant="secondary" size="sm" onClick={translatePine} disabled={translating}>
              <Wand2 /> {translating ? "Translating…" : "Translate to spec"}
            </Button>
            {preview ? (
              <div className="space-y-2 rounded-md border border-border/60 bg-surface-2/40 p-3 text-[12px]">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-foreground">{preview.name}</span>
                  <Badge variant="iris">{preview.param_count} fitted params</Badge>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(preview.lifted_params).map(([k, v]) => (
                    <span key={k} className="rounded border border-border/60 bg-background/50 px-1.5 py-0.5 font-mono text-[10.5px] text-muted">
                      {k}={String(v)}
                    </span>
                  ))}
                </div>
                {preview.notes.length ? <p className="text-[11.5px] leading-snug text-quiet">{preview.notes[0]}</p> : null}
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>

      {/* Survivors + graveyard */}
      <div className="grid gap-3 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Survivors — decorrelated handful</CardTitle>
            <Badge variant="up">{result.survivors.length} kept</Badge>
          </CardHeader>
          <CardContent className="pt-0">
            <Table>
              <THead>
                <TR>
                  <TH>Strategy</TH>
                  <TH>Lane</TH>
                  <TH className="text-right">D-Sharpe</TH>
                  <TH className="text-right">OOS</TH>
                </TR>
              </THead>
              <TBody>
                {result.survivors.map((s) => (
                  <TR key={s.version_id}>
                    <TD className="max-w-[220px] truncate font-medium text-foreground">{s.name}</TD>
                    <TD><Badge variant={laneStyle[s.lane] ?? "muted"}>{s.lane}</Badge></TD>
                    <TD className="text-right tabular text-foreground">{s.deflated_sharpe.toFixed(2)}</TD>
                    <TD className="text-right tabular text-up">{formatPct(s.oos_return_pct)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Graveyard — deaths with reasons</CardTitle>
            <Badge variant="down"><Skull className="size-3" /> {result.killed}</Badge>
          </CardHeader>
          <CardContent className="space-y-2">
            {result.graveyard.map((g) => (
              <div key={g.version_id} className="flex items-center justify-between gap-3 rounded-md border border-border/50 bg-surface-2/30 px-3 py-2">
                <span className="max-w-[200px] truncate text-[12.5px] text-muted">{g.name}</span>
                <div className="flex flex-wrap justify-end gap-1">
                  {g.reasons.map((r) => (
                    <Badge key={r} variant="down">{r.replace(/_/g, " ")}</Badge>
                  ))}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function Funnel({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="rounded-md border border-border/60 bg-surface-2/40 p-3 text-center">
      <div className={`text-2xl font-semibold tabular ${tone}`}>{value}</div>
      <div className="mt-0.5 text-[11px] uppercase tracking-wide text-quiet">{label}</div>
    </div>
  );
}
