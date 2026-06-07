"use client";

// module: thin wrapper around the shared idea-intake component, kept so the Lab's existing
// `import { IdeaInbox } from "@/components/overview/idea-inbox"` continues to resolve unchanged.
// The real implementation lives in ./idea-intake (the ONE intake shared by Overview + Lab); this
// just renders it in the full-card "vibe loop" variant the Lab expects.

import type { InboxQueueItem } from "@cosmu/contracts-ts";
import { IdeaIntake } from "./idea-intake";

export function IdeaInbox({
  initial,
  connected,
  configured
}: {
  initial: InboxQueueItem[];
  connected: boolean;
  configured: boolean;
}) {
  return <IdeaIntake variant="card" initial={initial} connected={connected} configured={configured} />;
}
