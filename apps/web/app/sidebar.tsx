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
  { href: "/", label: "Dashboard", description: "portfolio and runs", icon: BarChart3, group: "Cosmu" },
  { href: "/bots", label: "Agents", description: "create and tune", icon: Bot, group: "Cosmu" },
  { href: "/signals", label: "Signals", description: "capture and triage", icon: Radio, group: "Modules", toggleKey: "signals" },
  { href: "/research", label: "Research", description: "test a thesis", icon: FlaskConical, group: "Modules", toggleKey: "researchLab" },
  { href: "/pro", label: "Review", description: "live approvals", icon: ShieldCheck, group: "Modules", toggleKey: "proReview" },
  { href: "/prompts", label: "Prompts", description: "version history", icon: BadgeCheck, group: "Modules", toggleKey: "promptLibrary" },
  { href: "/settings", label: "Settings", description: "defaults and sources", icon: Settings, group: "Cosmu" }
];

const GROUPS = ["Cosmu", "Modules"] as const;

type FeatureToggles = {
  signals: boolean;
  researchLab: boolean;
  proReview: boolean;
  promptLibrary: boolean;
};

const DEFAULT_TOGGLES: FeatureToggles = {
  signals: false,
  researchLab: false,
  proReview: false,
  promptLibrary: false
};

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pendingHref, setPendingHref] = useState<string | null>(null);
  const [featureToggles, setFeatureToggles] = useState<FeatureToggles>(DEFAULT_TOGGLES);
  const [, startTransition] = useTransition();

  useEffect(() => {
    let cancelled = false;
    fetch("/api/settings/app", { cache: "no-store" })
      .then((res) => res.ok ? res.json() : null)
      .then((data) => {
        if (!cancelled && data?.featureToggles) {
          setFeatureToggles({ ...DEFAULT_TOGGLES, ...data.featureToggles });
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    setOpen(false);
    setPendingHref(null);
  }, [pathname]);

  const visibleItems = useMemo(() => {
    return NAV_ITEMS.filter((item) => !item.toggleKey || featureToggles[item.toggleKey as keyof FeatureToggles]);
  }, [featureToggles]);

  const activeSection = useMemo(() => visibleItems.find((item) => (item.href === "/" ? pathname === "/" : pathname.startsWith(item.href))), [pathname, visibleItems]);

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
          {GROUPS.filter((group) => visibleItems.some((item) => item.group === group)).map((group) => (
            <div className="sidebar-nav-group" key={group}>
              <span className="sidebar-group-title">{group}</span>
              {visibleItems.filter((item) => item.group === group).map((item) => {
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
