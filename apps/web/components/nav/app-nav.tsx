"use client";

// module: app navigation (Iris Bento `.sb-nav` / `.nav-item`). The v18 redesign IS the whole
// frontend — SIX surfaces, nothing else: Strategies · Paper · Live · Costs · Keys · Commands
// (landing = Strategies). There is no mobile bottom-dock: the bento sidebar collapses to an icon
// rail at narrow widths via the `@media (max-width:880px)` rules in globals.css. Active state is the
// current route; optional per-stage counts come from a client fetch in the shell (shown only when real).

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type NavCounts = Partial<Record<string, number>>;

type NavItem = { href: string; key: string; label: string; icon: ReactNode };

// Inline SVG glyphs ported verbatim from the reference mockup (stroke = currentColor so they inherit
// the nav-item colour, including the active iris tint).
const ICONS: Record<string, ReactNode> = {
  strategies: (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round">
      <circle cx="3.2" cy="4" r="1.1" fill="currentColor" stroke="none" /><line x1="6.2" y1="4" x2="13" y2="4" />
      <circle cx="3.2" cy="7.5" r="1.1" fill="currentColor" stroke="none" /><line x1="6.2" y1="7.5" x2="13" y2="7.5" />
      <circle cx="3.2" cy="11" r="1.1" fill="currentColor" stroke="none" /><line x1="6.2" y1="11" x2="13" y2="11" />
    </svg>
  ),
  paper: (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="2.6" width="9" height="10.8" rx="1.6" /><rect x="5.4" y="1.5" width="4.2" height="2.3" rx="0.8" />
      <line x1="5.5" y1="7" x2="9.5" y2="7" /><line x1="5.5" y1="9.5" x2="9.5" y2="9.5" />
    </svg>
  ),
  live: (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1.5 7.5h2.6l1.4-3 2.2 6 1.4-3h3.4" />
    </svg>
  ),
  costs: (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" strokeLinejoin="round">
      <rect x="1.5" y="3.5" width="12" height="8" rx="2" /><path d="M1.5 6.2h12" />
      <circle cx="10.4" cy="9" r="1" fill="currentColor" stroke="none" />
    </svg>
  ),
  keys: (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="5" cy="5" r="2.5" /><path d="M6.8 6.8l5.4 5.4M9.8 12.2l2-2" />
    </svg>
  ),
  commands: (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" strokeLinejoin="round">
      <rect x="1.5" y="2.6" width="12" height="9.8" rx="1.6" /><polyline points="4,6 6.4,8 4,10" /><line x1="8" y1="10" x2="11" y2="10" />
    </svg>
  )
};

// The SIX primary surfaces — the entire app, in canonical sidebar order.
export const navItems: NavItem[] = [
  { href: "/strategies", key: "strategies", label: "Strategies", icon: ICONS.strategies },
  { href: "/paper", key: "paper", label: "Paper", icon: ICONS.paper },
  { href: "/live", key: "live", label: "Live", icon: ICONS.live },
  { href: "/costs", key: "costs", label: "Costs", icon: ICONS.costs },
  { href: "/keys", key: "keys", label: "Keys", icon: ICONS.keys },
  { href: "/commands", key: "commands", label: "Commands", icon: ICONS.commands }
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/strategies") return pathname.startsWith("/strategies") || pathname.startsWith("/strategy");
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function SideNav({ counts }: { counts?: NavCounts }) {
  const pathname = usePathname();
  return (
    <nav className="sb-nav" aria-label="Main navigation">
      {navItems.map((item) => {
        const active = isActive(pathname, item.href);
        const count = counts?.[item.key];
        return (
          <Link
            key={item.href}
            href={item.href}
            id={`nav-${item.key}`}
            aria-current={active ? "page" : undefined}
            className={cn("nav-item", active && "active")}
          >
            <span className="nav-left">
              {item.icon}
              {item.label}
            </span>
            {typeof count === "number" ? <span className="nav-count">{count}</span> : null}
          </Link>
        );
      })}
    </nav>
  );
}
