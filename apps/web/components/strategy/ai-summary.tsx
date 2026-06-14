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
  model,
  specRationale
}: {
  summaryMd?: string | null;
  stale?: boolean | null;
  updatedAt?: string | null;
  // Real recorded model id, when the source provides one. Falls back to the honest source label.
  model?: string | null;
  // The strategy's OWN plain-language rationale (a real recorded spec field — what it trades + why the edge
  // exists). Honest fallback when no operator summary is written yet, so every strategy explains itself in
  // plain words instead of "no summary yet". Not generated here; lifted verbatim from the spec.
  specRationale?: string | null;
}) {
  // Prefer the operator-agent summary; else fall back to the spec's own rationale. The badge names the real
  // source so the reader always knows where the text came from — never invented.
  const rationale = specRationale?.trim() || null;
  const usingRationale = !summaryMd && Boolean(rationale);
  const badge = model ?? (usingRationale ? "from the spec" : "operator's agent");
  return (
    <div className="psec ai-sec">
      <div className="ai-head">
        <span
          className="ai-title"
          data-tip="What this strategy does, in plain words — what it trades and why the edge should exist. Prefers the operator's agent write-up; otherwise the strategy's own recorded rationale. Advisory, not the Gate."
        >
          What this does
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
      ) : usingRationale ? (
        <p className="ai-body" style={{ whiteSpace: "pre-wrap" }}>{rationale}</p>
      ) : (
        <p className="ai-body quiet">
          No description yet — the operator&apos;s agent writes a plain-language read from this Version&apos;s recorded facts.
          It appears here once written; the engine never auto-generates it.
        </p>
      )}
    </div>
  );
}
