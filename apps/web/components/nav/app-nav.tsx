"use client";

// module: app navigation. The v18 redesign IS the whole frontend — SIX surfaces, no more: the
// lifecycle (Strategies → Paper → Live), the money (Costs), and the operator's two utility surfaces
// (Keys, Commands). The old research/knowledge/ops pages were folded (redirected in next.config.ts).
// Desktop = a flat persistent rail; mobile = a bottom tab bar (4 primary tabs + a More sheet for the
// 2 overflow items). Default landing = Strategies (app/page.tsx → /strategies).

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import {
  DollarSign,
  KeyRound,
  LayoutDashboard,
  LineChart,
  ListChecks,
  MoreHorizontal,
  Radio,
  Terminal,
  X
} from "lucide-react";
import { cn } from "@/lib/utils";

type NavItem = { href: string; label: string; desc?: string; icon: typeof LayoutDashboard; gated?: boolean };

// The SIX primary surfaces — the entire app. Flat list is the canonical order (desktop rail + mobile
// dock both consume it directly). Sidebar order: Strategies · Paper · Live · Costs · Keys · Commands.
export const navItems: NavItem[] = [
  { href: "/strategies", label: "Strategies", desc: "Ranked · faceted · the sheet", icon: ListChecks },
  { href: "/paper", label: "Paper", desc: "Forward test · live data, no money", icon: LineChart },
  { href: "/live", label: "Live", desc: "Positions · guardrails · rules", icon: Radio },
  { href: "/costs", label: "Costs", desc: "Spend · run-rate · renewals", icon: DollarSign },
  { href: "/keys", label: "Keys", desc: "Services · what's connected", icon: KeyRound },
  { href: "/commands", label: "Commands", desc: "Run from Claude Code", icon: Terminal }
];

// Desktop rail grouping — one flat unlabeled group renders all six surfaces (no eyebrows; the app is
// small enough to read as a single column). Each entry references navItems by href.
type NavGroup = { label: string; hrefs: string[] };
const NAV_GROUPS: NavGroup[] = [
  { label: "", hrefs: ["/strategies", "/paper", "/live", "/costs", "/keys", "/commands"] }
];

const ITEM_BY_HREF = new Map(navItems.map((i) => [i.href, i]));

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  if (href === "/strategies") {
    return pathname.startsWith("/strategies") || pathname.startsWith("/strategy");
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

function NavLink({ item, onNavigate, collapsed }: { item: NavItem; onNavigate?: () => void; collapsed: boolean }) {
  const pathname = usePathname();
  const active = isActive(pathname, item.href);
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
      title={collapsed ? item.label : undefined}
      className={cn(
        // Linear-style row: a left active-accent bar (via ::before), calm hover, tight type. The
        // accent bar replaces the boxed-border active state for a quieter, more premium read.
        "group relative flex items-center gap-3 rounded-md text-[13px] outline-none transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-ring/45",
        "before:absolute before:left-0 before:top-1/2 before:h-4 before:w-[2.5px] before:-translate-y-1/2 before:rounded-full before:bg-iris before:transition-opacity before:duration-150",
        collapsed ? "justify-center px-0 py-2.5 before:left-0.5" : "px-3 py-2",
        active
          ? "bg-surface-2/70 text-foreground before:opacity-100"
          : "text-muted hover:bg-surface-2/55 hover:text-foreground before:opacity-0",
        item.gated && !active && "text-quiet opacity-70 hover:opacity-100"
      )}
    >
      <item.icon className={cn("size-[17px] shrink-0 transition-colors", active ? "text-iris-soft" : "text-quiet group-hover:text-foreground")} />
      {!collapsed && (
        <span className="flex min-w-0 flex-col leading-tight">
          <span className="font-medium">{item.label}</span>
          {item.desc && <span className="truncate text-[10.5px] text-quiet">{item.desc}</span>}
        </span>
      )}
    </Link>
  );
}

export function SideNavLinks({ onNavigate, collapsed = false }: { onNavigate?: () => void; collapsed?: boolean }) {
  return (
    <nav className="flex flex-col gap-3" aria-label="Main navigation">
      {NAV_GROUPS.map((group) => (
        <div key={group.label} className="flex flex-col gap-0.5">
          {collapsed ? (
            <div className="mx-auto mb-0.5 h-px w-6 bg-hairline" aria-hidden />
          ) : group.label ? (
            <div className="label-eyebrow px-3 pb-1">{group.label}</div>
          ) : null}
          {group.hrefs.map((href) => {
            const item = ITEM_BY_HREF.get(href);
            return item ? <NavLink key={href} item={item} onNavigate={onNavigate} collapsed={collapsed} /> : null;
          })}
        </div>
      ))}
    </nav>
  );
}

