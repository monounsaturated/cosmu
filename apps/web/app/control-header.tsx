"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import type { FormEvent } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Activity, AlertTriangle, Command, FlaskConical, Radio, Search, ShieldCheck } from "lucide-react";
import { ThemeToggle } from "./theme-toggle";

type Summary = {
  runningAgents: number;
  failedAgents: number;
  pendingApprovals: number;
  runningResearch: number;
  liveActionsGated?: boolean;
  cappedAutoliveEnabled?: boolean;
};

const labelForPath = (path: string) => {
  if (path.startsWith("/signals")) return "Signals";
  if (path.startsWith("/research")) return "Research";
  if (path.startsWith("/bots")) return "Agents";
  if (path.startsWith("/pro")) return "Review";
  if (path.startsWith("/prompts")) return "Prompts";
  if (path.startsWith("/settings")) return "Settings";
  return "Command";
};

export function ControlHeader() {
  const pathname = usePathname();
  const router = useRouter();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [command, setCommand] = useState("");
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

  const submitCommand = (event: FormEvent) => {
    event.preventDefault();
    const q = command.trim();
    if (!q) return;
    const target = /\b(signal|x|news|web|tweet|hot data)\b/i.test(q) ? "/signals" : "/research";
    router.push(`${target}?command=${encodeURIComponent(q)}`);
    setCommand("");
  };

  return (
    <header className={`control-header ${isPending ? "control-header-pending" : ""}`}>
      <div className="control-topline">
        <Link href="/" className="control-brand" aria-label="Cosmu home">
          <strong>cosmu</strong>
          <span>{currentMode}</span>
        </Link>

        <form className="command-bar" onSubmit={submitCommand}>
          <Search size={16} />
          <input
            value={command}
            onChange={(event) => setCommand(event.target.value)}
            placeholder="Paste a signal, thesis, or market note..."
          />
          <button type="submit" aria-label="Send command">
            <Command size={15} />
          </button>
        </form>

        <div className="control-status">
          <span title="Running agents"><Activity size={15} />{summary?.runningAgents ?? 0} agents</span>
          <span title="Running research jobs"><FlaskConical size={15} />{summary?.runningResearch ?? 0} labs</span>
          <span title="Failed agents in the last 24h" className={(summary?.failedAgents ?? 0) > 0 ? "status-danger" : ""}>
            <AlertTriangle size={15} />{summary?.failedAgents ?? 0} fails
          </span>
          <Link href="/signals" title="Signals"><Radio size={15} />Signals</Link>
          <Link href="/pro" title="Pending approvals"><ShieldCheck size={15} />{summary?.pendingApprovals ?? 0} review</Link>
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
