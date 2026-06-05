"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "Overview" },
  { href: "/costs", label: "Costs" },
  { href: "/console", label: "Console" },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function TopNav() {
  const pathname = usePathname();
  return (
    <nav className="flex items-center gap-0.5" aria-label="Main navigation">
      {NAV_ITEMS.map((item) => {
        const active = isActive(pathname, item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors",
              active
                ? "bg-surface-2/70 text-foreground"
                : "text-muted hover:bg-surface-2/40 hover:text-foreground"
            )}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
