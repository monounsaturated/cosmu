// module: AiSummary — the v18 strat-sheet AI-summary block: a calm iris-tinted panel with an "AI summary"
// title and a model badge on the right, then the plain-language body. HONEST BY CONSTRUCTION:
//   • Body text comes ONLY from real recorded fields — the operator-agent summary (research_notes
//     kind='summary', served as summary_md). Nothing is generated here; absent → an honest empty line.
//   • The badge names the SOURCE. The detail contract carries no model id, so when summary_md is present
//     the badge reads "operator's agent"; the caller may pass an explicit `model` to override only when it
//     is a real recorded value. We never invent a model name.
//   • A "stale" pill shows when the recorded summary's facts moved since it was written.
//
// Advisory only — never the Gate. This narrates; the deterministic Gate alone funds or kills.

import { Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@/components/ui/tooltip";

export function AiSummary({
  summaryMd,
  stale,
  updatedAt,
  model
}: {
  summaryMd?: string | null;
  stale?: boolean | null;
  updatedAt?: string | null;
  // Real recorded model id, when the source provides one. Falls back to the honest source label.
  model?: string | null;
}) {
  const badge = model ?? "operator's agent";
  return (
    <section className="rounded-lg border border-iris/25 bg-iris/[0.05] p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-[12px] font-semibold text-iris-soft">
          <Sparkles className="size-3.5" aria-hidden /> AI summary
          <Tooltip content="A plain-language read written from this Version's recorded facts only — what it trades, the hypothesis, what the Gate decided, and the forward-test state. Advisory, not the Gate: the Gate alone funds or kills." />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="iris">{badge}</Badge>
          {stale ? <Badge variant="warn">stale — numbers changed since written</Badge> : null}
        </div>
      </div>
      {summaryMd ? (
        <div className="space-y-1.5">
          <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-muted">{summaryMd}</p>
          {updatedAt ? (
            <div className="text-[11px] text-quiet">
              written <time dateTime={updatedAt}>{new Date(updatedAt).toLocaleString("en-US")}</time>
            </div>
          ) : null}
        </div>
      ) : (
        <p className="text-[12.5px] leading-relaxed text-quiet">
          No summary yet — the operator&apos;s agent writes a plain-language read from this Version&apos;s recorded
          facts. It appears here once written; the engine never auto-generates it.
        </p>
      )}
    </section>
  );
}
