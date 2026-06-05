// Overview — the landing page. This is NOT a fund dashboard (there is no money yet). In one glance it
// answers three things: (a) is the machine running, and in what mode (Sim/Live) — with its last tick;
// (b) the idea inbox — queue a vibe, it becomes a typed, gated spec next tick, showing queued→imported
// status; (c) the verdict ledger — every thesis tested, PASS or FAIL, from GET /verdicts.
// HONEST: all sections handle engine-unreachable gracefully and never fabricate a status or verdict.

import { Activity, ClipboardCheck, Pause, Play } from "lucide-react";
import { engineConfigured, getAutonomyStatus, getVerdicts, getInboxQueue } from "./data";
import type { VerdictRow } from "./data";
import { IdeaInbox } from "@/components/overview/idea-inbox";
import { NotConnectedBanner, EmptyState } from "@/components/ui/honest-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn, timeAgo } from "@/lib/utils";

export default async function OverviewPage() {
  const [
    { status, connected: statusConnected },
    { verdicts, connected: verdictsConnected },
    { items: queueItems, connected: queueConnected }
  ] = await Promise.all([
    getAutonomyStatus(),
    getVerdicts(),
    getInboxQueue()
  ]);
  const connected = statusConnected || verdictsConnected;

  // Coerce to safe arrays — an older engine shape must never crash render.
  const rows: VerdictRow[] = verdicts.rows ?? [];
  const inbox = queueItems ?? [];

  return (
    <div className="mx-auto max-w-[1100px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
      <Header />

      {!connected && (
        <NotConnectedBanner configured={engineConfigured} />
      )}

      <MachineStatus status={status} connected={statusConnected} />

      {/* Idea inbox — queue a vibe; next tick turns it into a typed, gated spec. Handles offline itself. */}
      <IdeaInbox initial={inbox} connected={queueConnected} configured={engineConfigured} />

      {/* The verdict ledger — every thesis tested, PASS or FAIL. */}
      <VerdictLedger rows={rows} connected={verdictsConnected} />
    </div>
  );
}

function Header() {
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">overview</div>
      <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">The machine</h1>
      <p className="mt-1 text-[13px] text-muted">Status, the verdict ledger, and where you feed it ideas. No money yet — this is the lab read-out.</p>
    </div>
  );
}

// Machine status — is it running, in what mode (Sim/Live), and when did it last tick.
function MachineStatus({
  status,
  connected
}: {
  status: Awaited<ReturnType<typeof getAutonomyStatus>>["status"];
  connected: boolean;
}) {
  const running = connected && status.running && !status.paused;
  const stateLabel = !connected ? "Unknown" : status.paused ? "Paused" : status.running ? "Running" : "Idle";
  const stateVariant = running ? "up" : status.paused ? "warn" : "muted";
  const modeLabel = status.live_enabled ? "Live" : "Sim";
  const lastTick = timeAgo(status.last_tick_at);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <Activity className="size-4 text-iris-soft" /> Machine status
        </CardTitle>
        <div className="flex items-center gap-1.5">
          <Badge variant={stateVariant}>
            {running ? <Play className="size-3" /> : status.paused ? <Pause className="size-3" /> : null}
            {stateLabel}
          </Badge>
          <Badge variant={status.live_enabled ? "info" : "muted"}>{modeLabel}</Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
          <Field label="Mode" value={modeLabel} />
          <Field label="Last tick" value={lastTick ?? "—"} />
          <Field label="Cycles run" value={connected ? String(status.cycles_run) : "—"} />
        </div>
        {connected && status.next_action ? (
          <p className="mt-4 text-[12px] text-muted">
            <span className="text-quiet">Next: </span>
            {status.next_action}
          </p>
        ) : null}
        {!connected ? (
          <p className="mt-4 text-[12px] text-quiet">Status unknown — the engine did not report. The verdict ledger below is read from disk.</p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] font-medium uppercase tracking-[0.07em] text-quiet">{label}</div>
      <div className="mt-1 text-[15px] font-semibold tabular text-foreground">{value}</div>
    </div>
  );
}

const VERDICT_STYLE: Record<VerdictRow["status"], { label: string; variant: "up" | "down" | "warn" | "muted" }> = {
  PASS: { label: "PASS", variant: "up" },
  FAIL: { label: "FAIL", variant: "down" },
  "INSUFFICIENT-DATA": { label: "Insufficient data", variant: "warn" },
  "DATA-BLOCKED": { label: "Data-blocked", variant: "muted" }
};

// The verdict ledger — every pre-registered thesis the Gate has ruled on, PASS or FAIL. Read off
// docs/reports/phase0-*-verdict.md by the engine; honest empty when nothing has been ruled on yet.
function VerdictLedger({ rows, connected }: { rows: VerdictRow[]; connected: boolean }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-1.5">
          <ClipboardCheck className="size-4 text-iris-soft" /> Verdict ledger
        </CardTitle>
        <span className="text-[12px] text-quiet">{rows.length} thesis{rows.length === 1 ? "" : "es"} tested</span>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <EmptyState
            title={connected ? "No verdicts yet" : "Verdicts unavailable"}
            hint={
              connected
                ? "Every pre-registered thesis appears here once the Gate rules on it — PASS or FAIL. Nothing is fabricated."
                : "The engine did not return the ledger. Once it is up, real verdicts appear here."
            }
            icon={<ClipboardCheck className="size-5" />}
          />
        ) : (
          <ul className="divide-y divide-border/60">
            {rows.map((r) => {
              const style = VERDICT_STYLE[r.status] ?? VERDICT_STYLE.FAIL;
              return (
                <li key={r.slug} className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1.5 py-3 first:pt-0 last:pb-0">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[13.5px] font-medium text-foreground">{r.thesis}</span>
                      {r.date ? <span className="text-[11px] text-quiet">{r.date}</span> : null}
                    </div>
                    {r.reason ? <p className="mt-0.5 text-[12px] leading-relaxed text-muted">{r.reason}</p> : null}
                  </div>
                  <Badge variant={style.variant} className={cn("mt-0.5 shrink-0")}>
                    {style.label}
                  </Badge>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
