"use client";

import { useState, useEffect, useMemo, useTransition } from "react";
import type { MouseEvent } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  BadgeCheck,
  BarChart3,
  Bot,
  FlaskConical,
  Menu,
  Radio,
  Settings,
  ShieldCheck,
  Sparkles,
  X
} from "lucide-react";

const NAV_ITEMS = [
  { href: "/", label: "Command", description: "portfolio and runs", icon: BarChart3, group: "Operate" },
  { href: "/signals", label: "Signals", description: "capture and triage", icon: Radio, group: "Build" },
  { href: "/research", label: "Research", description: "test a thesis", icon: FlaskConical, group: "Build" },
  { href: "/bots", label: "Agents", description: "models, prompts, risk", icon: Bot, group: "Operate" },
  { href: "/pro", label: "Review", description: "live approvals", icon: ShieldCheck, group: "Govern" },
  { href: "/prompts", label: "Prompts", description: "version history", icon: BadgeCheck, group: "Govern" },
  { href: "/settings", label: "Settings", description: "sources and defaults", icon: Settings, group: "System" }
];

const GROUPS = ["Operate", "Build", "Govern", "System"] as const;

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pendingHref, setPendingHref] = useState<string | null>(null);
  const [, startTransition] = useTransition();

  useEffect(() => {
    setOpen(false);
    setPendingHref(null);
  }, [pathname]);

  const activeSection = useMemo(() => NAV_ITEMS.find((item) => (item.href === "/" ? pathname === "/" : pathname.startsWith(item.href))), [pathname]);

  const isActive = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  return (
    <>
      <button className="mobile-drawer-btn" onClick={() => setOpen((v) => !v)} aria-label="Toggle navigation">
        {open ? <X size={18} /> : <Menu size={18} />}
        <span>{open ? "Close" : "Menu"}</span>
      </button>
      <aside className={`sidebar-modern ${open ? "sidebar-open" : ""}`}>
        <Link href="/" className="sidebar-logo-modern" aria-label="Cosmu command">
          <span className="sidebar-mark"><Sparkles size={17} /></span>
          <span>
            <strong>cosmu</strong>
            <small>agent trading OS</small>
          </span>
        </Link>

        <nav className="sidebar-list" aria-label="Product">
          {GROUPS.map((group) => (
            <div className="sidebar-nav-group" key={group}>
              <span className="sidebar-group-title">{group}</span>
              {NAV_ITEMS.filter((item) => item.group === group).map((item) => {
                const Icon = item.icon;
                const active = isActive(item.href) || pendingHref === item.href;
                const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
                  if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
                  if (pathname === item.href) return;
                  event.preventDefault();
                  setPendingHref(item.href);
                  startTransition(() => router.push(item.href));
                };
                return (
                  <Link key={item.href} href={item.href} onClick={handleClick} className={`sidebar-item ${active ? "sidebar-item-active" : ""}`}>
                    <Icon size={17} />
                    <span><strong>{item.label}</strong><small>{item.description}</small></span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer-modern">
          <span>Current view</span>
          <strong>{activeSection?.label ?? "Command"}</strong>
        </div>
      </aside>
      {open ? <button className="sidebar-backdrop" aria-label="Close navigation" onClick={() => setOpen(false)} /> : null}
    </>
  );
}
