// Overview — the landing page. In one glance it answers: (a) is the machine running, and in what mode
// (Sim/Live) — with its last tick; (b) the verdict ledger — every thesis tested, PASS or FAIL; (c) a place
// to dump a new idea (text → POST /lab/inbox) and see the queue status so the vibe loop is visible.
// HONEST: when the engine is unreachable we render a single "not connected" state and never fabricate.

import { Activity, ArrowRight, ClipboardCheck, FlaskConical, Pause, Play } from "lucide-react";
import Link from "next/link";
import { engineConfigured, getAutonomyStatus, getVerdicts, getInboxQueue } from "./data";
import type { VerdictRow } from "./data";
import type { InboxQueueItem } from "@cosmu/contracts-ts";
import { IdeaDumpBox } from "./idea-dump-box";
import { NotConnected, EmptyState } from "@/components/ui/honest-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { DataPreview } from "@/components/ui/data-preview";
import { cn, timeAgo } from "@/lib/utils";

export default async function OverviewPage() {
  const [
    { status, connected: statusConnected },
    { verdicts, connected: verdictsConnected },
    { items: inboxItems, connected: inboxConnected }
  ] = await Promise.all([
    getAutonomyStatus(),
    getVerdicts(),
    getInboxQueue()
  ]);
  const connected = statusConnected || verdictsConnected;

  if (!connected) {
    return (
      <div className="mx-auto max-w-[1100px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
        <Header />
        <NotConnected
          configured={engineConfigured}
          what="The Overview shows the machine's status and the verdict ledger — every thesis tested, PASS or FAIL. Connect the engine to see real status; nothing is fabricated."
        />
      </div>
    );
  }

  // Coerce to a safe array — an older engine shape (or an offline verdicts read) must never crash render.
  const rows: VerdictRow[] = verdicts.rows ?? [];

  return (
    <div className="mx-auto max-w-[1100px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
      <Header />

      <MachineStatus status={status} connected={statusConnected} />

      {/* Dump a new idea + queue snapshot — the vibe loop entry point.
          Queue shows queued → imported status so the operator knows what the next tick will see. */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            <FlaskConical className="size-4 text-iris-soft" /> Dump an idea
          </CardTitle>
          <span className="text-[12px] text-quiet">Queued as prose → next tick authors a typed spec → Gate decides</span>
        </CardHeader>
        <CardContent className="space-y-4">
          <IdeaDumpBox />
          <IdeaQueuePreview items={inboxItems} connected={inboxConnected} />
        </CardContent>
      </Card>

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
  const modeLabel = status.live_enabled ? "Live" : "Simulation";
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

// The verdict ledger preview — top 5 most-recent verdicts + "View all" link to /verdicts.
// Full sortable + filterable table lives at /verdicts.
const PREVIEW_N = 5;

function VerdictLedger({ rows, connected }: { rows: VerdictRow[]; connected: boolean }) {
  const preview = rows.slice(0, PREVIEW_N);
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
          <DataPreview href="/verdicts" viewAllLabel="View all verdicts" total={rows.length}>
            <ul className="divide-y divide-border/60">
              {preview.map((r) => {
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
          </DataPreview>
        )}
      </CardContent>
    </Card>
  );
}

// Compact snapshot of the idea queue — queued (waiting for next tick to author a spec) or imported
// (already turned into a typed StrategySpec, now flowing through Backtest → Gate). Server-rendered
// so the operator sees the real queue state on page load. No optimistic rows; never fabricated.
function IdeaQueuePreview({ items, connected }: { items: InboxQueueItem[]; connected: boolean }) {
  if (!connected || items.length === 0) return null;
  return (
    <div className="border-t border-border/50 pt-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.1em] text-quiet">
          Queue — {items.length} idea{items.length === 1 ? "" : "s"}
        </span>
        <Link href="/lab" className="flex items-center gap-1 text-[11px] text-iris-soft hover:underline">
          See full Lab <ArrowRight className="size-3" />
        </Link>
      </div>
      <ul className="space-y-1.5">
        {items.slice(0, 4).map((item) => (
          <li
            key={item.filename}
            className="flex items-center justify-between gap-3 rounded-md border border-border/50 bg-surface-2/30 px-3 py-2"
          >
            <span className="min-w-0 truncate text-[12.5px] text-foreground">{item.name}</span>
            <span className="flex shrink-0 items-center gap-2">
              <span className="text-[11px] text-quiet">{timeAgo(item.ts) ?? ""}</span>
              <Badge variant={item.status === "imported" ? "up" : "info"}>{item.status}</Badge>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
