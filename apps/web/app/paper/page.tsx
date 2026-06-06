import { redirect } from "next/navigation";

// "Paper" (the old pooled wallet) was dropped for per-strategy tracks; the Simulation stage is now a
// `status` facet inside the unified Strategies leaderboard. Keep the old path working.
export default function PaperPage() {
  redirect("/strategies");
}
