"use client";

// Costs subscriptions register + the four clickable category tiles (v18 "Subscriptions & renewals").
// Tiles are dynamic filters (click a category to narrow; click again to clear). The table is the
// operator-editable subscriptions ledger — see useCostOverrides: the /mo seed is the engine's real billing
// figure; cadence, the renewal calendar and lifetime are pinned by the operator (localStorage), and
// /mo + proj/yr compute live. Rows are computed server-side and passed in as the cost register; we map
// them to the subscriptions vocabulary and layer overrides on the client.

import { useState } from "react";
import { CategoryTiles, CardHead, RefreshedAt, foldTile, TILE_ORDER, type RegisterRow } from "./cost-sections";
import { SubscriptionsTable } from "./subscriptions-table";
import { mergeSubs, useCostOverrides, type Cadence, type SubSeed } from "./cost-overrides";

// Map an engine register row to the subscriptions vocabulary. Cadence is a best-effort default the
// operator can override; the /mo figure is the engine's real amount.
function seedCadence(r: RegisterRow): Cadence {
  const v = r.vendor.toLowerCase();
  if (foldTile(r.category) === "trading") return "perfill";
  if (v.includes("openrouter")) return "usage";
  if (v.includes("anthropic") || v.includes("claude")) return "flat";
  return "monthly";
}

function toSeed(r: RegisterRow): SubSeed {
  return {
    source: r.vendor,
    cat: foldTile(r.category),
    cadence: seedCadence(r),
    perMo: r.amount,
    note: r.note ?? null,
    origin: r.source,
  };
}

export function CostsRegister({
  register,
  computedAt,
}: {
  register: RegisterRow[];
  computedAt: string;
}) {
  const [active, setActive] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);  // view ↔ Excel-like edit mode for the truth source
  const { ov, hasOverrides, editRow, resetRow, addRow, editManual, removeManual } = useCostOverrides();

  // Seed the subscriptions from the full engine register — unlike a spend-only register, a subscriptions
  // tracker shows $0/free services too (you still track when they renew), exactly like v18.
  const seeds = register.map(toSeed);
  const rows = mergeSubs(seeds, ov);

  // Tile totals (/mo per category) + filtering come from the merged set.
  const totals: Record<string, number> = { infra: 0, trading: 0, data: 0, ai: 0 };
  for (const r of rows) totals[foldTile(r.cat)] += r.perMo ?? 0;
  const tileCats = TILE_ORDER.map((c) => ({ category: c, amount: totals[c] }));

  const filtered = active ? rows.filter((r) => foldTile(r.cat) === foldTile(active)) : rows;
  const pick = (cat: string) => setActive((prev) => (prev && foldTile(prev) === foldTile(cat) ? null : cat));

  return (
    <>
      <CategoryTiles categories={tileCats} active={active} onPick={pick} />
      <div className="card" style={{ marginBottom: "var(--gap)" }}>
        <CardHead
          label={`Subscriptions & renewals${active ? ` · ${active} only — click the tile again to clear` : ""}`}
          aside={
            <span style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <RefreshedAt at={computedAt} />
              {editing ? (
                <button type="button" className="sub-add" onClick={addRow} data-tip="Add a cost line the engine can't see">
                  + Add cost
                </button>
              ) : null}
              <button
                type="button"
                className={editing ? "sub-add sub-edit-on" : "sub-add"}
                onClick={() => setEditing((v) => !v)}
                data-tip={editing ? "Lock the table — back to read-only" : "Edit the cost table like a sheet — click any cell to change the truth source"}
              >
                {editing ? "Done" : "Edit"}
              </button>
            </span>
          }
        />
        <div className="card-body">
          <SubscriptionsTable
            rows={filtered}
            editing={editing}
            onEdit={editRow}
            onReset={resetRow}
            onEditManual={editManual}
            onRemoveManual={removeManual}
          />
          <div className="costs-note">
            <code>/ mo</code> seeds from each provider&apos;s billing (real where the API reports it, a
            plan-tier estimate otherwise); <b style={{ color: "var(--fg)" }}>last paid</b>,{" "}
            <b style={{ color: "var(--fg)" }}>next renewal</b>, cadence &amp; lifetime are subscription facts
            the engine can&apos;t see — click any to <b style={{ color: "var(--fg)" }}>set</b> them, or{" "}
            <b style={{ color: "var(--fg)" }}>+ Add cost</b> for a line of your own. <code>/ mo</code> &amp;
            projection compute live; operator-entered values are saved in this browser. Nothing is fabricated.
            {hasOverrides ? <span className="iris"> · overrides active</span> : null}
          </div>
        </div>
      </div>
    </>
  );
}
