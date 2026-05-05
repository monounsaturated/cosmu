"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import type { FormEvent, MouseEvent } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Activity, AlertTriangle, Bot, Command, FlaskConical, Radio, Settings, ShieldCheck } from "lucide-react";
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
  { href: "/", label: "Trader", description: "bots and PnL", icon: Activity },
  { href: "/signals", label: "Signals", description: "capture and triage", icon: Radio },
  { href: "/research", label: "Research", description: "test a thesis", icon: FlaskConical },
  { href: "/bots", label: "Agents", description: "configure bots", icon: Bot }
];

const UTILITY_LINKS = [
  { href: "/pro", label: "Approvals" },
  { href: "/prompts", label: "Prompts" },
  { href: "/settings", label: "Settings" }
];

const labelForPath = (path: string) => {
  if (path.startsWith("/signals")) return "Signals";
  if (path.startsWith("/research")) return "Research";
  if (path.startsWith("/bots")) return "Agents";
  if (path.startsWith("/pro")) return "Approvals";
  return "Trader";
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
    const target = /\b(signal|x|news|web|tweet|hot data)\b/i.test(q) ? "/signals" : "/research";
    router.push(`${target}?command=${encodeURIComponent(q)}`);
    setCommand("");
  };

  return (
    <header className={`control-header ${isPending ? "control-header-pending" : ""}`}>
      <div className="control-topline">
        <Link href="/" className="control-brand" aria-label="Cosmu home">
          <strong>cosmu</strong>
          <span>signal to strategy to bot</span>
        </Link>
        <div className="control-utilities">
          {UTILITY_LINKS.map((link) => (
            <Link key={link.href} href={link.href} className={pathname.startsWith(link.href) ? "utility-link utility-link-active" : "utility-link"}>
              {link.href === "/settings" && <Settings size={14} />}
              {link.label}
            </Link>
          ))}
          <ThemeToggle />
        </div>
      </div>

      <div className="control-mainline">
        <nav className="mode-switch" aria-label="Primary workflow">
          {MODES.map((mode) => {
            const Icon = mode.icon;
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
                <Icon size={16} />
                <span>
                  <strong>{mode.label}</strong>
                  <small>{mode.description}</small>
                </span>
              </Link>
            );
          })}
        </nav>

        <form className="command-bar" onSubmit={submitCommand}>
          <Command size={16} />
          <input
            value={command}
            onChange={(event) => setCommand(event.target.value)}
            placeholder="Paste a market observation or thesis..."
          />
        </form>

        <div className="control-status">
          <span title="Running agents"><Activity size={15} />{summary?.runningAgents ?? 0}</span>
          <span title="Running research jobs"><FlaskConical size={15} />{summary?.runningResearch ?? 0}</span>
          <span title="Failed agents in the last 24h" className={(summary?.failedAgents ?? 0) > 0 ? "status-danger" : ""}>
            <AlertTriangle size={15} />{summary?.failedAgents ?? 0}
          </span>
          <span title="Pending approvals"><ShieldCheck size={15} />{summary?.pendingApprovals ?? 0}</span>
        </div>
      </div>
    </header>
  );
}
