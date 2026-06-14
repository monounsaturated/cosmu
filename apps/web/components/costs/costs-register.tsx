"use client";

// Costs register + the four clickable category tiles. The tiles are dynamic filters: clicking a category
// narrows the register to that category's sources (click again to clear). All four buckets always show
// (even at $0). The register itself is operator-editable — see useCostOverrides: amounts/budgets can be
// pinned and manual cost lines added (localStorage, this browser), so the page is a deterministic budget
// tool even where a supplier API can't report exact spend. Rows are computed server-side and passed in;
// overrides are layered on the client.

import { useState } from "react";
import { CategoryTiles, CardHead, RefreshedAt, foldTile, TILE_ORDER, type RegisterRow } from "./cost-sections";
import { EditableRegisterTable } from "./editable-register";
import { mergeOverrides, useCostOverrides } from "./cost-overrides";

export function CostsRegister({
  register,
  computedAt,
}: {
  register: RegisterRow[];
  computedAt: string;
}) {
  const [active, setActive] = useState<string | null>(null);
  const { ov, hasOverrides, editRow, resetRow, addRow, editManual, removeManual } = useCostOverrides();

  // Costs lists only things that actually COST money — free ($0) engine services are dropped (they belong
  // on Keys as data providers, not in the spend register). Operator-added/edited rows are kept regardless.
  const paid = register.filter((r) => (r.amount ?? 0) > 0 || r.range != null);

  // Layer operator overrides over the paid engine rows.
  const rows = mergeOverrides(paid, ov);

  // Tile totals + filtering come from the merged set, folded into the 4 buckets.
  const totals: Record<string, number> = { infra: 0, trading: 0, data: 0, ai: 0 };
  for (const r of rows) totals[foldTile(r.category)] += r.amount ?? 0;
  const tileCats = TILE_ORDER.map((c) => ({ category: c, amount: totals[c] }));

  const filtered = active ? rows.filter((r) => foldTile(r.category) === foldTile(active)) : rows;
  const pick = (cat: string) => setActive((prev) => (prev && foldTile(prev) === foldTile(cat) ? null : cat));

  return (
    <>
      <CategoryTiles categories={tileCats} active={active} onPick={pick} />
      <div className="card" style={{ marginBottom: "var(--gap)" }}>
        <CardHead
          label={`Cost register · ${filtered.length} source${filtered.length === 1 ? "" : "s"}${active ? ` · ${active}` : ""}`}
          aside={
            <span style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <RefreshedAt at={computedAt} />
              <button type="button" className="btn btn-xs" onClick={addRow} data-tip="Add a cost line the engine can't see">
                + Add cost
              </button>
            </span>
          }
        />
        <div className="card-body">
          <EditableRegisterTable
            rows={filtered}
            onEditAmount={(r, n) => editRow(r.vendor, { amount: n })}
            onEditBudget={(r, n) => editRow(r.vendor, { budget: n })}
            onReset={(r) => resetRow(r.vendor)}
            onEditManual={editManual}
            onRemoveManual={removeManual}
          />
          <div className="costs-note">
            {active ? (
              <>
                Filtered to <b style={{ color: "var(--fg)" }}>{active}</b> — click the tile again to clear.{" "}
              </>
            ) : null}
            Live figures are fetched from each provider&apos;s billing API; <code>actual</code> rows are
            engine-reported real spend vs budget; the rest are clearly-labelled plan-tier estimates. Click any
            Amount or Budget to <b style={{ color: "var(--fg)" }}>set</b> a figure the API can&apos;t give you,
            or <b style={{ color: "var(--fg)" }}>+ Add cost</b> for a line the engine can&apos;t see —{" "}
            <code>set</code> rows are operator-entered and saved in this browser. Nothing here is fabricated.
            {hasOverrides ? <span className="iris"> · overrides active</span> : null}
          </div>
        </div>
      </div>
    </>
  );
}
