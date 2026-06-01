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
            <CardTitle>Universe &amp; venues</CardTitle>
            <CardDescription>Which asset classes and venues the machine may research and trade.</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <UniverseSettings />
        </CardContent>
      </Card>
    </div>
  );
}
