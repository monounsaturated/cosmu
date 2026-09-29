// Social — the canonical display name of the social-authority lane. The underlying route is /mind (kept so
// existing deep links survive); this /social alias redirects there so the new name also resolves. One lane,
// one page, under the single name "Social".

import { redirect } from "next/navigation";

export default function SocialPage() {
  redirect("/mind");
}
