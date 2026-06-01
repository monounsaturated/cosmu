import { redirect } from "next/navigation";

// The Farm surface (Strategy Finder) moved into the unified Lab route. Keep the old path working.
export default function FarmPage() {
  redirect("/lab");
}
