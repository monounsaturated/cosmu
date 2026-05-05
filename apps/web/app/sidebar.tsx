"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Settings, ScrollText } from "lucide-react";

const NAV_ITEMS = [
  { href: "/prompts", label: "Prompts", icon: ScrollText },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

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
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`sidebar-link ${isActive(item.href) ? "sidebar-link-active" : ""}`}
              title={collapsed ? item.label : undefined}
            >
              <span className="sidebar-icon"><Icon size={17} /></span>
              {!collapsed && <span>{item.label}</span>}
            </Link>
          );
        })}

        {isBotDetailPage && (
          <div className="sidebar-link sidebar-link-active" title={collapsed ? "Agent Detail" : undefined}>
            <span className="sidebar-icon"><Activity size={17} /></span>
            {!collapsed && <span>Agent Detail</span>}
          </div>
        )}
      </nav>
    </aside>
  );
}
