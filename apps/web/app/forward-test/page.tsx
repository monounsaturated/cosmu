// module: legacy route — the stage formerly at this URL is now called Paper (vocabulary rename 2026-06-11).
import { redirect } from "next/navigation";

export default function LegacyForwardTestRedirect() {
  redirect("/paper");
}
