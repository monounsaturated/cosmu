// Keys → the v18 services ledger table (mockup id=page-services, `.key-tbl`). One row PER env var:
//   status-dot · Key · Service · Description · Location
// The status dot reads at a glance (green connected · gold unverified · red missing · grey unset) and
// hovering it (data-tip) reveals the full label. The Location cell shows ".env.local" (grey) + the deploy
// host (Railway/Vercel/…) COLOURED by whether the engine sees the key set on that host.
//
// SECURITY: this NEVER renders a key value — only presence/status booleans the engine reports. It is a
// view-only index, so there are no inputs and nothing is editable here. Server-safe (no client hooks):
// the only interactivity is the global tooltip handler reading `data-tip`.

import type { SettingsKeyRow } from "@cosmu/contracts-ts";

// Status → the v18 dot/host suffix (live/pending/error/off) + human tooltip. Maps the engine's per-var
// status enum (connected/unverified/missing/unset) onto the bento class suffixes verbatim from the mockup.
type KeyStatus = NonNullable<SettingsKeyRow["status"]>;

const STATUS_META: Record<KeyStatus, { suffix: string; label: string; tip: string }> = {
  connected: {
    suffix: "live",
    label: "connected",
    tip: "Connected — set locally and on the host, live & reachable",
  },
  unverified: {
    suffix: "pending",
    label: "unverified",
    tip: "Unverified — set, but the host copy is not confirmed live yet",
  },
  missing: {
    suffix: "error",
    label: "missing",
    tip: "Missing on the host — set in .env.local but the deployed host has no key",
  },
  unset: {
    suffix: "off",
    label: "unset",
    tip: "Not set — no key anywhere yet",
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
  local: "local",
  none: "",
};

function hostLabel(row: SettingsKeyRow): string {
  // "local" is redundant with the ".env.local" token already shown — never append a "· local".
  if (!row.host || row.host === "none" || row.host === "local") return "";
  return HOST_LABEL[row.host];
}

// The Location cell: ".env.local" + host name, both GREY/regular — the host (Railway/Vercel) is a plain
// label, NOT colour-coded by presence (the status DOT in column 1 already carries connected/missing/
// unverified). A keyed row shows ".env.local · <host>"; a keyless row shows just the host or a "public API".
function Location({ row }: { row: SettingsKeyRow }) {
  const host = hostLabel(row);
  if (!row.key) {
    return host ? <span className="loc-host">{host}</span> : <span className="loc-env">public API</span>;
  }
  return (
    <>
      <span className="loc-env">.env.local</span>
      {host ? (
        <>
          <span className="loc-sep">·</span>
          <span className="loc-host">{host}</span>
        </>
      ) : null}
    </>
  );
}

export function KeysTable({ rows }: { rows: SettingsKeyRow[] }) {
  return (
    <div className="tbl-scroll">
    <table className="mini-tbl key-tbl">
      <thead>
        <tr>
          <th className="k-st" aria-label="Status" />
          <th>Key</th>
          <th>Service</th>
          <th>Description</th>
          <th>Location</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const status = statusOf(row);
          const meta = STATUS_META[status];
          return (
            <tr key={row.env_var}>
              <td className="k-st">
                <span className={`kdot s-${meta.suffix}`} data-tip={meta.tip} />
              </td>
              <td>
                {row.key ? (
                  <span className="k-key">{row.env_var}</span>
                ) : (
                  <span className="quiet" style={{ fontSize: 11 }}>
                    {row.host ? "project-linked" : "keyless · public API"}
                  </span>
                )}
              </td>
              <td className="k-svc2">
                <span className="k-nm">{row.service || row.name}</span>
              </td>
              <td className="k-desc">{row.description || "—"}</td>
              <td>
                <Location row={row} />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
    </div>
  );
}

// Honest count helper — how many KEYED rows (env vars) are connected, for the "N of M connected" header.
export function keyedCounts(rows: SettingsKeyRow[]): { connected: number; total: number } {
  const keyed = rows.filter((r) => r.key);
  const connected = keyed.filter((r) => statusOf(r) === "connected").length;
  return { connected, total: keyed.length };
}

// The inline three-dot legend in the card header (connected · unverified · missing), verbatim from
// the mockup's LEGEND markup.
export function KeysLegend() {
  return (
    <span className="key-legend">
      <span className="lg">
        <span className="kdot s-live" />
        connected
      </span>
      <span className="lg">
        <span className="kdot s-pending" />
        unverified
      </span>
      <span className="lg">
        <span className="kdot s-error" />
        missing
      </span>
    </span>
  );
}

export type { KeyStatus };
