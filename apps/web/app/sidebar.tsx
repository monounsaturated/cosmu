"use client";

import { useState, useEffect, useMemo } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BadgeCheck,
  BarChart3,
  Bot,
  Brain,
  ChevronUp,
  DollarSign,
  Ellipsis,
  FlaskConical,
  Gauge,
  Radio,
  Settings
} from "lucide-react";
import { defaultFeatureToggles, type AppSettings } from "@cosmu/shared";
import { CosmuMark } from "./cosmu-mark";

type FeatureToggles = AppSettings["featureToggles"];

type NavItem = {
  href: string;
  label: string;
  description: string;
  icon: typeof BarChart3;
  group: "Core" | "Modules";
  featureKey?: keyof FeatureToggles;
};

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", description: "agents, venues, spend", icon: Bot, group: "Core" },
  { href: "/prompts", label: "Prompts", description: "research and trader text", icon: BadgeCheck, group: "Core" },
  { href: "/spending", label: "Spend Detail", description: "token ledger", icon: DollarSign, group: "Core" },
  { href: "/settings", label: "Settings", description: "models, venues, modules", icon: Settings, group: "Core" },
  { href: "/prompt-lab", label: "Prompt Lab", description: "prompt experiments", icon: Brain, group: "Modules", featureKey: "promptLab" },
  { href: "/sentiment", label: "Sentiment", description: "market pulse", icon: Gauge, group: "Modules", featureKey: "sentiment" },
  { href: "/signals", label: "Signals", description: "capture and triage", icon: Radio, group: "Modules", featureKey: "signals" },
  { href: "/research", label: "Research", description: "framework tests", icon: FlaskConical, group: "Modules", featureKey: "researchLab" }
] satisfies NavItem[];

const MOBILE_TABS = [
  { href: "/", label: "Dash", icon: Bot },
  { href: "/prompts", label: "Prompts", icon: BadgeCheck },
  { href: "/spending", label: "Spend", icon: DollarSign },
  { href: "/settings", label: "Settings", icon: Settings }
];

const GROUPS = ["Core", "Modules"] as const;

export function Sidebar() {
  const pathname = usePathname();
  const [moreOpen, setMoreOpen] = useState(false);
  const [pendingHref, setPendingHref] = useState<string | null>(null);
  const [featureToggles, setFeatureToggles] = useState<FeatureToggles>(defaultFeatureToggles);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/settings/app", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (cancelled) return;
        setFeatureToggles({
          ...defaultFeatureToggles,
          ...(data?.featureToggles ?? {})
        });
      })
      .catch(() => {
        if (!cancelled) setFeatureToggles(defaultFeatureToggles);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    setMoreOpen(false);
    setPendingHref(null);
  }, [pathname]);

  const visibleItems = useMemo(
    () => NAV_ITEMS.filter((item) => !item.featureKey || featureToggles[item.featureKey]),
    [featureToggles]
  );
  const mobileExtraItems = useMemo(() => visibleItems.filter((item) => !MOBILE_TABS.some((tab) => tab.href === item.href)), [visibleItems]);

  const isActive = (href: string) => (href === "/" ? pathname === "/" || pathname.startsWith("/bots") : pathname.startsWith(href));

  const handleNavClick = (href: string) => {
    setPendingHref(href);
    setMoreOpen(false);
  };

  return (
    <>
      <aside className="sidebar-modern">
        <Link href="/" className="sidebar-logo-modern" aria-label="Cosmu home">
          <span className="sidebar-mark"><CosmuMark size={16} /></span>
          <span>
            <strong>cosmu</strong>
            <small>trading agents</small>
          </span>
        </Link>

        <nav className="sidebar-list" aria-label="Navigation">
          {GROUPS.filter((group) => visibleItems.some((item) => item.group === group)).map((group) => (
            <div className="sidebar-nav-group" key={group}>
              <span className="sidebar-group-title">{group === "Core" ? "Operate" : "Enabled Modules"}</span>
              {visibleItems.filter((item) => item.group === group).map((item) => {
                const Icon = item.icon;
                const active = isActive(item.href) || pendingHref === item.href;
                return (
                  <Link key={item.href} href={item.href} onClick={() => handleNavClick(item.href)} className={`sidebar-item ${active ? "sidebar-item-active" : ""}`}>
                    <Icon size={18} />
                    <span><strong>{item.label}</strong></span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
      </aside>

      <nav className="mobile-tab-bar" aria-label="Mobile navigation">
        {MOBILE_TABS.map((tab) => {
          const Icon = tab.icon;
          const active = isActive(tab.href);
          return (
            <Link key={tab.href} href={tab.href} onClick={() => handleNavClick(tab.href)} className={`mobile-tab-item ${active ? "mobile-tab-item-active" : ""}`}>
              <Icon size={22} />
              <span>{tab.label}</span>
            </Link>
          );
        })}
        {mobileExtraItems.length > 0 ? (
          <button
            type="button"
            className={`mobile-tab-item mobile-more-trigger ${moreOpen ? "mobile-tab-item-active" : ""}`}
            onClick={() => setMoreOpen((value) => !value)}
            aria-expanded={moreOpen}
            aria-label="More navigation"
          >
            {moreOpen ? <ChevronUp size={22} /> : <Ellipsis size={22} />}
            <span>More</span>
          </button>
        ) : null}
      </nav>

      {moreOpen ? (
        <>
          <button className="mobile-more-backdrop" aria-label="Close more menu" onClick={() => setMoreOpen(false)} />
          <div className="mobile-more-sheet">
            <div className="mobile-more-handle" />
            <strong>More</strong>
            <div className="mobile-more-list">
              {mobileExtraItems.map((item) => {
                const Icon = item.icon;
                const active = isActive(item.href);
                return (
                  <Link key={item.href} href={item.href} onClick={() => handleNavClick(item.href)} className={`mobile-more-item ${active ? "mobile-more-item-active" : ""}`}>
                    <Icon size={18} />
                    <span>
                      <strong>{item.label}</strong>
                      <small>{item.description}</small>
                    </span>
                  </Link>
                );
              })}
            </div>
          </div>
        </>
      ) : null}
    </>
  );
}
