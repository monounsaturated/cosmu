// Commands — the v18 static reference surface (mockup id=page-commands): a flat bento `.cmd-row` list
// (cmd-name mono + cmd-desc) inside a `.card`. The app is the glass cockpit (it SHOWS everything and lets
// you approve/steer); the DOING — adding data, importing strategies, running the gate, deploying — happens
// as runnable playbooks. Pure static render (no engine calls) — works offline, never moves money.
//
// HONESTY: the mockup listed a `cosmu …` CLI that does NOT exist (and dead "paper" verbs). The real,
// runnable commands are the Claude Code slash-skills in `.claude/skills/<name>/SKILL.md` plus the `pnpm`
// driver scripts in package.json. Every row below is a command that actually exists. Source of truth:
// `.claude/skills/` and the root package.json scripts — keep this list in sync when one is added/removed.

import { Suspense } from "react";
import { Page, Toolbar } from "@/components/ui/toolbar";

type Cmd = { name: string; desc: string };
type Group = { stage: string; cmds: Cmd[] };

// Mirrors the real runnable playbooks in .claude/skills/ and the real `pnpm` scripts. The slash commands
// run inside Claude Code (or any agent: open `.claude/skills/<name>/SKILL.md` and follow it); the `pnpm`
// rows are the deterministic dev/ops scripts. Keep in sync when a skill or script is added/removed.
const GROUPS: Group[] = [
  {
    stage: "Discover",
    cmds: [
      { name: "/scan-signals", desc: "Unbiased cross-asset sweep over every data source → testable hypotheses, each with its disconfirmer — propose-only, never moves money" },
      { name: "/create-strategy", desc: "Turn a thesis into a typed, auditable StrategySpec and drop it in the inbox" },
      { name: "/import-pine", desc: "TradingView Pine → typed spec; hardcoded numbers become a fitted search space, never baked in" },
      { name: "/dump-idea", desc: "Capture a loose natural-language idea as a StrategySpec in strategies/inbox/" },
    ],
  },
  {
    stage: "Data & venues",
    cmds: [
      { name: "/add-data-source", desc: "Wire a new point-in-time data source end-to-end: provider → feature → ingest → test" },
      { name: "/manage-data", desc: "Fetch, backfill and verify market bars + alt sources through one idempotent path; report coverage" },
      { name: "/add-venue", desc: "Wire a new exchange or asset class: adapter → catalog → universe gate → real per-venue fees → test" },
      { name: "/profile-source", desc: "Audit a new feed's PIT history (coverage · gaps · look-ahead) into a GO / REVIEW / NO-GO verdict" },
    ],
  },
  {
    stage: "Test & judge",
    cmds: [
      { name: "/run-gate", desc: "Run the deterministic real-data Gate and report the verdict — fund a forward-test track, or kill with reasons" },
      { name: "/evolve-strategy", desc: "Isolate a gate-passed signal, graft it onto other assets, recombine survivors — route the cohort back through the Gate" },
      { name: "/debug-strategy", desc: "Post-mortem a dead or zero-trade Version — why it died, what to learn" },
      { name: "/variance-attribution", desc: "Decompose a funded track's paper→live divergence into named, signed buckets (fees · slippage · funding · decay · regime)" },
    ],
  },
  {
    stage: "Ship & maintain",
    cmds: [
      { name: "/deploy-check", desc: "The pre-push gate — run pnpm verify and confirm the tree is green and coherent" },
      { name: "/deploy-iterate", desc: "After a push, read Railway / Vercel logs to confirm the deploy is healthy and iterate on failures" },
      { name: "/groom", desc: "Self-maintenance: prune dead code, graveyard stale strategies, keep docs + memory lean, leave the tree green" },
      { name: "/code-review", desc: "Pre-merge quality gate — review the diff for correctness traps, synthetic-data leaks and security" },
    ],
  },
  {
    stage: "Dev scripts",
    cmds: [
      { name: "pnpm verify", desc: "Lint + types + engine tests + build + contract-drift — the deterministic pre-push gate" },
      { name: "pnpm dev", desc: "Regenerate contracts and run the web app locally" },
      { name: "pnpm engine:test", desc: "Run the engine pytest suite" },
      { name: "pnpm engine:api", desc: "Run the engine API locally (cosmu.api.app)" },
    ],
  },
];

export default function CommandsPage() {
  return (
    <Page>
      <Toolbar title="Commands" />
      <Suspense fallback={<div className="skel" style={{ height: 320 }} />}>
        <CommandsBody />
      </Suspense>
    </Page>
  );
}

// Static — no engine call. Wrapped in the same streamed region as the data surfaces so the toolbar paints
// instantly and the page transition feels uniform.
function CommandsBody() {
  return (
    <>
      <div className="card">
        <div className="card-body">
          <p className="quiet" style={{ fontSize: 11.5, lineHeight: 1.6, margin: "0 0 4px" }}>
            The screens are a glass cockpit — they show you everything and let you approve and steer. The
            doing runs as playbooks. In Claude Code, type the slash command; on any other agent open{" "}
            <code className="mono" style={{ color: "var(--iris-s)", fontSize: 11 }}>
              .claude/skills/&lt;name&gt;/SKILL.md
            </code>{" "}
            and follow it — same playbook. The Gate and anything that moves money stay deterministic and out
            of any LLM path.
          </p>
        </div>
      </div>

      {GROUPS.map((group) => (
        <div className="card" key={group.stage}>
          <div className="card-hdr">
            <span className="card-lbl">{group.stage}</span>
          </div>
          <div className="card-body">
            {group.cmds.map((c) => (
              <div className="cmd-row" key={c.name}>
                <span className="cmd-name">{c.name}</span>
                <span className="cmd-desc">{c.desc}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </>
  );
}
