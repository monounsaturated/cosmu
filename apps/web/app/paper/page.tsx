import { redirect } from "next/navigation";

// "Paper" (the pooled paper Wallet) was dropped in favour of per-strategy Forward-test — each
// survivor proves itself on its own track, no pooled wallet. Keep the old path working.
export default function PaperPage() {
  redirect("/forward-test");
}
