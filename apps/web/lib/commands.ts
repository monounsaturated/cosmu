// module: the canonical slash-command catalog. Cosmu's app is a glass cockpit — it SHOWS state and
// lets you steer; the DOING (author a strategy, run the gate, feed data) happens in Claude Code as
// runnable playbooks. This catalog is the single source of truth the cockpit reuses to surface
// "what to run, and when" inline — as hover modals on the relevant widget — instead of walls of prose.
// Mirrors .claude/skills/<name>/SKILL.md. Keep in sync when a skill is added/removed.

import {
  Bug,
  Database,
  FileCode2,
  FileText,
  Gavel,
  Landmark,
  Lightbulb,
  PlugZap,
  RefreshCw,
  Search,
  Sparkles,
  type LucideIcon
} from "lucide-react";

export interface Command {
  /** The slash command as typed in Claude Code, e.g. "/run-gate". */
  cmd: string;
  /** One line: what it does. */
  what: string;
  /** One line: when to reach for it. */
  when: string;
  icon: LucideIcon;
}

// Keyed by the slash command so a widget can pull the exact one it relates to.
export const COMMANDS: Record<string, Command> = {
  "/scan-signals": {
    cmd: "/scan-signals",
    icon: Search,
    what: "Unbiased sweep across every data source for weak / cross-asset signals → testable hypotheses, each with its disconfirmer.",
    when: "You want fresh edges to put on trial."
  },
  "/create-strategy": {
    cmd: "/create-strategy",
    icon: FileText,
    what: "Turn a thesis into a typed, auditable StrategySpec and drop it in the inbox for the next gated cohort.",
    when: "You have a concrete idea to test."
  },
  "/dump-idea": {
    cmd: "/dump-idea",
    icon: Lightbulb,
    what: "Capture a loose, natural-language idea as a typed spec in the inbox — same intake as the Idea inbox here.",
    when: "You have a vibe, not a full spec yet."
  },
  "/import-pine": {
    cmd: "/import-pine",
    icon: FileCode2,
    what: "TradingView Pine → typed spec. Hardcoded numbers become a fitted search space, never baked in.",
    when: "Porting a TradingView strategy."
  },
  "/add-data-source": {
    cmd: "/add-data-source",
    icon: Database,
    what: "Wire a new point-in-time data source end-to-end: provider → feature → ingest → test.",
    when: "A feed is stale or you want a new signal."
  },
  "/manage-data": {
    cmd: "/manage-data",
    icon: Database,
    what: "Fetch, backfill, and verify market bars + alt sources through one idempotent point-in-time path.",
    when: "Data looks thin, stale, or missing."
  },
  "/add-venue": {
    cmd: "/add-venue",
    icon: Landmark,
    what: "Wire a new exchange or asset class: adapter → catalog → universe gate → real per-venue fees.",
    when: "Adding somewhere to trade."
  },
  "/run-gate": {
    cmd: "/run-gate",
    icon: Gavel,
    what: "Run the deterministic real-data Gate and report the verdict: fund a Simulation track, or kill with reasons.",
    when: "Checking whether an edge is real, net of costs."
  },
  "/debug-strategy": {
    cmd: "/debug-strategy",
    icon: Bug,
    what: "Diagnose why a strategy isn't trading, isn't passing the Gate, or shows surprising numbers.",
    when: "A spec is inert, killed, or looks wrong."
  },
  "/deploy-check": {
    cmd: "/deploy-check",
    icon: PlugZap,
    what: "Run pnpm verify and confirm the tree is green and coherent before pushing (push = deploy).",
    when: "Before every push."
  },
  "/deploy-iterate": {
    cmd: "/deploy-iterate",
    icon: RefreshCw,
    what: "Read Railway / Vercel logs after a push, confirm the deploy is healthy, and iterate on failures.",
    when: "A deploy is failing or you're chasing a runtime error."
  },
  "/groom": {
    cmd: "/groom",
    icon: Sparkles,
    what: "Self-maintenance: prune dead code, graveyard stale strategies, keep docs + memory lean, verify green.",
    when: "Periodic cleanup so the system stays smart without bloating."
  }
};
