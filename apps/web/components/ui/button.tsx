import type { ComponentProps } from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const button = cva(
  "inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium whitespace-nowrap transition-all outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary:
          "bg-iris text-white font-semibold shadow-[0_10px_28px_-14px_var(--color-iris)] hover:brightness-110 active:brightness-95",
        secondary: "bg-surface-2 text-foreground border border-border hover:border-border-strong hover:bg-surface-2/80",
        ghost: "text-muted hover:bg-surface-2/70 hover:text-foreground",
        outline: "border border-border-strong text-foreground hover:bg-surface-2/60"
      },
      size: {
        sm: "h-8 px-3",
        md: "h-9 px-4",
        lg: "h-10 px-5",
        icon: "h-9 w-9"
      }
    },
    defaultVariants: { variant: "secondary", size: "md" }
  }
);

export function Button({
  className,
  variant,
  size,
  asChild,
  ...props
}: ComponentProps<"button"> & VariantProps<typeof button> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "button";
  return <Comp className={cn(button({ variant, size }), className)} {...props} />;
}
