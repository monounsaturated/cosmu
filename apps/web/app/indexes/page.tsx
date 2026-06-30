// Indexes — REMOVED. We scrapped the Index strategy type: an "index" is just DATA an LLM strategy reads,
// never its own page/type. The nav entry is gone; this route now permanently redirects to /strategies so
// stale deep links never 404. (The old indexes registry UI + IndexesTable were retired with this change.)

import { redirect } from "next/navigation";

export default function IndexesPage() {
  redirect("/strategies");
}
