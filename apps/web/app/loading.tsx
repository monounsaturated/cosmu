import { CosmuMark } from "@/components/brand/logo";

export default function Loading() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="flex flex-col items-center gap-3 text-muted">
        <CosmuMark className="animate-orbit" size={42} />
        <span className="text-[13px]">Loading Cosmu control plane…</span>
      </div>
    </div>
  );
}
