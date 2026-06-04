"use client";

// module: WidgetCard — the Notion-style block that wraps a cockpit widget. A calm card with a title row
// (icon + name, optional "run /command" hover hint, optional deep-link, optional right-aligned aside) and
// a body. Keeps every new widget visually consistent without each re-implementing the chrome. (Edit-mode
// removal is handled uniformly by the <Cockpit/> shell, so it isn't a concern of the card itself.)

import type { ReactNode } from "react";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { Card } from "@/components/ui/card";
import { CommandHint } from "@/components/ui/command-hint";
import { cn } from "@/lib/utils";

export function WidgetCard({
  title,
  icon,
  command,
  href,
  hrefLabel,
  aside,
  className,
  bodyClassName,
  children
}: {
  title: string;
  icon?: ReactNode;
  command?: string;
  href?: string;
  hrefLabel?: string;
  aside?: ReactNode;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
}) {
  return (
    <Card className={cn("flex h-full flex-col", className)}>
      <div className="flex items-start justify-between gap-3 p-5 pb-3">
        <div className="flex min-w-0 items-center gap-1.5">
          {icon ? <span className="text-iris-soft">{icon}</span> : null}
          <h3 className="truncate text-sm font-semibold tracking-tight text-foreground">{title}</h3>
          {command ? <CommandHint cmd={command} /> : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {aside}
          {href ? (
            <Link
              href={href}
              className="inline-flex items-center gap-1 text-[12px] font-medium text-iris-soft transition-colors hover:underline"
            >
              {hrefLabel ?? "Open"} <ArrowUpRight className="size-3.5" />
            </Link>
          ) : null}
        </div>
      </div>
      <div className={cn("flex-1 p-5 pt-0", bodyClassName)}>{children}</div>
    </Card>
  );
}
