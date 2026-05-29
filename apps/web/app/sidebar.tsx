"use client";

import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BadgeCheck,
  BarChart3,
  Bot,
  Brain,
  ChevronUp,
  Database,
  DollarSign,
  Ellipsis,
  FlaskConical,
  Gauge,
  MessageSquare,
  Network,
  Radio,
  Settings,
  ShieldCheck,
  Sparkles
} from "lucide-react";

type FeatureToggles = {
  promptLab: boolean;
  sentiment: boolean;
  signals: boolean;
  researchLab: boolean;
  proReview: boolean;
  promptLibrary: boolean;
};

type NavItem = {
  href: string;
  label: string;
  description: string;
  icon: typeof BarChart3;
  group: "Core" | "Modules";
  featureKey?: keyof FeatureToggles;
};

const DEFAULT_FEATURE_TOGGLES: FeatureToggles = {
  promptLab: false,
  sentiment: false,
  signals: false,
  researchLab: false,
  proReview: false,
  promptLibrary: false
};

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", description: "agents, venues, spend", icon: Bot, group: "Core" },
  { href: "/prompts", label: "Prompts", description: "research and trader text", icon: BadgeCheck, group: "Core" },
  { href: "/spending", label: "Spend Detail", description: "token ledger", icon: DollarSign, group: "Core" },
  { href: "/settings", label: "Settings", description: "models, venues, modules", icon: Settings, group: "Core" },
  { href: "/prompt-lab", label: "Prompt Lab", description: "prompt experiments", icon: Brain, group: "Modules", featureKey: "promptLab" },
  { href: "/sentiment", label: "Sentiment", description: "market pulse", icon: Gauge, group: "Modules", featureKey: "sentiment" },
  { href: "/signals", label: "Signals", description: "capture and triage", icon: Radio, group: "Modules", featureKey: "signals" },
  { href: "/research", label: "Research", description: "framework tests", icon: FlaskConical, group: "Modules", featureKey: "researchLab" },
  { href: "/pro", label: "Review", description: "live approvals", icon: ShieldCheck, group: "Modules", featureKey: "proReview" }
] satisfies NavItem[];

const MOBILE_TABS = [
  { href: "/", label: "Dash", icon: Bot },
  { href: "/prompts", label: "Prompts", icon: BadgeCheck },
  { href: "/spending", label: "Spend", icon: DollarSign },
  { href: "/settings", label: "Settings", icon: Settings }
];

const GROUPS = ["Core", "Modules"] as const;

const SIDEBAR_MIN = 200;
const SIDEBAR_MAX = 400;
const SIDEBAR_DEFAULT = 256;
const SIDEBAR_STORAGE_KEY = "cosmu-sidebar-width";

export function Sidebar() {
  const pathname = usePathname();
  const [moreOpen, setMoreOpen] = useState(false);
  const [pendingHref, setPendingHref] = useState<string | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(SIDEBAR_DEFAULT);
  const [featureToggles, setFeatureToggles] = useState<FeatureToggles>(DEFAULT_FEATURE_TOGGLES);
  const dragging = useRef(false);
  const sidebarRef = useRef<HTMLElement>(null);

  useEffect(() => {
    try {
      const saved = localStorage.getItem(SIDEBAR_STORAGE_KEY);
      if (saved) {
        const w = Number(saved);
        if (w >= SIDEBAR_MIN && w <= SIDEBAR_MAX) setSidebarWidth(w);
      }
    } catch {}
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/settings/app", { cache: "no-store" })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (cancelled) return;
        setFeatureToggles({
          ...DEFAULT_FEATURE_TOGGLES,
          ...(data?.featureToggles ?? {})
        });
      })
      .catch(() => {
        if (!cancelled) setFeatureToggles(DEFAULT_FEATURE_TOGGLES);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const onDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const onMove = (ev: MouseEvent) => {
      if (!dragging.current) return;
      const w = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, ev.clientX));
      setSidebarWidth(w);
    };
    const onUp = () => {
      dragging.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      if (sidebarRef.current) {
        const finalW = sidebarRef.current.offsetWidth;
        try { localStorage.setItem(SIDEBAR_STORAGE_KEY, String(finalW)); } catch {}
      }
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
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
      <aside className="sidebar-modern" ref={sidebarRef} style={{ width: sidebarWidth }}>
        <div className="sidebar-resize-handle" onMouseDown={onDragStart} />
        <Link href="/" className="sidebar-logo-modern" aria-label="Cosmu home">
          <span className="sidebar-mark"><Sparkles size={16} /></span>
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
                    <span><strong>{item.label}</strong><small>{item.description}</small></span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="sidebar-platform-note">
          <span><Database size={14} /> data</span>
          <span><Network size={14} /> frameworks</span>
          <span><Brain size={14} /> memory</span>
          <span><MessageSquare size={14} /> chat</span>
        </div>
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
