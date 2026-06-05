import type { InboxQueueItem, InboxQueueResponse } from "@cosmu/contracts-ts";
import { getJson } from "./client";

// GET /lab/inbox — the operator's queued natural-language strategy ideas (newest first). Each stays
// "queued" until a scan turns its brief into a typed, gated spec, then flips to "imported". Honest empty
// when nothing has been dropped yet; never fabricated.
const emptyInboxQueue: InboxQueueResponse = { items: [], inbox_dir: "" };

export async function getInboxQueue(): Promise<{ items: InboxQueueItem[]; connected: boolean }> {
  const { data, connected } = await getJson<InboxQueueResponse>("/lab/inbox", emptyInboxQueue);
  return { items: data.items, connected };
}
