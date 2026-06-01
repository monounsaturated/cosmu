import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

export function Separator({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("h-px w-full bg-border/70", className)} {...props} />;
}
