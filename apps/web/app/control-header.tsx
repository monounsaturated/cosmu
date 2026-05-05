"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import type { FormEvent, MouseEvent } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Activity, AlertTriangle, CheckCircle2, Command, FlaskConical, Shield } from "lucide-react";
import { ThemeToggle } from "./theme-toggle";

type Summary = {
  runningAgents: number;
  failedAgents: number;
  pendingApprovals: number;
  runningResearch: number;
  liveActionsGated?: boolean;
  cappedAutoliveEnabled?: boolean;
};

const MODES = [
  { href: "/", label: "Light" },
  { href: "/research", label: "Research" },
  { href: "/pro", label: "Pro" }
];

const labelForPath = (path: string) => {
  if (path.startsWith("/research")) return "Research";
  if (path.startsWith("/pro")) return "Pro";
  return "Light";
};

export function ControlHeader() {
  const pathname = usePathname();
  const router = useRouter();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [command, setCommand] = useState("");
  const [pendingPath, setPendingPath] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetch("/api/agent-control/summary", { cache: "no-store" })
        .then((res) => res.ok ? res.json() : null)
        .then((data) => {
          if (!cancelled && data) setSummary(data);
        })
        .catch(() => {
          if (!cancelled) setSummary(null);
        });
    };
    load();
    const timer = window.setInterval(load, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const currentMode = useMemo(() => labelForPath(pathname), [pathname]);
  const activeMode = useMemo(
    () => (pendingPath ? labelForPath(pendingPath) : currentMode),
    [pendingPath, currentMode]
  );

  useEffect(() => {
    if (pendingPath && pathname === pendingPath) setPendingPath(null);
  }, [pathname, pendingPath]);

  const submitCommand = (event: FormEvent) => {
    event.preventDefault();
    const q = command.trim();
    if (!q) return;
    router.push(`/research?command=${encodeURIComponent(q)}`);
    setCommand("");
  };

  return (
    <header className={`control-header ${isPending ? "control-header-pending" : ""}`}>
      <div className="mode-switch" aria-label="Workspace mode">
        {MODES.map((mode) => {
          const isActive = activeMode === mode.label;
          const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
            if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
            if (pathname === mode.href) return;
            event.preventDefault();
            setPendingPath(mode.href);
            startTransition(() => router.push(mode.href));
          };
          return (
            <Link
              key={mode.href}
              href={mode.href}
              prefetch
              onMouseEnter={() => router.prefetch(mode.href)}
              onClick={handleClick}
              className={`mode-tab ${isActive ? "mode-tab-active" : ""} ${pendingPath === mode.href ? "mode-tab-pending" : ""}`}
            >
              {mode.label}
            </Link>
          );
        })}
      </div>

      <form className="command-bar" onSubmit={submitCommand}>
        <Command size={16} />
        <input
          value={command}
          onChange={(event) => setCommand(event.target.value)}
          placeholder="Ask Cosmu to test a hypothesis, inspect agents, or create a paper bot..."
        />
      </form>

      <div className="control-status">
        <span title="Running agents"><Activity size={15} />{summary?.runningAgents ?? 0}</span>
        <span title="Running research jobs"><FlaskConical size={15} />{summary?.runningResearch ?? 0}</span>
        <span title="Failed agents in the last 24h" className={(summary?.failedAgents ?? 0) > 0 ? "status-danger" : ""}>
          <AlertTriangle size={15} />{summary?.failedAgents ?? 0}
        </span>
        <span title="Pending approvals"><Shield size={15} />{summary?.pendingApprovals ?? 0}</span>
        <span title={summary?.cappedAutoliveEnabled ? "Capped auto-live is enabled" : "Live actions approval-gated"}>
          <CheckCircle2 size={15} />
          {summary?.cappedAutoliveEnabled ? "Auto-live" : summary?.liveActionsGated === false ? "Ungated" : "Gated"}
        </span>
        <ThemeToggle />
      </div>
    </header>
  );
}
