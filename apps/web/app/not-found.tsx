import Link from "next/link";
import { CosmuMark } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center gap-5 px-6 text-center">
      <CosmuMark size={48} />
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Off the orbit</h1>
        <p className="mt-1.5 text-[13.5px] text-muted">That page isn&apos;t part of the control plane.</p>
      </div>
      <Button variant="primary" asChild>
        <Link href="/">Return to Cosmu</Link>
      </Button>
    </div>
  );
}
