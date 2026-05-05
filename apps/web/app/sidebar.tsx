"use client";

import { useState, useEffect, useMemo, useTransition } from "react";
import type { MouseEvent } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Activity, BarChart3, Bot, FlaskConical, Radio, Settings, ShieldCheck, ScrollText } from "lucide-react";

const NAV_GROUPS = [
  {
    label: "Operate",
    items: [
      { href: "/", label: "Trader", description: "Light bots", icon: BarChart3 },
      { href: "/signals", label: "Signals", description: "Hot data", icon: Radio },
      { href: "/research", label: "Research", description: "Strategy lab", icon: FlaskConical },
      { href: "/pro", label: "Pro", description: "Live approvals", icon: ShieldCheck }
    ]
  },
  {
    label: "Configure",
    items: [
      { href: "/bots", label: "Agents", description: "All bot configs", icon: Bot },
      { href: "/prompts", label: "Prompts", description: "Versioned text", icon: ScrollText },
      { href: "/settings", label: "Settings", description: "Defaults", icon: Settings }
    ]
  }
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [collapsed, setCollapsed] = useState(false);
  const [pendingHref, setPendingHref] = useState<string | null>(null);
  const [, startTransition] = useTransition();

  useEffect(() => {
    if (pendingHref && pathname.startsWith(pendingHref)) setPendingHref(null);
  }, [pathname, pendingHref]);

  useEffect(() => {
    const saved = localStorage.getItem("sidebar-collapsed");
    if (saved === "true") setCollapsed(true);
  }, []);

  const toggle = () => {
    const next = !collapsed;
    setCollapsed(next);
    localStorage.setItem("sidebar-collapsed", String(next));
  };

  const isActive = (href: string) => {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  };

  const isBotDetailPage = pathname.startsWith("/bots/");
  const activeSection = useMemo(() => {
    if (pathname.startsWith("/signals")) return "Signal Sentinel";
    if (pathname.startsWith("/research")) return "Research Lab";
    if (pathname.startsWith("/pro")) return "Cosmu Pro";
    if (pathname.startsWith("/bots")) return "Agent Config";
    if (pathname.startsWith("/prompts")) return "Prompt Library";
    if (pathname.startsWith("/settings")) return "Control Room";
    return "Trader Cockpit";
  }, [pathname]);

  return (
    <aside className={`sidebar ${collapsed ? "sidebar-collapsed" : ""}`}>
      <div className="sidebar-header">
        {!collapsed && (
          <Link href="/" className="sidebar-logo">
            cosmu
          </Link>
        )}
        <button className="sidebar-toggle" onClick={toggle} aria-label="Toggle sidebar">
          {collapsed ? "▸" : "◂"}
        </button>
      </div>

      <nav className="sidebar-nav">
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="sidebar-group">
            {!collapsed && <span className="sidebar-group-label">{group.label}</span>}
            {group.items.map((item) => {
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
                <Link
                  key={item.href}
                  href={item.href}
                  prefetch
                  onMouseEnter={() => router.prefetch(item.href)}
                  onClick={handleClick}
                  className={`sidebar-link ${active ? "sidebar-link-active" : ""}`}
                  title={collapsed ? `${item.label} - ${item.description}` : undefined}
                >
                  <span className="sidebar-icon"><Icon size={17} /></span>
                  {!collapsed && (
                    <span className="sidebar-link-copy">
                      <strong>{item.label}</strong>
                      <small>{item.description}</small>
                    </span>
                  )}
                </Link>
              );
            })}
          </div>
        ))}

        {isBotDetailPage && (
          <div className="sidebar-link sidebar-link-active" title={collapsed ? "Agent Detail" : undefined}>
            <span className="sidebar-icon"><Activity size={17} /></span>
            {!collapsed && <span>Agent Detail</span>}
          </div>
        )}
      </nav>
      {!collapsed && (
        <div className="sidebar-context">
          <span>Now viewing</span>
          <strong>{activeSection}</strong>
          <small>Use the top command bar to send a thesis to Signals or Research.</small>
        </div>
      )}
    </aside>
  );
}
