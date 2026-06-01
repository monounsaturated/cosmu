import { redirect } from "next/navigation";

// The Farm surface moved into the unified Research route. Keep the old path working.
export default function FarmPage() {
  redirect("/research");
}
