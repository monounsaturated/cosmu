// module: Commands — the canonical "how to drive Cosmu from Claude Code" reference. The app is the glass
// cockpit (it SHOWS everything and lets you approve/steer); the DOING — adding data, importing strategies,
// running the gate, deploying — happens in Claude Code as runnable playbooks (skills). This page is a
// plain-language CATALOG of those actions, grouped by lifecycle stage, so the operator always knows what
// they can run and when. Pure static render (no engine calls) — works offline, never moves money.
// Source of truth: .claude/skills/<name>/SKILL.md. Keep this list in sync when a skill is added/removed.

import {
  Bug,
  Database,
  FileCode2,
  FileText,
  Gavel,
  Landmark,
  Layers,
  PlugZap,
  RefreshCw,
  Rocket,
  Search,
  Sparkles,
  Terminal
} from "lucide-react";
import type { ComponentType } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SectionHeader } from "@/components/ui/section";

type Cmd = { cmd: string; what: string; when: string; icon: ComponentType<{ className?: string }> };
type Group = { stage: string; blurb: string; cmds: Cmd[] };

// Mirrors the runnable playbooks in .claude/skills/. Keep in sync when a skill is added/removed.
const GROUPS: Group[] = [
  {
    stage: "Discover",
    blurb: "Find and shape ideas. Everything here only PROPOSES — the Gate decides what's real.",
    cmds: [
      {
        cmd: "/scan-signals",
        icon: Search,
        what: "Unbiased sweep across every data source for weak / cross-asset signals → testable hypotheses, each with the evidence against it.",
        when: "You want fresh edges to test."
      },
      {
        cmd: "/create-strategy",
        icon: FileText,
        what: "Turn a thesis or idea into a typed, auditable StrategySpec and drop it in the inbox.",
        when: "You have an idea to put on trial."
      },
      {
        cmd: "/import-pine",
        icon: FileCode2,
        what: "TradingView Pine → typed spec. Hardcoded numbers become a fitted search space, never baked in.",
        when: "Porting a TradingView strategy."
      }
    ]
  },
  {
    stage: "Data & venues",
    blurb: "Feed the machine. New inputs widen what the Gate can find.",
    cmds: [
      {
        cmd: "/add-data-source",
        icon: Database,
        what: "Wire a new point-in-time data source end-to-end: provider → feature → ingest → test.",
        when: "Adding a new signal feed."
      },
      {
        cmd: "/manage-data",
        icon: RefreshCw,
        what: "Fetch, backfill and verify market bars + alt sources through one idempotent path — and report coverage.",
        when: "Pulling data, deepening history, or checking what's stale."
      },
      {
        cmd: "/add-venue",
        icon: Landmark,
        what: "Wire a new exchange or asset class: adapter → catalog → universe gate → real per-venue fees → test.",
        when: "Adding somewhere to trade."
      }
    ]
  },
  {
    stage: "Test & judge",
    blurb: "Let the deterministic Gate — never an LLM — be the judge.",
    cmds: [
      {
        cmd: "/run-gate",
        icon: Gavel,
        what: "Run the real-data cross-asset Gate and report the verdict: fund a forward-test track, or kill with reasons.",
        when: "Checking whether an edge is real."
      },
      {
        cmd: "/evolve-strategy",
        icon: Layers,
        what: "Isolate a gate-passed signal, graft it onto other assets, recombine survivors — and route the cohort back through the Gate.",
        when: "Compounding a proven edge without manufacturing one."
      },
      {
        cmd: "/debug-strategy",
        icon: Bug,
        what: "Post-mortem on a dead or underperforming Version — why it died, what to learn.",
        when: "Understanding a loss."
      }
    ]
  },
  {
    stage: "Ship & maintain",
    blurb: "Keep it live and lean. Push = deploy.",
    cmds: [
      {
        cmd: "/deploy-check",
        icon: PlugZap,
        what: "The pre-push gate — run pnpm verify (lint + types + tests) and confirm the tree is green and coherent.",
        when: "Before every push."
      },
      {
        cmd: "/deploy-iterate",
        icon: Rocket,
        what: "Agentic deploy → read Railway / Vercel runtime logs → fix → repeat, without wasted redeploys.",
        when: "A deploy is failing."
      },
      {
        cmd: "/groom",
        icon: Sparkles,
        what: "Self-maintenance: prune dead code, graveyard stale strategies, keep docs + memory lean, leave the tree green.",
        when: "Periodic cleanup so the system stays smart without bloating."
      }
    ]
  }
];

export default function CommandsPage() {
  return (
    <div className="mx-auto max-w-[960px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-7 lg:px-7">
      <SectionHeader
        eyebrow="commands"
        title="Run from Claude Code"
        aside={<Badge variant="iris">The app shows · Claude Code does</Badge>}
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-1.5">
            <Terminal className="size-4 text-iris-soft" /> The cockpit and the hands
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-[13px] leading-relaxed text-muted">
          <p>
            Cosmu&apos;s screens are a <span className="text-foreground">glass cockpit</span> — they show you everything
            (data, strategies, the gate funnel, P&amp;L) and let you{" "}
            <span className="text-foreground">approve and steer</span>. The{" "}
            <span className="text-foreground">doing</span> — adding data sources, importing strategies, running the
            gate, deploying — happens in <span className="text-foreground">Claude Code</span> as runnable playbooks. One
            place to act, one place to watch.
          </p>
          <p className="text-quiet">
            In Claude Code, type the slash command below. On any other agent (Codex, Cursor), open{" "}
            <code className="rounded bg-surface-2/60 px-1 py-0.5 font-mono text-[11.5px] text-iris-soft">
              .claude/skills/&lt;name&gt;/SKILL.md
            </code>{" "}
            and follow it — same playbook.
          </p>
        </CardContent>
      </Card>

      {GROUPS.map((group) => (
        <section key={group.stage} className="space-y-3">
          <div>
            <h3 className="text-[13px] font-semibold text-foreground">{group.stage}</h3>
            <p className="text-[12px] text-quiet">{group.blurb}</p>
          </div>

          <Card>
            <CardContent className="overflow-x-auto px-0 pt-0">
              <ul className="min-w-[34rem] divide-y divide-hairline">
                {group.cmds.map((c) => {
                  const Icon = c.icon;
                  return (
                    <li
                      key={c.cmd}
                      className="flex flex-col gap-1.5 px-5 py-3.5 sm:flex-row sm:items-start sm:gap-4"
                    >
                      <div className="flex w-[13.5rem] shrink-0 items-center gap-2">
                        <Icon className="size-4 shrink-0 text-iris-soft" aria-hidden />
                        <code className="whitespace-nowrap font-mono text-[12.5px] font-medium text-iris-soft">
                          {c.cmd}
                        </code>
                      </div>
                      <div className="min-w-0 space-y-1">
                        <p className="text-[12.5px] leading-relaxed text-muted">{c.what}</p>
                        <p className="text-[11.5px] text-quiet">
                          <span className="text-muted">When:</span> {c.when}
                        </p>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </CardContent>
          </Card>
        </section>
      ))}

      <p className="text-[11.5px] leading-relaxed text-quiet">
        The Gate and anything that moves money are deterministic and out of any LLM path — Claude Code only proposes;
        the Gate disposes. Live trading stays off behind its interlocks regardless of what you run here.
      </p>
    </div>
  );
}
