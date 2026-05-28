"use client";

import { useMemo } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ThemeToggle } from "./theme-toggle";

const labelForPath = (path: string) => {
  if (path.startsWith("/trading-agents")) return "AI Hedge Fund";
  if (path.startsWith("/signals")) return "Signals";
  if (path.startsWith("/research")) return "Research";
  if (path.startsWith("/bots")) return "Agents";
  if (path.startsWith("/spending")) return "Spending";
  if (path.startsWith("/pro")) return "Review";
  if (path.startsWith("/prompts")) return "Prompts";
  if (path.startsWith("/settings")) return "Settings";
  return "Dashboard";
};

export function ControlHeader() {
  const pathname = usePathname();
  const currentMode = useMemo(() => labelForPath(pathname), [pathname]);

  return (
    <header className="control-header">
      <div className="control-topline">
        <Link href="/" className="control-brand" aria-label="Cosmu home">
          <strong>cosmu</strong>
          <span>{currentMode}</span>
        </Link>

        <div className="control-actions">
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
