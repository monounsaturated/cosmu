import { redirect } from "next/navigation";

// Scores fold into Mind (scores are first-class, rendered in the committee surface — docs/PRODUCT.md E2).
// Keep the old path working.
export default function ScoresPage() {
  redirect("/mind");
}
