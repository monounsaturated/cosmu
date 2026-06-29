"use client";

// module: app navigation (Iris Bento `.sb-nav` / `.nav-item`). The v18 redesign IS the whole
// frontend — TEN surfaces: Strategies · Paper · Live · Trades · Indexes · Mind · Conviction · Costs · Keys · Commands
// (landing = Strategies). Trades is the one ledger of every execution (paper + live), tagged. Mind is the read-only credibility surface — the followed-voices scoreboard off
// /mind/credibility. Conviction is the read-only, PROPOSE-ONLY queue (off /conviction/proposals) of LLM/Conviction
// trade ideas built from high-authority accounts' fresh asset-calls — a human reviews the authority evidence and
// arms; nothing on that surface moves money. Strategies is now the ONE granular surface: every (algo × asset × venue)
// triplet, never pooled — the old per-symbol "Lab" tab was folded into it (its route now redirects).
// Indexes (2026-06-15) is the operator-defined, deterministically-scored
// signal-index registry that strategies later key off. (The old Research/experiment-memory route was
// dropped from the nav to declutter — its gate_verdicts data stays in the DB + /verdicts API and is
// meant to become a generated report, not a daily surface.) There is no mobile bottom-dock: the bento
// sidebar collapses to an icon
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
  indexes: (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1.7 10.5l3-3.4 2.4 2 3.4-4.4" /><circle cx="12.2" cy="3.4" r="1" fill="currentColor" stroke="none" />
      <line x1="1.7" y1="13" x2="13" y2="13" />
    </svg>
  ),
  mind: (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
      <path d="M7.5 2.3c-2 0-3.4 1.3-3.4 3 0 .5-.3.8-.7 1.2-.5.5-.7 1-.7 1.6 0 .9.6 1.5 1.4 1.7.2 1.3 1.3 2.2 2.7 2.2" />
      <path d="M7.5 2.3c2 0 3.4 1.3 3.4 3 0 .5.3.8.7 1.2.5.5.7 1 .7 1.6 0 .9-.6 1.5-1.4 1.7-.2 1.3-1.3 2.2-2.7 2.2" />
      <line x1="7.5" y1="2.3" x2="7.5" y2="12" />
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
  trades: (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2.5 4.5h9" /><path d="m9 2 2.5 2.5L9 7" /><path d="M12.5 10.5h-9" /><path d="m6 8-2.5 2.5L6 13" />
    </svg>
  ),
  costs: (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" strokeLinejoin="round">
      <rect x="1.5" y="3.5" width="12" height="8" rx="2" /><path d="M1.5 6.2h12" />
      <circle cx="10.4" cy="9" r="1" fill="currentColor" stroke="none" />
    </svg>
  ),
  research: (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 1.7v4.1L2.9 11a1.4 1.4 0 0 0 1.2 2.1h6.8A1.4 1.4 0 0 0 12.1 11L9 5.8V1.7" /><line x1="5.2" y1="1.7" x2="9.8" y2="1.7" /><line x1="4.7" y1="8.4" x2="10.3" y2="8.4" />
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
  ),
  conviction: (
    <svg viewBox="0 0 15 15" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="7.5" cy="7.5" r="5.6" /><circle cx="7.5" cy="7.5" r="2.6" />
      <circle cx="7.5" cy="7.5" r="0.6" fill="currentColor" stroke="none" />
    </svg>
  )
};

// The primary surfaces — the entire app, in canonical sidebar order.
export const navItems: NavItem[] = [
  { href: "/strategies", key: "strategies", label: "Strategies", icon: ICONS.strategies },
  { href: "/paper", key: "paper", label: "Paper", icon: ICONS.paper },
  { href: "/live", key: "live", label: "Live", icon: ICONS.live },
  { href: "/trades", key: "trades", label: "Trades", icon: ICONS.trades },
  { href: "/indexes", key: "indexes", label: "Indexes", icon: ICONS.indexes },
  { href: "/mind", key: "mind", label: "Mind", icon: ICONS.mind },
  { href: "/conviction", key: "conviction", label: "Conviction", icon: ICONS.conviction },
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
