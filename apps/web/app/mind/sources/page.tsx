// Full source-trust scoreboard — the data-source catalog: every registered feed, sortable + filterable,
// with a coverage rollup up top (trusted · fresh · contributing). Linked from the Mind page.

import { ArrowLeft, CheckCircle, ShieldCheck, Zap } from "lucide-react";
import Link from "next/link";
import { getSourceTrust, engineConfigured } from "../../data";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { NotConnected } from "@/components/ui/honest-state";
import { MetricCard } from "@/components/ui/viz";
import { SourceTrustTable } from "./source-trust-table";

export default async function SourcesPage() {
  const { trust, connected } = await getSourceTrust();
  const rows = trust.rows ?? [];

  const freshCount = rows.filter((r) => r.status === "fresh" || r.status === "recent").length;
  const withGatePasses = rows.filter((r) => r.gate_pass_count > 0).length;
  const trustedCount = rows.filter((r) => r.trust_score >= 0.5).length;

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
          <span className="ml-2 text-quiet">As of {new Date(trust.as_of).toLocaleTimeString()}.</span>
        )}
      </p>

      {!connected ? (
        <NotConnected
          configured={engineConfigured}
          what="Source trust scores appear once data has been ingested and the engine is connected."
        />
      ) : (
        <>
          {/* Coverage rollup — the catalog at a glance. */}
          {rows.length > 0 && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <MetricCard
                label="Registered sources"
                value={rows.length}
                tone="iris"
                icon={<ShieldCheck className="size-4" />}
                hint={`${trustedCount} at ≥50% trust`}
              />
              <MetricCard
                label="Fresh"
                value={`${freshCount}/${rows.length}`}
                tone="up"
                icon={<CheckCircle className="size-4" />}
                hint="ingested recently"
              />
              <MetricCard
                label="Contributing to gate"
                value={withGatePasses}
                tone={withGatePasses > 0 ? "up" : "muted"}
                icon={<Zap className="size-4" />}
                hint="have a realized gate pass"
              />
            </div>
          )}
          <Card>
            <CardContent className="pt-5">
              <SourceTrustTable rows={rows} />
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
