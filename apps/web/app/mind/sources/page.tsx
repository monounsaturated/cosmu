// Full source-trust scoreboard — every registered data source, sortable + filterable.
// Linked from the Mind page DataPreview "View all" button.

import { ArrowLeft, Database } from "lucide-react";
import Link from "next/link";
import { getSourceTrust, engineConfigured } from "../../data";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { NotConnected } from "@/components/ui/honest-state";
import { SourceTrustTable } from "./source-trust-table";

export default async function SourcesPage() {
  const { trust, connected } = await getSourceTrust();
  const rows = trust.rows ?? [];

  const freshCount = rows.filter((r) => r.status === "fresh" || r.status === "recent").length;
  const withGatePasses = rows.filter((r) => r.gate_pass_count > 0).length;

  return (
    <div className="mx-auto max-w-[1100px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
      <div className="flex items-start gap-3">
        <Link
          href="/mind"
          className="mt-1 flex shrink-0 items-center gap-1 text-[12px] text-muted transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" /> Mind
        </Link>
        <SectionHeader
          eyebrow="mind · sources"
          title="Source trust scoreboard"
          aside={
            <div className="flex items-center gap-2">
              <Badge variant="muted">{freshCount}/{rows.length} fresh</Badge>
              <Badge variant="muted">{withGatePasses} contributed</Badge>
            </div>
          }
          className="flex-1"
        />
      </div>

      <p className="text-[12px] text-muted">
        Trust = freshness × realized gate contribution. Honest: sources with no data show &quot;no data&quot;. Never fabricated.
        {trust.as_of && (
          <span className="ml-2 text-quiet">
            As of {new Date(trust.as_of).toLocaleTimeString()}.
          </span>
        )}
      </p>

      {!connected ? (
        <NotConnected
          configured={engineConfigured}
          what="Source trust scores appear once data has been ingested and the engine is connected."
        />
      ) : (
        <Card>
          <CardContent className="pt-5">
            <SourceTrustTable rows={rows} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
