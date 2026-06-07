import { KeyRound, SlidersHorizontal } from "lucide-react";
import { engineConfigured, getSettingsKeys } from "../data";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { UniverseSettings } from "@/components/universe/universe-settings";
import { JurisdictionSetting } from "@/components/universe/jurisdiction-setting";
import { KeysPanel } from "@/components/settings/keys-panel";

export default async function SettingsPage() {
  const { keys, connected } = await getSettingsKeys();
  return (
    <div className="mx-auto max-w-[900px] space-y-8 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
      <SectionHeader
        eyebrow="settings"
        title="Operator controls"
        aside={
          <Badge variant="iris">
            <SlidersHorizontal className="size-3" /> every change is audited
          </Badge>
        }
      />
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Universe, venues &amp; data sources</CardTitle>
            <CardDescription>Which asset classes and venues the machine may research and trade. Venues without a live data feed are marked &ldquo;no data yet&rdquo;.</CardDescription>
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
            <CardDescription>Where you operate — decides which venues can move real money (e.g. the US excludes Binance). One standardized setting; change it anytime, every change is audited.</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <JurisdictionSetting />
        </CardContent>
      </Card>

      <Card id="keys" className="scroll-mt-20">
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-2">
              <KeyRound className="size-4 text-iris-soft" /> Keys
            </CardTitle>
            <CardDescription>
              What&rsquo;s plugged in vs missing on the engine, and what each key unlocks. Keys live only on the engine,
              never in the browser — this page shows whether each is set, never its value. Full reference in{" "}
              <code className="font-mono text-iris-soft">docs/KEYS.md</code>.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <KeysPanel keys={keys} connected={connected} configured={engineConfigured} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Caps &amp; model</CardTitle>
            <CardDescription>Risk caps are set on the engine. The LLM is optional — research runs offline without it.</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-2.5 text-[12.5px] leading-relaxed text-muted">
          <p>
            <span className="font-medium text-foreground">Caps</span> (per-strategy, global, max daily loss) are reviewed and set in
            the two-click Live arming flow.
          </p>
          <p>
            <span className="font-medium text-foreground">Model on/off</span> — the LLM only authors and mutates ideas; it is out of
            the survival path. When it is off, deterministic template matching is used and the Gate still decides survival.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
