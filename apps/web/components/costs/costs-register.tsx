"use client";

// Costs register + clickable category tiles. The tiles are dynamic filters: clicking a category narrows
// the register to that category's sources (click again to clear). Client-only state; the rows themselves
// are computed server-side and passed in (no engine call here).

import { useState } from "react";
import type { CostByCategory } from "@cosmu/contracts-ts";
import { CategoryTiles, RegisterTable, CardHead, RefreshedAt, type RegisterRow } from "./cost-sections";

// Fold the register's category vocab (infra/ci/data/trading/llm/ai) onto the four tile buckets so a tile
// click filters the matching register rows.
const FOLD: Record<string, string> = { infra: "infra", ci: "infra", data: "data", trading: "trading", llm: "ai", ai: "ai" };
const fold = (c: string) => FOLD[c.toLowerCase()] ?? c.toLowerCase();

export function CostsRegister({
  categories,
  register,
  computedAt,
}: {
  categories: CostByCategory[];
  register: RegisterRow[];
  computedAt: string;
}) {
  const [active, setActive] = useState<string | null>(null);
  const filtered = active ? register.filter((r) => fold(r.category) === fold(active)) : register;
  const pick = (cat: string) => setActive((prev) => (prev && fold(prev) === fold(cat) ? null : cat));
  const hasCats = categories.some((c) => c.amount > 0);

  return (
    <>
      {hasCats ? <CategoryTiles categories={categories} active={active} onPick={pick} /> : null}
      <div className="card" style={{ marginBottom: "var(--gap)" }}>
        <CardHead
          label={`Cost register · ${filtered.length} source${filtered.length === 1 ? "" : "s"}${active ? ` · ${active}` : ""}`}
          aside={<RefreshedAt at={computedAt} />}
        />
        <div className="card-body">
          <RegisterTable rows={filtered} />
          <div className="costs-note">
            {active ? (
              <>
                Filtered to <b style={{ color: "var(--fg)" }}>{active}</b> — click the tile again to clear.{" "}
              </>
            ) : null}
            Live figures are fetched from each provider&apos;s billing API; <code>actual</code> rows are
            engine-reported real spend vs budget; the rest are clearly-labelled plan-tier estimates. Headroom
            is shown only where a real budget cap exists. Nothing here is fabricated.
          </div>
        </div>
      </div>
    </>
  );
}
