import type { LeaderboardRow } from "@cosmu/contracts-ts";
import { EmptyState } from "@/components/ui/honest-state";

// The Paper "Recent trades" card (Iris Bento `.card`, mirrors the mockup's tradesBox slot). The Paper surface
// fetches the leaderboard + the aggregate overview curve — NEITHER carries a per-FILL blotter across the cohort
// (Execution[] lives on the per-strategy detail endpoint, not at the aggregate). So rather than fabricate a fills
// feed, this renders an HONEST empty state and points the operator to the per-strategy sheet for the real blotter.
//
// HONESTY: nothing here is fabricated. When the engine ships an aggregate paper-fills feed, bind it here and
// render the `.mini-tbl`; until then the honest empty is the truth.
export function TrackLedger({ rows }: { rows: LeaderboardRow[] }) {
  const has = rows.length > 0;
  return (
    <div className="card dh">
      <div className="card-hdr">
        <span className="card-lbl">Recent trades</span>
      </div>
      <div className="card-body">
        <EmptyState
          title="No aggregate fill feed yet."
          hint={
            has
              ? "Paper fills are recorded per strategy — open a track from Open positions to see its real per-fill blotter. Nothing is fabricated at the cohort level."
              : "Once a funded track records its first fill, its blotter appears on that strategy's detail sheet. Nothing is shown here until then."
          }
        />
      </div>
    </div>
  );
}
