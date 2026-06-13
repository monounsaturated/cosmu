"use client";

// module: Keys → the v18 services ledger table (mockup id=page-services). One row per env var:
//   status-dot · Key · Service · Description · Location
// The status dot reads at a glance (green connected · amber unverified · red missing · grey unset);
// hovering it reveals the full label. The Location cell shows the env var name + ".env.local" (grey)
// + the deploy host (Railway/Vercel/…) COLOURED by whether the engine sees it set on that host.
//
// SECURITY: this NEVER renders a key value — only presence/status booleans the engine reports. It is a
// view-only index, so there are no inputs and nothing is editable here.

import type { ReactNode } from "react";
import type { SettingsKeyRow } from "@/app/data";
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/table";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

// Status → dot colour + human label. Mirrors the v18 SVCST mapping (live/pending/error/off) onto the
// engine's per-var status enum. `unset` is the calm grey "no key needed / not provided yet".
type KeyStatus = NonNullable<SettingsKeyRow["status"]>;

const STATUS_META: Record<KeyStatus, { dot: string; label: string; detail: string }> = {
  connected: {
    dot: "bg-up",
    label: "Connected",
    detail: "Key is set and the engine verified it works.",
  },
  unverified: {
    dot: "bg-warn",
    label: "Set · unverified",
    detail: "Key is present but the engine has not confirmed a live call yet.",
  },
  missing: {
    dot: "bg-down",
    label: "Missing",
    detail: "A required key is not set — the feature it unlocks stays off.",
  },
  unset: {
    dot: "bg-quiet",
    label: "Not set",
    detail: "Optional key — not provided. The lane runs keyless or stays off.",
  },
};

// The engine may omit `status` on legacy rows; fall back to the `configured` boolean so we never
// guess green for an unknown.
function statusOf(row: SettingsKeyRow): KeyStatus {
  if (row.status) return row.status;
  return row.configured ? "connected" : "missing";
}

// Friendly deploy-host label. Contract host enum is lowercase; "none" means local-only / no remote.
const HOST_LABEL: Record<NonNullable<SettingsKeyRow["host"]>, string> = {
  railway: "Railway",
  vercel: "Vercel",
  local: "local only",
  none: "—",
};

function hostLabel(row: SettingsKeyRow): string {
  if (!row.host || row.host === "none") return "";
  return HOST_LABEL[row.host];
}

// Colour the host token by whether the engine sees the key set THERE.
//   present.host === true  → green  (set on the deploy host)
//   present.host === false → red    (missing on the deploy host)
//   present.host == null   → amber  (unverified — None means we couldn't confirm)
function hostToneClass(present: SettingsKeyRow["present"]): string {
  const h = present?.host;
  if (h === true) return "text-up";
  if (h === false) return "text-down";
  return "text-warn"; // null / undefined → unverified
}

function StatusDot({ status }: { status: KeyStatus }) {
  const meta = STATUS_META[status];
  return (
    <Tooltip
      side="bottom"
      content={
        <span>
          <span className="font-medium text-foreground">{meta.label}.</span> {meta.detail}
        </span>
      }
    >
      <span
        className={cn("inline-block size-2 shrink-0 rounded-full", meta.dot)}
        aria-label={meta.label}
      />
    </Tooltip>
  );
}

// The Location cell: env var (mono) · .env.local (grey) · host (coloured by presence).
function Location({ row }: { row: SettingsKeyRow }) {
  const host = hostLabel(row);
  const localTone = row.present?.local === true ? "text-up" : "text-quiet";
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
      <code className="rounded bg-background/60 px-1.5 py-0.5 font-mono text-[10.5px] text-foreground">
        {row.env_var}
      </code>
      <span className={cn("font-mono", localTone)}>.env.local</span>
      {host ? <span className={cn("font-mono", hostToneClass(row.present))}>{host}</span> : null}
    </div>
  );
}

export function KeysTable({ rows }: { rows: SettingsKeyRow[] }) {
  return (
    <Table>
      <THead>
        <TR className="hover:bg-transparent">
          <TH className="w-6 whitespace-nowrap pr-0" aria-label="Status" />
          <TH className="whitespace-nowrap">Key</TH>
          <TH className="whitespace-nowrap">Service</TH>
          <TH className="whitespace-nowrap">Description</TH>
          <TH className="whitespace-nowrap">Location</TH>
        </TR>
      </THead>
      <TBody>
        {rows.map((row) => {
          const status = statusOf(row);
          return (
            <TR key={row.env_var}>
              <TD className="pr-0">
                <StatusDot status={status} />
              </TD>
              <TD className="whitespace-nowrap font-medium text-foreground">{row.name}</TD>
              <TD className="whitespace-nowrap text-quiet">{row.service || "—"}</TD>
              <TD className="text-[12px] text-muted">{row.description || "—"}</TD>
              <TD className="whitespace-nowrap">
                <Location row={row} />
              </TD>
            </TR>
          );
        })}
      </TBody>
    </Table>
  );
}

// Re-export the status meta so callers can build a coverage read-out without re-deriving the labels.
export function statusMeta(status: KeyStatus): { label: string; dot: string } {
  return STATUS_META[status];
}

export function keyStatusOf(row: SettingsKeyRow): KeyStatus {
  return statusOf(row);
}

// Type aliases for callers that want them.
export type { KeyStatus };

// Honest helper: count of rows in a given status (used by the page header / legend).
export function countByStatus(rows: SettingsKeyRow[]): Record<KeyStatus, number> {
  const out: Record<KeyStatus, number> = { connected: 0, unverified: 0, missing: 0, unset: 0 };
  for (const r of rows) out[statusOf(r)] += 1;
  return out;
}

// A tiny inline legend for the four dot colours — keeps the meaning in reach above the table.
export function KeysLegend({ rows }: { rows: SettingsKeyRow[] }) {
  const counts = countByStatus(rows);
  const order: KeyStatus[] = ["connected", "unverified", "missing", "unset"];
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-quiet">
      {order.map((s) => (
        <span key={s} className="inline-flex items-center gap-1.5">
          <span className={cn("inline-block size-2 rounded-full", STATUS_META[s].dot)} aria-hidden />
          <span className="text-muted">{STATUS_META[s].label}</span>
          <span className="tabular text-quiet">{counts[s]}</span>
        </span>
      ))}
    </div>
  );
}
