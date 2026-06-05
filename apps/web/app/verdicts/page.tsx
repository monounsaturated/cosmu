// Verdict ledger: every phase0-*-verdict.md result in one scannable table.
// The research history IS the product — no manufactured PASS, no buried FAIL.

import { FlaskConical } from "lucide-react";
import { getVerdicts, engineConfigured, type VerdictRow } from "../data";
import { SectionHeader } from "@/components/ui/section";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { NotConnectedBanner, EmptyState } from "@/components/ui/honest-state";
import { Table, THead, TBody, TR, TH, TD } from "@/components/ui/table";

type BadgeVariant = "up" | "down" | "warn" | "muted";

function statusVariant(status: VerdictRow["status"]): BadgeVariant {
  if (status === "PASS") return "up";
  if (status === "FAIL") return "down";
  return "warn";
}

function statusLabel(status: VerdictRow["status"]): string {
  if (status === "INSUFFICIENT-DATA") return "INSUF. DATA";
  if (status === "DATA-BLOCKED") return "DATA-BLOCKED";
  return status;
}

function fmt(n: number | null, decimals = 3): string {
  if (n === null || n === undefined) return "—";
  return n.toFixed(decimals);
}

function fmtTrades(n: number | null): string {
  if (n === null || n === undefined) return "—";
  return n.toLocaleString();
}

function fmtDate(iso: string): string {
  if (!iso) return "—";
  // YYYY-MM-DD → Jun 5, 2026
  try {
    return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      timeZone: "UTC"
    });
  } catch {
    return iso;
  }
}

export default async function VerdictsPage() {
  const { verdicts, connected } = await getVerdicts();
  const rows = verdicts.rows;

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-8 lg:px-7">
      <SectionHeader
        eyebrow="research history"
        title="Phase-0 verdict ledger"
        aside={
          <Badge variant="muted">
            <FlaskConical className="size-3" /> {rows.length} verdict{rows.length !== 1 ? "s" : ""}
          </Badge>
        }
      />

      <p className="text-[12.5px] leading-relaxed text-muted">
        Every phase-0 gate run recorded here, pre-registered criteria first, honest result after.
        No threshold was lowered for any run. No manufactured PASS.
      </p>

      {!connected ? <NotConnectedBanner configured={engineConfigured} /> : null}

      <Card>
        <CardContent className="p-0">
          {rows.length === 0 ? (
            <EmptyState
              title="No verdicts found"
              hint={
                connected
                  ? "The engine couldn't read the docs/reports directory. Check that it is deployed alongside the verdict files."
                  : "Connect the engine to load verdicts from the research history."
              }
            />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Thesis</TH>
                  <TH className="w-16">ID</TH>
                  <TH className="w-28">Date</TH>
                  <TH className="w-28">Verdict</TH>
                  <TH className="w-20 text-right">DSR</TH>
                  <TH className="w-20 text-right">Trades</TH>
                  <TH className="w-24 text-right">cost_ratio</TH>
                  <TH className="min-w-[220px]">Key finding</TH>
                </TR>
              </THead>
              <TBody>
                {rows.map((row) => (
                  <TR key={row.slug}>
                    <TD className="font-medium text-foreground">{row.thesis}</TD>
                    <TD className="font-mono text-[11.5px] text-muted">{row.id || "—"}</TD>
                    <TD className="text-muted">{fmtDate(row.date)}</TD>
                    <TD>
                      <Badge variant={statusVariant(row.status)}>
                        {statusLabel(row.status)}
                      </Badge>
                    </TD>
                    <TD className="text-right font-mono text-[12.5px]">
                      <span className={row.deflated_sharpe !== null && row.deflated_sharpe >= 0.95 ? "text-up" : row.deflated_sharpe !== null && row.deflated_sharpe < 0 ? "text-down" : "text-muted"}>
                        {fmt(row.deflated_sharpe)}
                      </span>
                    </TD>
                    <TD className="text-right font-mono text-[12.5px] text-muted">
                      {fmtTrades(row.trades)}
                    </TD>
                    <TD className="text-right font-mono text-[12.5px] text-muted">
                      {fmt(row.cost_ratio, 2)}
                    </TD>
                    <TD className="text-[12px] leading-relaxed text-muted">
                      {row.reason || "—"}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <p className="text-[11px] text-quiet">
        Source: <code className="font-mono">docs/reports/phase0-*-verdict.md</code> · DSR = deflated Sharpe ratio (bar: ≥ 0.95) · cost_ratio = net / gross (floor: ≥ 0.40)
      </p>
    </div>
  );
}
