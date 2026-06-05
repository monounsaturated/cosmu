import { redirect } from "next/navigation";

// Forward-test is no longer its own page — the lifecycle (lab → screened → forward → live → killed) is a
// `status` facet inside the unified Strategies leaderboard (docs/PRODUCT.md Epic B). Keep the path working.
export default function ForwardTestPage() {
  redirect("/strategies");
}
