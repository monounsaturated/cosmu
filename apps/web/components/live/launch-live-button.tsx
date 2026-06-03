"use client";

// module: LaunchLiveButton — drop-in "Launch live" button that opens the LaunchLiveModal.
// Used from server-rendered pages (like /strategy/[id]) that need a client-side modal trigger.
// All modal logic lives in LaunchLiveModal; this is just the trigger + state wrapper.

import { useState } from "react";
import { Rocket } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LaunchLiveModal } from "./launch-live-modal";

interface Props {
  versionId: string;
  strategyName: string;
}

export function LaunchLiveButton({ versionId, strategyName }: Props) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="primary" size="md" onClick={() => setOpen(true)}>
        <Rocket className="size-4" /> Launch live
      </Button>
      {open ? (
        <LaunchLiveModal
          versionId={versionId}
          strategyName={strategyName}
          onClose={() => setOpen(false)}
        />
      ) : null}
    </>
  );
}
