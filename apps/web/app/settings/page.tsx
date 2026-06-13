// Settings — lean operator controls, two clear tiers:
//   1. Universe & legality — which asset classes / venues the machine may research and trade, and the
//      jurisdiction that decides which venues can move real money.
//   2. Engine — caps / the model, and a pointer to the top-level Keys page.
//
// Keys themselves live on their own primary surface (/keys) — this page does NOT duplicate the panel; it
// only links there, so there is one canonical keys view. Every change here is audited.

import type { ReactNode } from "react";
import Link from "next/link";
import { KeyRound, ArrowUpRight } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { UniverseSettings } from "@/components/universe/universe-settings";
import { JurisdictionSetting } from "@/components/universe/jurisdiction-setting";

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-[900px] space-y-9 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
      <SectionHeader
        eyebrow="settings"
        title="Operator controls"
        aside={<Badge variant="muted">every change is audited</Badge>}
      />

      {/* ── Tier 1 · Universe & legality ──────────────────────────────────────── */}
      <SettingsGroup label="Universe & legality" meaning="what the machine may research, trade, and fund">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Universe, venues &amp; data sources</CardTitle>
              <CardDescription>
                Which asset classes and venues the machine may research and trade. Venues without a live data feed are
                marked &ldquo;no data yet&rdquo;.
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <UniverseSettings />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Jurisdiction</CardTitle>
              <CardDescription>
                Where you operate — decides which venues can move real money (e.g. the US excludes Binance). One
                standardized setting; change it anytime.
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <JurisdictionSetting />
          </CardContent>
        </Card>
      </SettingsGroup>

      {/* ── Tier 2 · Engine ───────────────────────────────────────────────────── */}
      <SettingsGroup label="Engine" meaning="keys, caps, and the model">
        {/* Keys are their own primary surface (/keys) — link there, don't duplicate the panel. */}
        <Link href="/keys" className="group block focus-visible:outline-none" aria-label="Open the Keys page">
          <Card className="transition-colors group-hover:border-iris/40 group-focus-visible:border-iris/60">
            <CardHeader>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <KeyRound className="size-4 text-iris-soft" /> Keys
                  </CardTitle>
                  <CardDescription>
                    Provider/service keys now have their own page — what&rsquo;s connected vs missing on the engine and
                    what each unlocks. Status only, never values.
                  </CardDescription>
                </div>
                <ArrowUpRight className="mt-0.5 size-4 shrink-0 text-quiet transition-colors group-hover:text-iris-soft" />
              </div>
            </CardHeader>
          </Card>
        </Link>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Caps &amp; model</CardTitle>
              <CardDescription>
                Risk caps are set on the engine. The LLM is optional — research runs offline without it.
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-2.5 text-[12.5px] leading-relaxed text-muted">
            <p>
              <span className="font-medium text-foreground">Caps</span> (per-strategy, global, max daily loss) are
              reviewed and set in the two-click Live arming flow.
            </p>
            <p>
              <span className="font-medium text-foreground">Model on/off</span> — the LLM only authors and mutates ideas;
              it is out of the survival path. When it is off, deterministic template matching is used and the Gate still
              decides survival.
            </p>
          </CardContent>
        </Card>
      </SettingsGroup>
    </div>
  );
}

// A quiet tier divider: a small label + one-line meaning above a stack of related cards. Keeps the
// page sectioned and scannable without adding chrome.
function SettingsGroup({
  label,
  meaning,
  children,
}: {
  label: string;
  meaning: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-baseline gap-2.5 px-0.5">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.1em] text-iris-soft">{label}</h2>
        <span className="text-[11.5px] text-quiet">{meaning}</span>
      </div>
      <div className="space-y-4">{children}</div>
    </section>
  );
}
