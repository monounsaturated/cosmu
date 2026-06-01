import { redirect } from "next/navigation";

// Console was renamed to Steer (NL ops + ML asks; authoring moved to Claude Code / the Overview
// inbox). Keep the old path working.
export default function ConsolePage() {
  redirect("/steer");
}
