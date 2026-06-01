import { SlidersHorizontal } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SectionHeader } from "@/components/ui/section";
import { UniverseSettings } from "@/components/universe/universe-settings";

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-[900px] space-y-8 px-5 py-7 lg:px-7">
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
            <CardTitle>Keys, caps &amp; model</CardTitle>
            <CardDescription>Execution keys and risk caps are set on the engine. The LLM is optional — research runs offline without it.</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-2.5 text-[12.5px] leading-relaxed text-muted">
          <p>
            <span className="font-medium text-foreground">Execution keys</span> live only on the engine, never in the browser. Live
            trading stays off until keys are present, the Gate has passed, and you arm it on the Live screen.
          </p>
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
