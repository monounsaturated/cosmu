"use client";

// Costs boards — the headline stat strip, the four clickable category tiles, and the read-only
// subscriptions register they filter. All three share ONE filter state: click the "Other" headline box
// or any tile to narrow the table to that category; click again to clear.
//
// The register is a READ-ONLY mirror of the code-maintained cost register (apps/web/app/data/cost-register.ts)
// — costs are edited in code, not the browser, so there is no Edit button, no override layer and no Refresh
// column. The "Other" box replaces the old "AI spend" stat (redundant with the AI/LLM tile) and surfaces the
// catch-all category (e.g. Partnerships) that has no tile of its own.

import { useState } from "react";
import { CategoryTiles, CardHead, StatStrip, catKey, type StatCell } from "./cost-sections";
import { SubscriptionsTable } from "./subscriptions-table";
import { costTotals, type CostLine } from "@/app/data/cost-register";
import { formatUsd } from "@/lib/utils";

export function CostsRegister({
  rows,
  vsEquity,
}: {
  rows: CostLine[];
  /** opex / equity %, from the engine — honest "—" (null) when no equity figure exists. */
  vsEquity: number | null;
}) {
  const [active, setActive] = useState<string | null>(null);
  const { totalSpend, runRate, otherSpend, byCategory } = costTotals(rows);

  const pick = (cat: string) => setActive((prev) => (prev && catKey(prev) === catKey(cat) ? null : cat));
  const otherActive = active != null && catKey(active) === "other";

  const cells: StatCell[] = [
    { label: "Total spend", value: formatUsd(totalSpend), sub: "spent to date" },
    { label: "Run-rate", value: formatUsd(runRate), sub: "recurring · /mo" },
    {
      label: "vs equity",
      value: vsEquity === null ? "—" : `${vsEquity.toFixed(1)}%`,
      sub: vsEquity === null ? "needs equity" : "opex / equity",
      tone: vsEquity !== null && vsEquity <= 2 ? "up" : vsEquity !== null && vsEquity > 10 ? "dn" : undefined,
    },
    { label: "Other", value: formatUsd(otherSpend), sub: "non-tool spend", onClick: () => pick("other"), active: otherActive },
  ];

  const filtered = active ? rows.filter((r) => catKey(r.category) === catKey(active)) : rows;

  return (
    <>
      <StatStrip cells={cells} />
      <CategoryTiles categories={byCategory} active={active} onPick={pick} />
      <div className="card" style={{ marginBottom: "var(--gap)" }}>
        <CardHead
          label={`Subscriptions & renewals${active ? ` · ${active} only — click again to clear` : ""}`}
          aside={<span className="quiet" style={{ fontSize: 11 }}>{rows.length} sources · maintained in code</span>}
        />
        <div className="card-body">
          <SubscriptionsTable rows={filtered} />
        </div>
      </div>
    </>
  );
}
