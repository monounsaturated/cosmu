"use client";

// module: Autonomy status panel — the COMMAND CENTER for the autonomous machine the human oversees.
// Plain language: is it RUNNING or PAUSED, what it last did, what it will do next, cycles run, live
// on/off. Controls: Pause / Resume (POST /autonomy/pause|resume) and "Run a cycle now" (POST
// /autonomy/tick) which shows the bounded cycle's result.
//
// PRINCIPLES: this panel only REPORTS + sends pause/resume/tick. It never moves money — the
// deterministic Gate/scorer disposes, out of any LLM path, and the human arms live separately.
// LLM-OPTIONAL + OFFLINE-safe: with no engine we show an honest "not connected" note and never
// fabricate a running machine or a tick result. Optimistic on pause/resume, reconciled by the
// engine's response.

import { useState, useTransition } from "react";
import { Activity, Pause, Play, PlugZap, Zap } from "lucide-react";
import type { AutonomyStatus, AutonomyTickResult, PauseResumeResult } from "@/app/autonomy-contracts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { MoneyState, moneyMode } from "@/components/ui/money-state";

const ENGINE = process.env.NEXT_PUBLIC_ENGINE_API_URL ?? "";

function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "—";
  const secs = Math.round((Date.now() - t) / 1000);
  if (secs < 0) return "just now";
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

// Plain-language state badge. Honest when not connected: "unknown", never "running".
function stateBadge(status: AutonomyStatus, connected: boolean) {
  if (!connected) return { variant: "muted" as const, label: "status unknown" };
  if (status.paused) return { variant: "warn" as const, label: "Paused" };
  if (status.running) return { variant: "up" as const, label: "Running" };
  return { variant: "muted" as const, label: "Idle" };
}

