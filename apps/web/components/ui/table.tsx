import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

// Dense, premium data table primitives (Bloomberg/Stripe). Hairline rows, calm hover, tabular
// numerics. Numeric columns should set `className="text-right tabular"` on TH/TD so digits align.
export function Table({ className, ...props }: ComponentProps<"table">) {
  return (
    <div className="w-full overflow-x-auto">
      <table className={cn("w-full border-collapse text-[13px]", className)} {...props} />
    </div>
  );
}

// Sticky header for tall, scrolling tables — keeps column heads pinned with a calm blur backdrop.
export function THead({ className, sticky = false, ...props }: ComponentProps<"thead"> & { sticky?: boolean }) {
  return (
    <thead
      className={cn(sticky && "glass sticky top-0 z-10", className)}
      {...props}
    />
  );
}

export function TBody({ className, ...props }: ComponentProps<"tbody">) {
  return <tbody className={cn("", className)} {...props} />;
}

export function TR({ className, ...props }: ComponentProps<"tr">) {
  return (
    <tr
      className={cn(
        "border-b border-hairline transition-colors last:border-0 hover:bg-surface-2/45",
        className
      )}
      {...props}
    />
  );
}

export function TH({ className, ...props }: ComponentProps<"th">) {
  return (
    <th
      className={cn(
        "px-3 py-2.5 text-left text-[10.5px] font-semibold uppercase tracking-[0.1em] text-quiet",
        className
      )}
      {...props}
    />
  );
}

export function TD({ className, ...props }: ComponentProps<"td">) {
  return <td className={cn("px-3 py-3 align-middle", className)} {...props} />;
}
