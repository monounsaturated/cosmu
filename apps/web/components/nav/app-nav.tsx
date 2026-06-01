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

export function MobileNav() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  return (
    <div className="lg:hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label="Open menu"
        aria-expanded={open}
        className="inline-flex size-9 items-center justify-center rounded-md border border-border/70 text-muted transition-colors hover:bg-surface-2/60 hover:text-foreground"
      >
        {open ? <X className="size-5" /> : <Menu className="size-5" />}
      </button>
      {open &&
        createPortal(
          <div className="fixed inset-0 z-50" role="dialog" aria-modal="true">
            <button
              aria-label="Close menu"
              onClick={() => setOpen(false)}
              className="animate-overlay-in absolute inset-0 bg-black/40"
            />
            {/* compact, content-sized rounded panel that slides + fades in from the top (pure CSS) */}
            <div className="animate-menu-in absolute inset-x-3 top-3 origin-top rounded-2xl border border-border bg-surface p-2 shadow-2xl">
              <div className="flex items-center justify-between px-1.5 pb-2 pt-1">
                <CosmuWordmark />
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  aria-label="Close menu"
                  className="inline-flex size-8 items-center justify-center rounded-md text-muted hover:bg-surface-2/60 hover:text-foreground"
                >
                  <X className="size-5" />
                </button>
              </div>
              <div className="grid grid-cols-2 gap-1.5">
                {navItems.map((item) => {
                  const active = isActive(pathname, item.href);
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      onClick={() => setOpen(false)}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex items-center gap-2 rounded-lg border px-3 py-2.5 text-[13px] transition-colors",
                        active
                          ? "border-border bg-surface-2/70 text-foreground"
                          : "border-transparent bg-surface-2/30 text-muted hover:bg-surface-2/60 hover:text-foreground",
                        item.gated && !active && "text-quiet opacity-70"
                      )}
                    >
                      <item.icon className={cn("size-[17px] shrink-0", active ? "text-iris-soft" : "text-quiet")} />
                      <span>{item.label}</span>
                    </Link>
                  );
                })}
              </div>
            </div>
          </div>,
          document.body
        )}
    </div>
  );
}
