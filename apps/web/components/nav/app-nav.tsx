"use client";

// module: app navigation. Desktop = persistent icon-rail sidebar (full list). Mobile = a native-
// feeling bottom tab bar with at most 5 targets: the primary monitoring tabs plus a "More" sheet
// that holds the rest. Links are real routes only (no #anchors), with active-state highlighting via
// the current path. Live is surfaced in the dock (vs. tucked in More) only when it is actually armed.

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import {
  LayoutDashboard,
  ListChecks,
  Microscope,
  MoreHorizontal,
  Radio,
  SlidersHorizontal,
  Wallet,
  X
} from "lucide-react";
import { cn } from "@/lib/utils";

// One route per user question. `gated` items are kept deliberately dimmed (live trading is in
// scope but off by default — the screen stays lean and the gate must pass before anything arms).
type NavItem = { href: string; label: string; icon: typeof LayoutDashboard; gated?: boolean };

export const navItems: NavItem[] = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/lab", label: "Lab", icon: Microscope },
  { href: "/strategies", label: "Strategies", icon: ListChecks },
  { href: "/paper", label: "Paper", icon: Wallet },
  { href: "/live", label: "Live", icon: Radio, gated: true },
  { href: "/settings", label: "Settings", icon: SlidersHorizontal }
];

// Mobile dock: the four primary monitoring tabs always pinned; everything else lives in the More
// sheet. Live joins the dock (5th tab) only when armed — see BottomNav.
const PRIMARY_HREFS = ["/", "/lab", "/strategies", "/paper"];
const primaryItems = navItems.filter((i) => PRIMARY_HREFS.includes(i.href));
const liveItem = navItems.find((i) => i.href === "/live")!;
// The More sheet holds the rest (Live, Steer, Costs, Settings) — i.e. anything not a primary tab.
const moreItems = navItems.filter((i) => !PRIMARY_HREFS.includes(i.href));

const ENGINE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  // Strategy detail pages are browsed from Strategies, so keep Strategies highlighted there.
  if (href === "/strategies") return pathname.startsWith("/strategies") || pathname.startsWith("/strategy");
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

// Honest live-armed probe. Defaults to NOT armed and only flips true on a confirmed engine
// response — never fabricates an armed state. When the engine is unreachable, Live stays in the
// More sheet (not the dock), matching the rest of the app's honest not-connected behaviour.
function useLiveArmed(): boolean {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!ENGINE) return;
    let alive = true;
    async function probe() {
      try {
        const res = await fetch(`${ENGINE}/autonomy/status`);
        if (!res.ok) return;
        const data = (await res.json()) as { live_enabled?: boolean };
        if (alive) setArmed(Boolean(data.live_enabled));
      } catch {
        /* honest: stay not-armed */
      }
    }
    probe();
    const id = setInterval(probe, 15000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);
  return armed;
}

// A single dock tab — large (>=44px high overall row, ~56px) tap target, clear active state.
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
          active ? "bg-iris/15" : "bg-transparent"
        )}
      >
        <Icon className={cn("size-[20px] shrink-0 transition-colors", active ? "text-iris-soft" : "text-quiet")} />
      </span>
      <span className={cn("text-[10px] font-medium transition-colors", active ? "text-iris-soft" : "text-quiet")}>{item.label}</span>
    </span>
  );
  const className = cn(
    "flex min-h-[56px] items-center justify-center px-0.5 transition-colors",
    !active && "hover:text-foreground",
    item.gated && !active && "opacity-80"
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

// Mobile primary navigation: a fixed bottom tab bar. Default = five targets (four primary tabs +
// More). When Live is armed it earns its own dock tab so the operator can watch real-money trading
// one tap away; the bar then shows six cells (primary x4 + Live + More) and Live drops out of the
// More sheet. Off by default → Live stays in More, keeping the dock at a lean five.
export function BottomNav() {
  const pathname = usePathname();
  const armed = useLiveArmed();
  const [sheetOpen, setSheetOpen] = useState(false);

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

  // The 5th dock cell is Live only when armed; the More trigger is always the final cell.
  const fifth = armed ? liveItem : null;

  return (
    <>
      <nav
        aria-label="Primary"
        className={cn(
          "glass fixed inset-x-0 bottom-0 z-30 grid border-t border-border/70 pb-[env(safe-area-inset-bottom)] lg:hidden",
          fifth ? "grid-cols-6" : "grid-cols-5"
        )}
      >
        {primaryItems.map((item) => (
          <DockTab key={item.href} item={item} active={isActive(pathname, item.href)} />
        ))}
        {fifth ? <DockTab item={fifth} active={isActive(pathname, fifth.href)} /> : null}
        <DockTab
          item={{ label: "More", icon: MoreHorizontal }}
          active={sheetOpen || moreItems.some((i) => i.href !== "/live" && isActive(pathname, i.href)) || (!armed && isActive(pathname, "/live"))}
          onClick={() => setSheetOpen(true)}
        />
      </nav>

      <MoreSheet open={sheetOpen} onClose={() => setSheetOpen(false)} pathname={pathname} armed={armed} />
    </>
  );
}

// Bottom sheet holding the secondary routes. Smooth slide-up, scrim, safe-area aware, reduced-motion
// respected (the transition collapses to an opacity fade when the user prefers reduced motion).
function MoreSheet({
  open,
  onClose,
  pathname,
  armed
}: {
  open: boolean;
  onClose: () => void;
  pathname: string;
  armed: boolean;
}) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return null;

  // When Live is already in the dock (armed) it doesn't need a second entry in the sheet.
  const sheetItems = armed ? moreItems.filter((i) => i.href !== "/live") : moreItems;

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
          {sheetItems.map((item) => {
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
                  active ? "border-border bg-surface-2/70 text-foreground" : "border-border/60 bg-surface-2/30 text-muted hover:bg-surface-2/55 hover:text-foreground",
                  item.gated && !active && "text-quiet"
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
