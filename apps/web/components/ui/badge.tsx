import type { ComponentProps } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

// A calm, premium status/label chip. Low-saturation fills on a near-neutral canvas; the color does
// the talking, never a heavy fill. Pass `dot` for a status-light variant (e.g. live / running).
const badge = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium leading-none whitespace-nowrap tabular",
  {
    variants: {
      variant: {
        iris: "border-iris/30 bg-iris/10 text-iris-soft",
        up: "border-up/30 bg-up/[0.09] text-up",
        down: "border-down/30 bg-down/[0.09] text-down",
        warn: "border-warn/30 bg-warn/[0.09] text-warn",
        info: "border-info/30 bg-info/[0.09] text-info",
        muted: "border-border bg-surface-2/60 text-muted",
        outline: "border-border-strong text-muted"
      }
    },
    defaultVariants: { variant: "muted" }
  }
);

// Dot color mirrors the variant so the status light reads at a glance.
const DOT: Record<NonNullable<VariantProps<typeof badge>["variant"]>, string> = {
  iris: "bg-iris-soft",
  up: "bg-up",
  down: "bg-down",
  warn: "bg-warn",
  info: "bg-info",
  muted: "bg-quiet",
  outline: "bg-quiet"
};

export function Badge({
  className,
  variant,
  dot = false,
  children,
  ...props
}: ComponentProps<"span"> & VariantProps<typeof badge> & { dot?: boolean }) {
  return (
    <span className={cn(badge({ variant }), className)} {...props}>
      {dot ? <span className={cn("size-1.5 shrink-0 rounded-full", DOT[variant ?? "muted"])} aria-hidden /> : null}
      {children}
    </span>
  );
}
