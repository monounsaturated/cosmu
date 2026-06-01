// module: honest empty/connect states. The product NEVER fabricates a track record. When a surface
// has no real engine data it shows one of two honest states instead of numbers:
//   <NotConnected/> — the engine is unreachable. Tells the operator EXACTLY what to set.
//   <EmptyState/>   — the engine IS connected but has nothing yet (no survivors, no trades, …).
// Both are deliberately calm and informative, never alarmist and never a "demo".

import type { ReactNode } from "react";
import { PlugZap, Inbox } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

// Shown when ENGINE_API_URL is unset or the engine fetch failed. `configured` distinguishes
// "you haven't pointed the app at an engine" from "the engine is down right now".
export function NotConnected({ configured = false, what }: { configured?: boolean; what?: ReactNode }) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
        <div className="flex size-11 items-center justify-center rounded-full border border-border/70 bg-surface-2/50 text-quiet">
          <PlugZap className="size-5" />
        </div>
        <div className="space-y-1">
          <div className="text-[14px] font-medium text-foreground">Engine not connected</div>
          <p className="mx-auto max-w-md text-[12.5px] leading-relaxed text-muted">
            {what ?? "This surface shows real engine data. Nothing is fabricated here."}
          </p>
        </div>
        {!configured ? (
          <code className="rounded-md border border-border/70 bg-background/60 px-2.5 py-1.5 font-mono text-[11.5px] text-iris-soft">
            set ENGINE_API_URL to your engine
          </code>
        ) : (
          <p className="text-[11.5px] text-quiet">The engine is configured but did not respond. Once it is up, real data appears here.</p>
        )}
      </CardContent>
    </Card>
  );
}

// Shown when the engine is connected but the answer is genuinely empty (no data yet).
export function EmptyState({
  title,
  hint,
  icon
}: {
  title: string;
  hint?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
      <div className="text-quiet">{icon ?? <Inbox className="size-5" />}</div>
      <div className="text-[13px] text-muted">{title}</div>
      {hint ? <div className="mx-auto max-w-md text-[11.5px] leading-relaxed text-quiet">{hint}</div> : null}
    </div>
  );
}

// A slim inline banner for the top of a surface when not connected, so the rest of the page can
// still render its own honest empty sub-states underneath.
export function NotConnectedBanner({ configured = false }: { configured?: boolean }) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-border/70 bg-surface-2/40 px-3 py-2 text-[12px] text-muted">
      <PlugZap className="size-3.5 shrink-0 text-quiet" />
      <span>
        Engine not connected — showing honest empty states, not fabricated numbers.
        {!configured ? (
          <>
            {" "}Set <code className="font-mono text-iris-soft">ENGINE_API_URL</code>.
          </>
        ) : null}
      </span>
    </div>
  );
}
