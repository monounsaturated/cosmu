// Overview — machine status + thesis verdict ledger + idea input.
// Three panels on one page. No fabricated numbers; honest offline states throughout.

import { CheckCircle, XCircle, Clock, AlertCircle, Lightbulb } from "lucide-react";
import { engineConfigured, getAutonomyStatus, getVerdicts } from "./data";
import type { VerdictItem } from "./data";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { NotConnected } from "@/components/ui/honest-state";
import { IdeaInput } from "@/components/overview/idea-input";
import { cn, timeAgo } from "@/lib/utils";

export default async function OverviewPage() {
  const [{ status, connected: machineConnected }, { verdicts, connected: verdictsConnected }] =
    await Promise.all([getAutonomyStatus(), getVerdicts()]);

  return (
    <div className="mx-auto max-w-[980px] space-y-5 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">overview</div>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">What is the machine doing?</h1>
      </div>

      {/* Machine status */}
      <Card>
        <CardHeader>
          <CardTitle>Machine status</CardTitle>
        </CardHeader>
        <CardContent>
          {!machineConnected ? (
            <NotConnected
              configured={engineConfigured}
              what="Machine status shows whether the autonomous loop is ticking or idle, and when it last ran."
            />
          ) : (
            <div className="flex flex-wrap gap-x-8 gap-y-3">
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "inline-flex size-2.5 rounded-full",
                    status.running ? "animate-pulse bg-up" : "bg-quiet/60"
                  )}
                />
                <span className="text-[14px] font-medium text-foreground">
                  {status.running ? "Ticking" : status.paused ? "Paused" : "Idle"}
                </span>
              </div>
              <div className="text-[13px] text-muted">
                <span className="text-quiet">Last tick</span>{" "}
                {status.last_tick_at ? (
                  <span className="font-medium text-foreground">{timeAgo(status.last_tick_at)}</span>
                ) : (
                  <span className="text-quiet">never</span>
                )}
              </div>
              <div className="text-[13px] text-muted">
                <span className="text-quiet">Cycles</span>{" "}
                <span className="font-medium text-foreground tabular">{status.cycles_run}</span>
              </div>
              {status.last_action ? (
                <div className="text-[13px] text-muted">
                  <span className="text-quiet">Last action</span>{" "}
                  <span className="text-foreground">{status.last_action}</span>
                </div>
              ) : null}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Verdict ledger */}
      <Card>
        <CardHeader>
          <CardTitle>Phase-0 thesis verdicts</CardTitle>
        </CardHeader>
        <CardContent>
          {!verdictsConnected || verdicts.length === 0 ? (
            <p className="py-2 text-[13px] text-quiet">
              {!verdictsConnected
                ? "Engine not connected — verdicts are read from docs/reports/ via the engine."
                : "No verdict reports found in docs/reports/."}
            </p>
          ) : (
            <ul className="divide-y divide-border/50">
              {verdicts.map((v) => (
                <VerdictRow key={v.id} v={v} />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* Idea input */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            <Lightbulb className="size-4 text-iris-soft" /> Drop an idea
          </CardTitle>
        </CardHeader>
        <CardContent>
          <IdeaInput />
        </CardContent>
      </Card>
    </div>
  );
}

function VerdictRow({ v }: { v: VerdictItem }) {
  const isPass = v.verdict === "PASS";
  const isFail = v.verdict === "FAIL";
  const isPending = v.verdict === "pending";
  const Icon = isPass ? CheckCircle : isFail ? XCircle : isPending ? Clock : AlertCircle;
  const iconClass = isPass ? "text-up" : isFail ? "text-down" : "text-quiet";
  const badgeVariant: "up" | "down" | "muted" = isPass ? "up" : isFail ? "down" : "muted";

  return (
    <li className="flex flex-col gap-1 py-3 sm:flex-row sm:items-center sm:gap-4">
      <div className="flex min-w-[160px] items-center gap-2 shrink-0">
        <Icon className={cn("size-4 shrink-0", iconClass)} />
        <span className="text-[13.5px] font-medium text-foreground">{v.name}</span>
      </div>
      <Badge variant={badgeVariant} className="self-start sm:self-auto">
        {v.verdict}
      </Badge>
      {v.reason ? (
        <span className="text-[12.5px] leading-snug text-muted">{v.reason}</span>
      ) : null}
    </li>
  );
}
