// module: AiSummary — the v18 strat-sheet AI-summary block (Iris Bento `.psec.ai-sec` → `.ai-head` with
// an `.ai-title` + a model `.ai-badge`, then the plain-language `.ai-body`). HONEST BY CONSTRUCTION:
//   • Body text comes ONLY from a real recorded field — the operator-agent summary (research_notes
//     kind='summary', served as summary_md). Nothing is generated here; absent → an honest empty line.
//   • The badge names the SOURCE. The detail contract carries no model id, so when summary_md is present
//     the badge reads "operator's agent"; the caller may pass an explicit `model` to override only when it
//     is a real recorded value. We never invent a model name.
//   • A "stale" pill shows when the recorded summary's facts moved since it was written.
//
// Advisory only — never the Gate. This narrates; the deterministic Gate alone funds or kills.

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
    <div className="psec ai-sec">
      <div className="ai-head">
        <span
          className="ai-title"
          data-tip="A plain-language read written from this Version's recorded facts only — what it trades, the hypothesis, what the Gate decided, and the forward-test state. Advisory, not the Gate."
        >
          AI summary
        </span>
        <span className="ai-badge">{badge}</span>
        {stale ? <span className="ai-badge" style={{ color: "var(--gold)", borderColor: "oklch(0.82 0.14 85 / 0.32)" }}>stale — facts changed</span> : null}
      </div>
      {summaryMd ? (
        <>
          <p className="ai-body" style={{ whiteSpace: "pre-wrap" }}>{summaryMd}</p>
          {updatedAt ? (
            <div className="quiet" style={{ fontSize: 9.5, marginTop: 5 }}>
              written <time dateTime={updatedAt}>{new Date(updatedAt).toLocaleString("en-US")}</time>
            </div>
          ) : null}
        </>
      ) : (
        <p className="ai-body quiet">
          No summary yet — the operator&apos;s agent writes a plain-language read from this Version&apos;s recorded facts.
          It appears here once written; the engine never auto-generates it.
        </p>
      )}
    </div>
  );
}
