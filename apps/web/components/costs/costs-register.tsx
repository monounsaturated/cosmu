"use client";

// Costs register + the four clickable category tiles. The tiles are dynamic filters: clicking a category
// narrows the register to that category's sources (click again to clear). All four buckets always show
// (even at $0). Client-only state; the rows are computed server-side and passed in.

import { useState } from "react";
import { CategoryTiles, RegisterTable, CardHead, RefreshedAt, foldTile, TILE_ORDER, type RegisterRow } from "./cost-sections";

export function CostsRegister({
  register,
  computedAt,
}: {
  register: RegisterRow[];
  computedAt: string;
}) {
  const [active, setActive] = useState<string | null>(null);

  // Tile totals come from the register itself (so they include supplier billing), folded into the 4 buckets.
  const totals: Record<string, number> = { infra: 0, trading: 0, data: 0, ai: 0 };
  for (const r of register) totals[foldTile(r.category)] += r.amount ?? 0;
  const tileCats = TILE_ORDER.map((c) => ({ category: c, amount: totals[c] }));

  const filtered = active ? register.filter((r) => foldTile(r.category) === foldTile(active)) : register;
  const pick = (cat: string) => setActive((prev) => (prev && foldTile(prev) === foldTile(cat) ? null : cat));

  return (
    <>
      <CategoryTiles categories={tileCats} active={active} onPick={pick} />
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
