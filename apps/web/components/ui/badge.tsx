import type { ComponentProps } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badge = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium leading-none whitespace-nowrap tabular",
  {
    variants: {
      variant: {
        iris: "border-iris/35 bg-iris/12 text-iris-soft",
        up: "border-up/35 bg-up/10 text-up",
        down: "border-down/35 bg-down/10 text-down",
        warn: "border-warn/35 bg-warn/10 text-warn",
        info: "border-info/35 bg-info/10 text-info",
        muted: "border-border bg-surface-2/60 text-muted",
        outline: "border-border-strong text-muted"
      }
    },
    defaultVariants: { variant: "muted" }
  }
);

export function Badge({
  className,
  variant,
  ...props
}: ComponentProps<"span"> & VariantProps<typeof badge>) {
  return <span className={cn(badge({ variant }), className)} {...props} />;
}
