// /costs/ledger — folded into the main Costs surface. The v18 IA declutter merged the standalone
// "full ledger" drill-down into the Costs page itself: the bento Cost register card there already lists
// EVERY real cost source (supplier billing + engine infra lines + vendor actuals) in one sortable place,
// so a separate ledger route would just duplicate it. We redirect rather than show a near-identical view.
//
// (This permanently retires the old shadcn ledger tables — `infra-table.tsx` / `supplier-table.tsx` in
// this directory — which depended on now-deleted primitives. They are no longer imported.)

import { redirect } from "next/navigation";

export default function CostsLedgerPage() {
  redirect("/costs");
}
