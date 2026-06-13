"use client";

// GuardTile — the Iris Bento "guardrail folded into the KPI line" box (mirrors the mockup's guardBox +
// editCap). A `.kpi-box.guard-mini` that reads ONE real used/cap guardrail (Daily loss / Max DD / Exposure)
// as a used value coloured by occupancy, with an editable `.gm-cap` (click → `.cap-in` input) and a thin
// `.gm-bar` fill. Colour escalates with occupancy (mockup `gcol`): ≥85% red, ≥60% gold, else up-green.
//
// HONESTY: it renders ONLY what it is handed and never fabricates a reading. The Live surface passes the
// engine's real used/cap; when nothing is live it passes 0 / cap (the honest safe state — every guardrail
// sits at 0% while disarmed). When `used` is null (no live metric source — e.g. Max DD), it renders "—" for
// the used value rather than a fabricated 0.

import { useState } from "react";

export type GuardUnit = "usd" | "pct";

// Occupancy → semantic colour var. Mirrors the mockup's gcol thresholds exactly.
function gcol(frac: number): string {
  if (frac >= 0.85) return "var(--down)";
  if (frac >= 0.6) return "var(--gold)";
  return "var(--up)";
}

function fmtVal(v: number, unit: GuardUnit): string {
  if (unit === "usd") return `$${Math.round(v).toLocaleString("en-US")}`;
  return `${(Math.round(v * 10) / 10).toLocaleString("en-US")}%`;
}

export function GuardTile({
  label,
  used,
  cap,
  unit,
  editable = true,
  onCapChange
}: {
  label: string;
  /** The real used amount, or null when there is no live metric source yet (renders "—"). */
  used: number | null;
  cap: number;
  unit: GuardUnit;
  /** When false, the cap is read-only (no inline edit). */
  editable?: boolean;
  /** Called with the new cap when the operator edits it inline (committed on blur / Enter). */
  onCapChange?: (next: number) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(cap));

  const frac = used !== null && cap > 0 ? Math.min(used / cap, 1) : 0;
  const col = gcol(frac);

  function commit() {
    const n = parseFloat(draft);
    setEditing(false);
    if (!Number.isNaN(n) && n > 0) onCapChange?.(n);
    else setDraft(String(cap));
  }

  return (
    <div className="kpi-box guard-mini">
      <div className="kpi-label">{label}</div>
      <div className="gm-val">
        <span style={{ color: used === null ? "var(--quiet)" : col }}>
          {used === null ? "—" : fmtVal(used, unit)}
        </span>{" "}
        {editing ? (
          <input
            className="cap-in"
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
              if (e.key === "Escape") {
                setDraft(String(cap));
                setEditing(false);
              }
            }}
            aria-label={`${label} cap`}
          />
        ) : (
          <span
            className="gm-cap"
            data-tip={editable ? "Click to edit the limit" : undefined}
            onClick={editable ? () => { setDraft(String(cap)); setEditing(true); } : undefined}
          >
            / {fmtVal(cap, unit)}
          </span>
        )}
      </div>
      <div className="gm-bar">
        <div className="gm-fill" style={{ width: `${(frac * 100).toFixed(0)}%`, background: col }} />
      </div>
    </div>
  );
}
