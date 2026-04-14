"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: "◈" },
  { href: "/bots", label: "Bots", icon: "⬡" },
  { href: "/prompts", label: "Prompts", icon: "✎" },
  { href: "/settings", label: "Settings", icon: "⚙" },
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

  const isBotPage = pathname.startsWith("/bots/");

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
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`sidebar-link ${isActive(item.href) && !isBotPage ? "sidebar-link-active" : ""}`}
            title={collapsed ? item.label : undefined}
          >
            <span className="sidebar-icon">{item.icon}</span>
            {!collapsed && <span>{item.label}</span>}
          </Link>
        ))}

        {isBotPage && !isActive("/bots") && (
          <div className="sidebar-link sidebar-link-active" title={collapsed ? "Bot Detail" : undefined}>
            <span className="sidebar-icon">⬡</span>
            {!collapsed && <span>Bot Detail</span>}
          </div>
        )}
      </nav>
    </aside>
  );
}
