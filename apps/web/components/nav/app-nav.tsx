"use client";

// module: app navigation. Desktop = persistent sidebar list; mobile = hamburger + slide-in drawer
// so the menu is always reachable on narrow screens. Links are real routes only (no #anchors),
// with active-state highlighting via the current path.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { ChartCandlestick, Dna, LayoutDashboard, Menu, SlidersHorizontal, X } from "lucide-react";
import { CosmuWordmark } from "@/components/brand/logo";
import { cn } from "@/lib/utils";

export const navItems = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/farm", label: "Farm", icon: Dna },
  { href: "/strategy/sv-btc", label: "Strategies", icon: ChartCandlestick },
  { href: "/settings", label: "Settings", icon: SlidersHorizontal }
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  if (href.startsWith("/strategy")) return pathname.startsWith("/strategy");
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function SideNavLinks({ onNavigate, collapsed = false }: { onNavigate?: () => void; collapsed?: boolean }) {
  const pathname = usePathname();
  return (
    <nav className="flex flex-col gap-1" aria-label="Main navigation">
      {navItems.map((item) => {
        const active = isActive(pathname, item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            title={collapsed ? item.label : undefined}
            className={cn(
              "group flex items-center gap-3 rounded-md border text-[13px] transition-colors",
              collapsed ? "justify-center px-0 py-2.5" : "px-3 py-2",
              active
                ? "border-border bg-surface-2/70 text-foreground"
                : "border-transparent text-muted hover:border-border hover:bg-surface-2/60 hover:text-foreground"
            )}
          >
            <item.icon className={cn("size-[17px] shrink-0 transition-colors", active ? "text-iris-soft" : "text-quiet group-hover:text-iris-soft")} />
            {!collapsed && <span>{item.label}</span>}
          </Link>
        );
      })}
    </nav>
  );
}

export function MobileNav() {
  const [open, setOpen] = useState(false);
  return (
    <div className="lg:hidden">
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Open menu"
        className="inline-flex size-9 items-center justify-center rounded-md border border-border/70 text-muted transition-colors hover:bg-surface-2/60 hover:text-foreground"
      >
        <Menu className="size-5" />
      </button>
      {open && (
        <div className="fixed inset-0 z-50" role="dialog" aria-modal="true">
          <button aria-label="Close menu" className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
          <div className="glass absolute left-0 top-0 flex h-full w-[260px] flex-col gap-4 border-r border-border/70 p-4">
            <div className="flex items-center justify-between">
              <CosmuWordmark />
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close menu"
                className="inline-flex size-8 items-center justify-center rounded-md text-muted hover:text-foreground"
              >
                <X className="size-5" />
              </button>
            </div>
            <SideNavLinks onNavigate={() => setOpen(false)} />
          </div>
        </div>
      )}
    </div>
  );
}
