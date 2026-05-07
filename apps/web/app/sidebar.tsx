"use client";

import { useState, useEffect, useMemo, useTransition } from "react";
import type { MouseEvent } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  BadgeCheck,
  BarChart3,
  Bot,
  Brain,
  FlaskConical,
  Gauge,
  LayoutGrid,
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
  { href: "/trading-agents", label: "Trading Agents", description: "AI hedge fund", icon: LayoutGrid, group: "Cosmu" },
  { href: "/prompt-lab", label: "Prompt Lab", description: "iterate and optimize", icon: Brain, group: "Cosmu" },
  { href: "/sentiment", label: "Sentiment", description: "market pulse", icon: Gauge, group: "Cosmu" },
  { href: "/signals", label: "Signals", description: "capture and triage", icon: Radio, group: "Modules", toggleKey: "signals" },
  { href: "/research", label: "Research", description: "test a thesis", icon: FlaskConical, group: "Modules", toggleKey: "researchLab" },
  { href: "/pro", label: "Review", description: "live approvals", icon: ShieldCheck, group: "Modules", toggleKey: "proReview" },
  { href: "/prompts", label: "Prompts", description: "version history", icon: BadgeCheck, group: "Modules", toggleKey: "promptLibrary" },
  { href: "/settings", label: "Settings", description: "defaults and sources", icon: Settings, group: "Cosmu" }
];

const MOBILE_TABS = [
  { href: "/", label: "Home", icon: BarChart3 },
  { href: "/bots", label: "Agents", icon: Bot },
  { href: "/trading-agents", label: "AI Fund", icon: LayoutGrid },
  { href: "/settings", label: "Settings", icon: Settings }
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

  const handleNavClick = (href: string) => (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    if (pathname === href) return;
    event.preventDefault();
    setPendingHref(href);
    startTransition(() => router.push(href));
  };

  return (
    <>
      {/* Tablet drawer toggle */}
      <button className="mobile-drawer-btn" onClick={() => setOpen((v) => !v)} aria-label="Toggle navigation">
        {open ? <X size={18} /> : <Menu size={18} />}
        <span>{open ? "Close" : "Menu"}</span>
      </button>

      {/* Desktop + tablet sidebar */}
      <aside className={`sidebar-modern ${open ? "sidebar-open" : ""}`}>
        <Link href="/" className="sidebar-logo-modern" aria-label="Cosmu home">
          <span className="sidebar-mark"><Sparkles size={16} /></span>
          <span>
            <strong>cosmu</strong>
            <small>trading OS</small>
          </span>
        </Link>

        <nav className="sidebar-list" aria-label="Navigation">
          {GROUPS.filter((group) => visibleItems.some((item) => item.group === group)).map((group) => (
            <div className="sidebar-nav-group" key={group}>
              <span className="sidebar-group-title">{group}</span>
              {visibleItems.filter((item) => item.group === group).map((item) => {
                const Icon = item.icon;
                const active = isActive(item.href) || pendingHref === item.href;
                return (
                  <Link key={item.href} href={item.href} onClick={handleNavClick(item.href)} className={`sidebar-item ${active ? "sidebar-item-active" : ""}`}>
                    <Icon size={18} />
                    <span><strong>{item.label}</strong><small>{item.description}</small></span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer-modern">
          <span>Current view</span>
          <strong>{activeSection?.label ?? "Dashboard"}</strong>
        </div>
      </aside>

      {/* Tablet backdrop */}
      {open ? <button className="sidebar-backdrop" aria-label="Close navigation" onClick={() => setOpen(false)} /> : null}

      {/* Mobile bottom tab bar */}
      <nav className="mobile-tab-bar" aria-label="Mobile navigation">
        {MOBILE_TABS.map((tab) => {
          const Icon = tab.icon;
          const active = isActive(tab.href);
          return (
            <Link key={tab.href} href={tab.href} onClick={handleNavClick(tab.href)} className={`mobile-tab-item ${active ? "mobile-tab-item-active" : ""}`}>
              <Icon size={22} />
              <span>{tab.label}</span>
            </Link>
          );
        })}
      </nav>
    </>
  );
}
