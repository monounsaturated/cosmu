import { cn } from "@/lib/utils";

/**
 * Cosmu mark — an orbit (the strategy population) circling the deterministic core, one bright
 * node mid-orbit. The tile is filled with the iris gradient so it reads on BOTH light and dark
 * (the old dark-fill tile blacked out on light mode). Glyph is white for contrast on the iris.
 */
export function CosmuMark({ className, size = 32 }: { className?: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none" className={className} aria-hidden>
      <defs>
        <linearGradient id="cosmu-tile" x1="2" y1="2" x2="38" y2="38" gradientUnits="userSpaceOnUse">
          <stop stopColor="#7c5cff" />
          <stop offset="1" stopColor="#5331c9" />
        </linearGradient>
      </defs>
      <rect x="0.75" y="0.75" width="38.5" height="38.5" rx="11" fill="url(#cosmu-tile)" />
      <ellipse cx="20" cy="20" rx="12" ry="6.6" stroke="white" strokeOpacity="0.92" strokeWidth="2" transform="rotate(-28 20 20)" />
      <circle cx="20" cy="20" r="3.4" fill="white" />
      <circle cx="30.4" cy="14.8" r="2.3" fill="#f3c948" />
    </svg>
  );
}

export function CosmuWordmark({ subtitle = "v2 autonomous lab" }: { subtitle?: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <CosmuMark />
      <div className="leading-tight">
        <div className="text-[15px] font-semibold tracking-tight text-foreground">Cosmu</div>
        <div className={cn("text-[11px] text-quiet")}>{subtitle}</div>
      </div>
    </div>
  );
}
