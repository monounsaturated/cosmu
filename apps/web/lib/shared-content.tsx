import type { ReactNode } from "react";

export const TRACK_VS_AGGREGATE: ReactNode = (
  <div className="space-y-1.5">
    <p>
      <span className="font-semibold text-foreground">Per strategy</span> — each survivor proves itself on its own
      forward-test track, judged in net-of-fee %. There is no pooled wallet.
    </p>
    <p>
      <span className="font-semibold text-foreground">Net across forward-tests</span> — the combined net of every
      strategy currently forward-testing. An aggregate read-out, not an account you trade from.
    </p>
  </div>
);
