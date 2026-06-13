// module: / — the default landing. Per the v18 redesign the app opens on the STRATEGIES screener
// (sidebar order Strategies · Paper · Live · Costs · Keys · Commands). A server redirect keeps one
// canonical home. The folded surfaces (overview/console/lab/…) redirect here via next.config.ts.

import { redirect } from "next/navigation";

export default function Home() {
  redirect("/strategies");
}
