// RETIRED surface. The "Mind" voice-scoreboard (off /mind/credibility, written by the now-quarantined autonomous
// voices pass) was replaced by the lean AUTHORITY dashboard — proprietary data scored from whether accounts'
// past asset calls corroborated the tape. Kept as a permanent redirect so any bookmark / inbound link lands on
// the replacement instead of a dead route.

import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

export default function MindPage() {
  redirect("/authority");
}
