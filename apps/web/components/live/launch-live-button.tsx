"use client";

// LaunchLiveButton — drop-in bento "Launch live" button that opens the LaunchLiveModal. Used from
// server-rendered pages (like /strategy/[id]) that need a client-side modal trigger. All modal logic lives
// in LaunchLiveModal; this is just the trigger + state wrapper.

import { useState } from "react";
import { LaunchLiveModal } from "./launch-live-modal";

interface Props {
  versionId: string;
  strategyName: string;
}

export function LaunchLiveButton({ versionId, strategyName }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className="btn btn-iris" onClick={() => setOpen(true)}>
        Launch live
      </button>
      {open ? (
        <LaunchLiveModal versionId={versionId} strategyName={strategyName} onClose={() => setOpen(false)} />
      ) : null}
    </>
  );
}
