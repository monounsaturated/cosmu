"use client";

import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Activity, AlertTriangle, CheckCircle2, Command, FlaskConical, Shield } from "lucide-react";

type Summary = {
  runningAgents: number;
  failedAgents: number;
  pendingApprovals: number;
  runningResearch: number;
};

const MODES = [
  { href: "/", label: "Light" },
  { href: "/research", label: "Research" },
  { href: "/pro", label: "Pro" }
];

export function ControlHeader() {
  const pathname = usePathname();
  const router = useRouter();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [command, setCommand] = useState("");

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

  const activeMode = useMemo(() => {
    if (pathname.startsWith("/research")) return "Research";
    if (pathname.startsWith("/pro")) return "Pro";
    return "Light";
  }, [pathname]);

  const submitCommand = (event: FormEvent) => {
    event.preventDefault();
    const q = command.trim();
    if (!q) return;
    router.push(`/research?command=${encodeURIComponent(q)}`);
    setCommand("");
  };

  return (
    <header className="control-header">
      <div className="mode-switch" aria-label="Workspace mode">
        {MODES.map((mode) => (
          <Link
            key={mode.href}
            href={mode.href}
            className={`mode-tab ${activeMode === mode.label ? "mode-tab-active" : ""}`}
          >
            {mode.label}
          </Link>
        ))}
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
        <span title="Live actions approval-gated"><CheckCircle2 size={15} />Gated</span>
      </div>
    </header>
  );
}
