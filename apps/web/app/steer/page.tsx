import { redirect } from "next/navigation";

// Steer folded into the Console (the control surface — decide · steer · arm). Keep the old path working.
export default function SteerPage() {
  redirect("/console");
}
