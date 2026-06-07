import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

// The base surface every panel composes from. Calm by default; pass `interactive` to opt into a
// 1px hover-lift + brighter border (for cards that are themselves links/buttons). Premium hairline
// border + low-spread elevation — the Mercury/Linear "floats off the canvas, doesn't shout" feel.
export function Card({
  className,
  interactive = false,
  ...props
}: ComponentProps<"div"> & { interactive?: boolean }) {
  return (
    <div
      className={cn(
        "card-grad rounded-lg border border-border/70 shadow-card",
        interactive && "lift cursor-pointer hover:border-border-strong",
        className
      )}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("flex items-start justify-between gap-4 p-5 pb-3", className)} {...props} />;
}

export function CardTitle({ className, ...props }: ComponentProps<"h3">) {
  return <h3 className={cn("text-sm font-semibold tracking-tight text-foreground", className)} {...props} />;
}

export function CardDescription({ className, ...props }: ComponentProps<"p">) {
  return <p className={cn("text-[13px] leading-snug text-muted", className)} {...props} />;
}

export function CardContent({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("p-5 pt-0", className)} {...props} />;
}
