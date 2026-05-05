"use client";

import { useState, useEffect, useTransition } from "react";
import type { MouseEvent } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Activity, Settings, ScrollText } from "lucide-react";

const NAV_ITEMS = [
  { href: "/prompts", label: "Prompts", icon: ScrollText },
  { href: "/settings", label: "Settings", icon: Settings },
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
