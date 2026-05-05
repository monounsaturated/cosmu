"use client";

import { useState, useEffect, useMemo, useTransition } from "react";
import type { MouseEvent } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Menu, X, BarChart3, Bot, FlaskConical, Radio, Settings, ShieldCheck, ScrollText } from "lucide-react";

const NAV_ITEMS = [
  { href: "/", label: "Trader", description: "Portfolio + automation", icon: BarChart3 },
  { href: "/signals", label: "Signals", description: "Capture & triage", icon: Radio },
  { href: "/research", label: "Research", description: "Experiment workflows", icon: FlaskConical },
  { href: "/pro", label: "Approvals", description: "Human-in-the-loop", icon: ShieldCheck },
  { href: "/bots", label: "Agents", description: "Configure everything", icon: Bot },
  { href: "/prompts", label: "Prompts", description: "Versioned instructions", icon: ScrollText },
  { href: "/settings", label: "Settings", description: "Models + defaults", icon: Settings }
];

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
        {open ? <X size={18} /> : <Menu size={18} />} {open ? "Close" : "Menu"}
      </button>
      <aside className={`sidebar-modern ${open ? "sidebar-open" : ""}`}>
        <Link href="/" className="sidebar-logo-modern">cosmu</Link>
        <p className="sidebar-subtitle">A cleaner operator-first cockpit.</p>

        <nav className="sidebar-list">
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
              <Link key={item.href} href={item.href} onClick={handleClick} className={`sidebar-item ${active ? "sidebar-item-active" : ""}`}>
                <Icon size={16} />
                <span><strong>{item.label}</strong><small>{item.description}</small></span>
              </Link>
            );
          })}
        </nav>

        <div className="sidebar-footer-modern">
          <span>Current view</span>
          <strong>{activeSection?.label ?? "Trader"}</strong>
        </div>
      </aside>
      {open ? <button className="sidebar-backdrop" aria-label="Close navigation" onClick={() => setOpen(false)} /> : null}
    </>
  );
}
