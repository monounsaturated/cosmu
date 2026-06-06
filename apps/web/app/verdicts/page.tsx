// Full verdict ledger — every thesis the Gate has ruled on, sortable + filterable.
// Linked from the Overview's DataPreview "View all" button.
// Server-fetches the full ledger; client-side sort + search via DataTablePage.

import { ArrowLeft, ClipboardCheck } from "lucide-react";
import Link from "next/link";
import { getVerdicts, engineConfigured } from "../data";
import type { VerdictRow } from "../data";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { NotConnected } from "@/components/ui/honest-state";
import { VerdictTable } from "./verdict-table";

const VERDICT_STYLE: Record<VerdictRow["status"], { label: string; variant: "up" | "down" | "warn" | "muted" }> = {
  PASS: { label: "PASS", variant: "up" },
  FAIL: { label: "FAIL", variant: "down" },
  "INSUFFICIENT-DATA": { label: "Insufficient data", variant: "warn" },
  "DATA-BLOCKED": { label: "Data-blocked", variant: "muted" }
};

export default async function VerdictsPage() {
  const { verdicts, connected } = await getVerdicts();
  const rows: VerdictRow[] = verdicts.rows ?? [];

  const passCount = rows.filter((r) => r.status === "PASS").length;
  const failCount = rows.filter((r) => r.status === "FAIL").length;

  return (
    <div className="mx-auto max-w-[1100px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
      <div className="flex items-start gap-3">
        <Link
          href="/"
          className="mt-1 flex shrink-0 items-center gap-1 text-[12px] text-muted transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" /> Overview
        </Link>
        <SectionHeader
          eyebrow="verdicts · all"
          title="Verdict ledger"
          aside={
            <div className="flex items-center gap-2">
              <Badge variant="up">{passCount} PASS</Badge>
              <Badge variant="down">{failCount} FAIL</Badge>
            </div>
          }
          className="flex-1"
        />
      </div>

      {!connected ? (
        <NotConnected
          configured={engineConfigured}
          what="Every thesis the Gate has ruled on appears here — PASS or FAIL. Connect the engine to see the real ledger."
        />
      ) : (
        <Card>
          <CardContent className="pt-5">
            <VerdictTable rows={rows} verdictStyle={VERDICT_STYLE} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
