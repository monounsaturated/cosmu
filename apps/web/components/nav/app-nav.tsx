"use client";

// module: app navigation. Desktop = persistent sidebar list; mobile = hamburger + slide-in drawer
// so the menu is always reachable on narrow screens. Links are real routes only (no #anchors),
// with active-state highlighting via the current path.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { createPortal } from "react-dom";
import { LayoutDashboard, Menu, MessageSquare, Microscope, Radio, SlidersHorizontal, X } from "lucide-react";
import { CosmuWordmark } from "@/components/brand/logo";
import { cn } from "@/lib/utils";

// `gated` items are kept deliberately dimmed (live trading is in scope but off by default —
// the screen itself stays lean and the gate must pass before anything can arm).
type NavItem = { href: string; label: string; icon: typeof LayoutDashboard; gated?: boolean };

export const navItems: NavItem[] = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/research", label: "Research", icon: Microscope },
  { href: "/console", label: "Console", icon: MessageSquare },
  { href: "/live", label: "Live", icon: Radio, gated: true },
  { href: "/settings", label: "Settings", icon: SlidersHorizontal }
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  // Strategy detail pages live under Research, so keep Research highlighted there.
  if (href === "/research") return pathname.startsWith("/research") || pathname.startsWith("/strategy") || pathname.startsWith("/farm");
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
                : "border-transparent text-muted hover:border-border hover:bg-surface-2/60 hover:text-foreground",
              item.gated && !active && "text-quiet opacity-70 hover:opacity-100"
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

// Mobile primary navigation: a fixed bottom bar with large (>=44px) tap targets, always one tap
// from any surface. Sits above page content (the page reserves space via padding-bottom on mobile).
export function BottomNav() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Primary"
      className="glass fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-border/70 pb-[env(safe-area-inset-bottom)] lg:hidden"
    >
      {navItems.map((item) => {
        const active = isActive(pathname, item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex min-h-[56px] flex-col items-center justify-center gap-1 text-[10.5px] font-medium transition-colors",
              active ? "text-iris-soft" : "text-quiet hover:text-foreground",
              item.gated && !active && "opacity-70"
            )}
          >
            <item.icon className={cn("size-[20px] shrink-0", active && "text-iris-soft")} />
            <span>{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
