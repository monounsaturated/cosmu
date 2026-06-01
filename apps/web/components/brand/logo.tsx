import { cn } from "@/lib/utils";

/**
 * Cosmu mark — an orbit (the strategy population circling the deterministic core)
 * with a single bright node mid-orbit. Iris gradient, cosmos motif.
 */
export function CosmuMark({ className, size = 34 }: { className?: string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      className={className}
      aria-hidden
    >
      <defs>
        <linearGradient id="cosmu-iris" x1="6" y1="6" x2="42" y2="42" gradientUnits="userSpaceOnUse">
          <stop stopColor="oklch(0.74 0.16 290)" />
          <stop offset="1" stopColor="oklch(0.6 0.2 300)" />
        </linearGradient>
        <radialGradient id="cosmu-core" cx="0.5" cy="0.5" r="0.5">
          <stop stopColor="oklch(0.86 0.12 290)" />
          <stop offset="1" stopColor="oklch(0.62 0.2 295)" />
        </radialGradient>
      </defs>
      <rect x="1" y="1" width="46" height="46" rx="13" fill="oklch(0.22 0.03 290)" />
      <rect x="1" y="1" width="46" height="46" rx="13" stroke="url(#cosmu-iris)" strokeOpacity="0.45" />
      <ellipse
        cx="24"
        cy="24"
        rx="14.5"
        ry="8"
        stroke="url(#cosmu-iris)"
        strokeWidth="2"
        transform="rotate(-28 24 24)"
      />
      <circle cx="24" cy="24" r="4" fill="url(#cosmu-core)" />
      <circle cx="36.4" cy="17.8" r="2.6" fill="oklch(0.82 0.14 85)" />
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
