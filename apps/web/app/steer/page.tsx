import { MessageSquare } from "lucide-react";
import { SteerBox } from "./steer-box";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SectionHeader } from "@/components/ui/section";

export default function SteerPage() {
  return (
    <div className="mx-auto max-w-[800px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
      <SectionHeader eyebrow="steer" title="Steer the machine" />
      <Card>
        <CardHeader>
          <div>
            <CardTitle className="flex items-center gap-1.5">
              <MessageSquare className="size-4 text-iris-soft" /> Steer in plain language
            </CardTitle>
            <CardDescription>Send research nudges or ask the survival model to re-rank. The Gate still decides what survives.</CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <SteerBox />
        </CardContent>
      </Card>
    </div>
  );
}
