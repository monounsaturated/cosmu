import { redirect } from "next/navigation";

// Research was renamed to Lab (the discovery surface). Keep the old path working.
export default function ResearchPage() {
  redirect("/lab");
}
