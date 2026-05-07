"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import type { FormEvent } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Activity, AlertTriangle, Search } from "lucide-react";
import { ThemeToggle } from "./theme-toggle";

type Summary = {
  runningAgents: number;
  failedAgents: number;
  pendingApprovals: number;
  runningResearch: number;
};

type FeatureToggles = {
  signals: boolean;
  researchLab: boolean;
  proReview: boolean;
  promptLibrary: boolean;
};

const DEFAULT_TOGGLES: FeatureToggles = {
  signals: false,
  researchLab: false,
  proReview: false,
  promptLibrary: false
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
  const router = useRouter();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [featureToggles, setFeatureToggles] = useState<FeatureToggles>(DEFAULT_TOGGLES);
  const [command, setCommand] = useState("");
  const [isPending, startTransition] = useTransition();

  useEffect(() => {
    let cancelled = false;
    fetch("/api/settings/app", { cache: "no-store" })
      .then((res) => res.ok ? res.json() : null)
      .then((data) => {
        if (!cancelled && data?.featureToggles) {
          setFeatureToggles({ ...DEFAULT_TOGGLES, ...data.featureToggles });
        }
      })
      .catch(() => {});
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

  const submitCommand = (event: FormEvent) => {
    event.preventDefault();
    const q = command.trim();
    if (!q) return;
    const target =
      featureToggles.signals && /\b(signal|x|news|web|tweet|hot data)\b/i.test(q)
        ? "/signals"
        : featureToggles.researchLab
          ? "/research"
          : "/bots";
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
          <Search size={15} />
          <input
            value={command}
            onChange={(event) => setCommand(event.target.value)}
            placeholder="Search or paste a thesis..."
          />
        </form>

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
