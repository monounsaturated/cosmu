import type { SVGProps } from "react";

// module: Cosmu brand mark — a cosmonaut helmet. Stroke-based with currentColor so it
// sits alongside lucide icons and inherits theme color. Favicon lives in app/icon.svg.
export function CosmuMark({ size = 16, ...props }: { size?: number } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {/* helmet shell */}
      <circle cx="12" cy="12" r="9" />
      {/* visor */}
      <rect x="7" y="9" width="10" height="6" rx="3" />
      {/* visor reflection */}
      <circle cx="9.7" cy="11.6" r="1" fill="currentColor" stroke="none" />
    </svg>
  );
}
