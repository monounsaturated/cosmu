// Index detail — REMOVED with the Index strategy type (see ../page.tsx). This route now redirects to
// /strategies so any stale per-index deep link resolves cleanly instead of 404-ing.

import { redirect } from "next/navigation";

export default async function IndexDetailPage({ params }: { params: Promise<{ id: string }> }) {
  // Await params to satisfy the Next.js async-params contract, then redirect (the id is intentionally unused).
  await params;
  redirect("/strategies");
}
