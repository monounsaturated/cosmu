"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, AlertTriangle } from "lucide-react";
import { ThemeToggle } from "./theme-toggle";

type Summary = {
  runningAgents: number;
  failedAgents: number;
  pendingApprovals: number;
  runningResearch: number;
};

const labelForPath = (path: string) => {
  if (path.startsWith("/trading-agents")) return "AI Hedge Fund";
  if (path.startsWith("/signals")) return "Signals";
  if (path.startsWith("/research")) return "Research";
  if (path.startsWith("/bots")) return "Agents";
  if (path.startsWith("/pro")) return "Review";
  if (path.startsWith("/prompts")) return "Prompts";
  if (path.startsWith("/settings")) return "Settings";
  return "Dashboard";
};

export function ControlHeader() {
  const pathname = usePathname();
  const [summary, setSummary] = useState<Summary | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetch("/api/agent-control/summary", { cache: "no-store" })
        .then((res) => res.ok ? res.json() : null)
        .then((data) => { if (!cancelled && data) setSummary(data); })
        .catch(() => { if (!cancelled) setSummary(null); });
    };
    load();
    const timer = window.setInterval(load, 15000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  const currentMode = useMemo(() => labelForPath(pathname), [pathname]);

  return (
    <header className="control-header">
      <div className="control-topline">
        <Link href="/" className="control-brand" aria-label="Cosmu home">
          <strong>cosmu</strong>
          <span>{currentMode}</span>
        </Link>

        <div className="control-status">
          <span title="Running agents">
            <Activity size={14} />
            {summary?.runningAgents ?? 0} active
          </span>
          <span
            title="Failed agents"
            className={(summary?.failedAgents ?? 0) > 0 ? "status-danger" : ""}
          >
            <AlertTriangle size={14} />
            {summary?.failedAgents ?? 0} fails
          </span>
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
