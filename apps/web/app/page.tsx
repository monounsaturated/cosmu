// module: / — the default landing. Per the v12 redesign the app opens on the LIVE dashboard
// (sidebar order Live · Paper · Strategies · Costs · Commands). Overview moved to /overview and is
// reachable from the sidebar's More section. A server redirect keeps one canonical home.

import { redirect } from "next/navigation";

export default function Home() {
  redirect("/live");
}