export function AutonomyPanel({
  initial,
  connected: initialConnected,
  configured,
  compact = false
}: {
  initial: AutonomyStatus;
  connected: boolean;
  configured: boolean;
  compact?: boolean;
}) {
  const [status, setStatus] = useState<AutonomyStatus>(initial);
  const [connected, setConnected] = useState(initialConnected);
  const [tick, setTick] = useState<AutonomyTickResult | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [pendingToggle, startToggle] = useTransition();
  const [pendingTick, startTick] = useTransition();

  const badge = stateBadge(status, connected);
  const money = moneyMode({ live: status.live_enabled });

  async function refresh() {
    if (!ENGINE) return;
    try {
      const res = await fetch(`${ENGINE}/autonomy/status`);
      if (!res.ok) throw new Error("engine unavailable");
      setStatus((await res.json()) as AutonomyStatus);
      setConnected(true);
    } catch {
      setConnected(false);
    }
  }

  function setPaused(paused: boolean) {
    setNote(null);
    // Optimistic: flip the state immediately; the engine response reconciles it.
    const prev = status;
    setStatus({ ...status, paused });
    startToggle(async () => {
      if (!ENGINE) {
        setStatus(prev);
        setConnected(false);
        setNote("Engine not connected — set ENGINE_API_URL to pause or resume the machine.");
        return;
      }
      try {
        const res = await fetch(`${ENGINE}/autonomy/${paused ? "pause" : "resume"}`, { method: "POST" });
        if (!res.ok) throw new Error("engine unavailable");
        const data = (await res.json()) as PauseResumeResult;
        setStatus((s) => ({ ...s, paused: data.paused }));
        setConnected(true);
        await refresh();
      } catch {
        setStatus(prev);
        setConnected(false);
        setNote(`Engine not connected — could not ${paused ? "pause" : "resume"} the machine.`);
      }
    });
  }

  function runCycle() {
    setNote(null);
    setTick(null);
    startTick(async () => {
      if (!ENGINE) {
        setConnected(false);
        setNote("Engine not connected — set ENGINE_API_URL to run a cycle.");
        return;
      }
      try {
        const res = await fetch(`${ENGINE}/autonomy/tick`, { method: "POST" });
        if (!res.ok) throw new Error("engine unavailable");
        setTick((await res.json()) as AutonomyTickResult);
        setConnected(true);
        await refresh();
      } catch {
        setConnected(false);
        setNote("Engine not connected — could not run a cycle.");
      }
    });
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex min-w-0 items-center gap-2">
          <Activity className="size-4 shrink-0 text-iris-soft" />
          <CardTitle>What the machine is doing</CardTitle>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={badge.variant}>{badge.label}</Badge>
          <MoneyState mode={money} withInfo={false} />
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Plain-language last/next line — the heart of "what's it doing?" */}
        <dl className="space-y-2.5">
          <Line label="Last did" value={connected && status.last_action ? status.last_action : "—"} />
          <Line label="Next" value={connected && status.next_action ? status.next_action : "—"} />
          <Line
            label="Last cycle"
            value={
              connected ? `${relativeTime(status.last_tick_at)} · ${status.cycles_run} cycle${status.cycles_run === 1 ? "" : "s"} run` : "—"
            }
          />
        </dl>

        {/* Last cycle's counts — what it produced, no money figures */}
        {!compact ? (
          <div className="grid grid-cols-4 gap-2">
            <Count label="Authored" value={connected ? status.last_summary.authored : null} />
            <Count label="Gate passed" value={connected ? status.last_summary.gated_passed : null} />
            <Count label="Funded" value={connected ? status.last_summary.funded : null} />
            <Count label="For you" value={connected ? status.last_summary.recommendations : null} />
          </div>
        ) : null}

        {/* Controls */}
        <div className="flex flex-wrap items-center gap-2">
          {status.paused ? (
            <Button variant="primary" size="sm" type="button" onClick={() => setPaused(false)} disabled={pendingToggle}>
              <Play /> {pendingToggle ? "Resuming…" : "Resume"}
            </Button>
          ) : (
            <Button variant="secondary" size="sm" type="button" onClick={() => setPaused(true)} disabled={pendingToggle}>
              <Pause /> {pendingToggle ? "Pausing…" : "Pause"}
            </Button>
          )}
          <Button variant="outline" size="sm" type="button" onClick={runCycle} disabled={pendingTick}>
            <Zap /> {pendingTick ? "Running…" : "Run a cycle now"}
          </Button>
          <span className="text-[11px] text-quiet">The Gate alone decides survival + funding — this only proposes.</span>
        </div>

        {/* Tick result — honest counts from one bounded cycle */}
        {tick ? (
          <div className="rounded-md border border-border/60 bg-surface-2/40 p-3">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-quiet">Cycle result</div>
            <div className="mt-2 grid grid-cols-4 gap-2">
              <Count label="Authored" value={tick.authored} />
              <Count label="Gate passed" value={tick.gated_passed} />
              <Count label="Funded" value={tick.funded} />
              <Count label="For you" value={tick.recommendations} />
            </div>
          </div>
        ) : null}

        {note ? (
          <div className="flex items-center gap-2 rounded-md border border-warn/35 bg-warn/10 px-3 py-2 text-[12px] text-warn">
            <PlugZap className="size-3.5 shrink-0" />
            <span>{note}</span>
          </div>
        ) : !connected ? (
          <div className="flex items-center gap-2 rounded-md border border-border/70 bg-surface-2/40 px-3 py-2 text-[12px] text-muted">
            <PlugZap className="size-3.5 shrink-0 text-quiet" />
            <span>
              Engine not connected — machine status is unknown, not fabricated.
              {!configured ? (
                <>
                  {" "}Set <code className="font-mono text-iris-soft">ENGINE_API_URL</code>.
                </>
              ) : null}
            </span>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-3">
      <dt className="w-20 shrink-0 text-[11px] font-medium uppercase tracking-[0.07em] text-quiet">{label}</dt>
      <dd className="min-w-0 text-[13px] leading-relaxed text-foreground">{value}</dd>
    </div>
  );
}

function Count({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="rounded-md border border-border/50 bg-surface-2/30 px-2.5 py-2 text-center">
      <div className="tabular text-lg font-semibold text-foreground">{value === null ? "—" : value}</div>
      <div className="text-[10px] uppercase tracking-wide text-quiet">{label}</div>
    </div>
  );
}
