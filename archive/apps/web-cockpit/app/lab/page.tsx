// Lab has been FOLDED into Strategies — there is now ONE granular surface showing every (algo × asset × venue)
// triplet (never pooled), so the separate per-symbol Lab page is gone. This route stays only as a permanent
// redirect so any existing bookmark / deep link lands on the merged surface instead of 404-ing.

import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

export default function LabPage() {
  redirect("/strategies");
}