// A single dock tab — large (~56px) tap target, clear active state.
function DockTab({
  item,
  active,
  onClick
}: {
  item: { href?: string; label: string; icon: typeof LayoutDashboard; gated?: boolean };
  active: boolean;
  onClick?: () => void;
}) {
  const Icon = item.icon;
  const inner = (
    <span className="flex h-full flex-col items-center justify-center gap-1">
      <span
        className={cn(
          "flex h-7 w-12 items-center justify-center rounded-full transition-colors duration-200",
          active ? "bg-iris/12" : "bg-transparent"
        )}
      >
        <Icon className={cn("size-[20px] shrink-0 transition-colors", active ? "text-iris-soft" : "text-quiet")} />
      </span>
      <span className={cn("text-[10px] font-medium transition-colors", active ? "text-iris-soft" : "text-quiet")}>{item.label}</span>
    </span>
  );
  const className = cn(
    "flex min-h-[56px] w-full items-center justify-center px-0.5 transition-colors",
    !active && "hover:text-foreground"
  );
  if (item.href) {
    return (
      <Link href={item.href} aria-current={active ? "page" : undefined} className={className}>
        {inner}
      </Link>
    );
  }
  return (
    <button type="button" onClick={onClick} className={className} aria-haspopup="dialog">
      {inner}
    </button>
  );
}

// Mobile primary navigation: first 4 nav items as primary tabs + a More sheet (5 cells total).
// Extra nav items beyond 4 go into the More sheet alongside the moreItems.
const BOTTOM_NAV_LIMIT = 4;

export function BottomNav() {
  const pathname = usePathname();
  const [sheetOpen, setSheetOpen] = useState(false);

  const primaryItems = navItems.slice(0, BOTTOM_NAV_LIMIT);
  const overflowItems = navItems.slice(BOTTOM_NAV_LIMIT);

  // Close the sheet whenever the route changes (a tap inside it navigated).
  useEffect(() => {
    setSheetOpen(false);
  }, [pathname]);

  // Lock body scroll while the sheet is open.
  useEffect(() => {
    if (!sheetOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [sheetOpen]);

  const overflowActive = overflowItems.some((i) => isActive(pathname, i.href));

  return (
    <>
      <nav
        aria-label="Primary"
        className="glass fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-border/70 pb-[env(safe-area-inset-bottom)] shadow-[0_-1px_0_0_color-mix(in_oklab,var(--color-border)_60%,transparent)] lg:hidden"
      >
        {primaryItems.map((item) => (
          <DockTab key={item.href} item={item} active={isActive(pathname, item.href)} />
        ))}
        <DockTab
          item={{ label: "More", icon: MoreHorizontal }}
          active={sheetOpen || overflowActive}
          onClick={() => setSheetOpen(true)}
        />
      </nav>

      <MoreSheet
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        pathname={pathname}
        overflowItems={overflowItems}
      />
    </>
  );
}

// Bottom sheet holding secondary routes + any nav items that overflow the primary bar.
function MoreSheet({
  open,
  onClose,
  pathname,
  overflowItems
}: {
  open: boolean;
  onClose: () => void;
  pathname: string;
  overflowItems: NavItem[];
}) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return null;

  const allItems = overflowItems;

  return createPortal(
    <div className={cn("fixed inset-0 z-40 lg:hidden", open ? "pointer-events-auto" : "pointer-events-none")} aria-hidden={!open}>
      {/* Scrim */}
      <button
        type="button"
        aria-label="Close menu"
        onClick={onClose}
        className={cn(
          "absolute inset-0 bg-black/50 transition-opacity duration-200 motion-reduce:transition-none",
          open ? "opacity-100" : "opacity-0"
        )}
        tabIndex={open ? 0 : -1}
      />
      {/* Sheet */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="More navigation"
        className={cn(
          "glass absolute inset-x-0 bottom-0 rounded-t-2xl border-t border-border/70 pb-[env(safe-area-inset-bottom)] shadow-2xl transition-transform duration-300 ease-out motion-reduce:transition-none",
          open ? "translate-y-0" : "translate-y-full"
        )}
      >
        <div className="flex items-center justify-between px-5 pt-3">
          <div className="mx-auto h-1 w-9 rounded-full bg-border" aria-hidden />
        </div>
        <div className="flex items-center justify-between px-5 pb-1 pt-2">
          <div className="text-[12px] font-semibold uppercase tracking-[0.12em] text-quiet">More</div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex size-9 items-center justify-center rounded-full text-quiet transition-colors hover:bg-surface-2/60 hover:text-foreground"
          >
            <X className="size-5" />
          </button>
        </div>
        <div className="grid grid-cols-2 gap-2 px-4 pb-5 pt-1">
          {allItems.map((item) => {
            const active = isActive(pathname, item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onClose}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex min-h-[56px] items-center gap-3 rounded-xl border px-4 transition-colors",
                  active ? "border-border-strong bg-surface-3 text-foreground" : "border-border/60 bg-surface-2/30 text-muted hover:bg-surface-2/55 hover:text-foreground"
                )}
              >
                <Icon className={cn("size-[19px] shrink-0", active ? "text-iris-soft" : "text-quiet")} />
                <span className="text-[13px] font-medium">{item.label}</span>
              </Link>
            );
          })}
        </div>
      </div>
    </div>,
    document.body
  );
}
