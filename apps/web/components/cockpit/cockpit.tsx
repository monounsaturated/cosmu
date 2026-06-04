"use client";

// module: the Cockpit shell — the modular Overview. The page fetches every surface and hands a plain
// CockpitData snapshot here; this client component renders the operator's CHOSEN widgets in a responsive
// grid and lets them pick-what-to-display (Customize panel + per-block hover-remove in edit mode). The
// selection persists to localStorage. Each widget is a self-contained block (Notion vibe) with its own
// honest empty state, so hiding/showing never fabricates or hides truth — it only declutters the view.

import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Activity,
  Compass,
  Database,
  Lightbulb,
  LayoutGrid,
  MessageSquare,
  RotateCcw,
  Settings2,
  X
} from "lucide-react";
import type { CockpitData } from "./cockpit-data";
import { WidgetCard } from "./widget-card";
import {
  EdgeKpis,
  EquityWidget,
  GateFunnelWidget,
  EdgeQualityWidget,
  WorkingVersionsWidget,
  MindWidget,
  RegimeWidget,
  LiveWidget
} from "./widgets";
import { WhatNext } from "@/components/overview/what-next";
import { RightNow } from "@/components/overview/right-now";
import { DataFreshness } from "@/components/overview/data-freshness";
import { IdeaInbox } from "@/components/overview/idea-inbox";
import { AutonomyPanel } from "@/components/autonomy/autonomy-panel";
import { NeedsYouInbox } from "@/components/autonomy/needs-you-inbox";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Group = "Edge & money" | "Machine" | "Research" | "Live";

interface WidgetDef {
  id: string;
  title: string;
  group: Group;
  span: 1 | 2;
  defaultOn: boolean;
  render: (d: CockpitData) => ReactNode;
}

// The registry — declaration order is the layout order. span:2 fills the row; span:1 widgets pair up.
const WIDGETS: WidgetDef[] = [
  { id: "edge-kpis", title: "Edge KPIs", group: "Edge & money", span: 2, defaultOn: true, render: (d) => <EdgeKpis data={d} /> },
  {
    id: "what-next",
    title: "What to do next",
    group: "Machine",
    span: 2,
    defaultOn: true,
    render: (d) => {
      const curve = d.overview.equity_curve;
      const hasTrack = curve.length >= 2;
      const start = curve[0]?.value ?? 0;
      const equity = curve[curve.length - 1]?.value ?? 0;
      return (
        <WhatNext
          population={d.population}
          leaderboard={d.leaderboard}
          recommendations={d.recommendations}
          autonomy={d.autonomy}
          dataFreshness={d.intelligence.data_freshness}
          hasTrackRecord={hasTrack}
          returnPct={hasTrack && start ? ((equity - start) / start) * 100 : 0}
        />
      );
    }
  },
  { id: "gate-funnel", title: "Gate funnel", group: "Machine", span: 1, defaultOn: true, render: (d) => <GateFunnelWidget data={d} /> },
  { id: "edge-quality", title: "Edge quality", group: "Edge & money", span: 1, defaultOn: true, render: (d) => <EdgeQualityWidget data={d} /> },
  { id: "equity", title: "Equity curve", group: "Edge & money", span: 2, defaultOn: true, render: (d) => <EquityWidget data={d} /> },
  {
    id: "right-now",
    title: "Right now",
    group: "Machine",
    span: 2,
    defaultOn: true,
    render: (d) => (
      <RightNow
        connected={d.connected}
        autonomy={d.autonomy}
        population={d.population}
        mind={d.mind}
        recommendations={d.recommendations}
        events={d.events}
      />
    )
  },
  { id: "working-versions", title: "Working versions", group: "Edge & money", span: 2, defaultOn: true, render: (d) => <WorkingVersionsWidget data={d} /> },
  {
    id: "data-freshness",
    title: "Data freshness",
    group: "Research",
    span: 1,
    defaultOn: true,
    render: (d) => <DataFreshness sources={d.intelligence.data_freshness} connected={d.intelConnected} />
  },
  {
    id: "idea-inbox",
    title: "Idea inbox",
    group: "Research",
    span: 1,
    defaultOn: true,
    render: (d) => <IdeaInbox initial={d.queuedIdeas} connected={d.inboxConnected} configured={d.configured} />
  },
  {
    id: "needs-you",
    title: "Needs you",
    group: "Machine",
    span: 1,
    defaultOn: true,
    render: (d) => (
      <WidgetCard title="Needs you" icon={<MessageSquare className="size-4" />} href="/steer" hrefLabel="Steer">
        <NeedsYouInbox initial={d.recommendations} connected={d.recConnected} configured={d.configured} />
      </WidgetCard>
    )
  },
  {
    id: "autonomy",
    title: "Autonomy controls",
    group: "Machine",
    span: 1,
    defaultOn: true,
    render: (d) => <AutonomyPanel initial={d.autonomy} connected={d.autonomyConnected} configured={d.configured} />
  },
  { id: "mind", title: "The Mind", group: "Research", span: 1, defaultOn: false, render: (d) => <MindWidget data={d} /> },
  { id: "regime", title: "Regime coverage", group: "Research", span: 1, defaultOn: false, render: (d) => <RegimeWidget data={d} /> },
  { id: "live", title: "Live execution", group: "Live", span: 1, defaultOn: false, render: (d) => <LiveWidget data={d} /> }
];

const WIDGET_IDS = WIDGETS.map((w) => w.id);
const DEFAULT_ENABLED = WIDGETS.filter((w) => w.defaultOn).map((w) => w.id);
const STORAGE_KEY = "cosmu.cockpit.v1";

const GROUP_ICON: Record<Group, ReactNode> = {
  "Edge & money": <Compass className="size-3.5" />,
  Machine: <Activity className="size-3.5" />,
  Research: <Database className="size-3.5" />,
  Live: <Lightbulb className="size-3.5" />
};

export function Cockpit({ data }: { data: CockpitData }) {
  // Start from defaults so server + first client render match; reconcile with the saved layout on mount.
  const [enabled, setEnabled] = useState<string[]>(DEFAULT_ENABLED);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as unknown;
      if (Array.isArray(parsed)) {
        const valid = parsed.filter((id): id is string => typeof id === "string" && WIDGET_IDS.includes(id));
        setEnabled(valid);
      }
    } catch {
      /* corrupt value — fall back to defaults */
    }
  }, []);

  function persist(next: string[]) {
    setEnabled(next);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      /* ignore quota / private-mode failures */
    }
  }

  const enabledSet = useMemo(() => new Set(enabled), [enabled]);

  function toggle(id: string) {
    persist(enabledSet.has(id) ? enabled.filter((x) => x !== id) : [...enabled, id]);
  }
  function reset() {
    persist(DEFAULT_ENABLED);
  }

  // Render registry order, filtered to the enabled set.
  const shown = WIDGETS.filter((w) => enabledSet.has(w.id));

  return (
    <div className="mx-auto max-w-[1280px] space-y-5 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
      {/* Toolbar */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-iris-soft">cockpit</div>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">Mission control</h1>
          <p className="mt-1 text-[12.5px] text-quiet">
            Is the machine finding real, net-of-fee edge? Pick the blocks you want — detail is one click (or hover) away.
          </p>
        </div>
        <Button variant={editing ? "primary" : "secondary"} size="sm" type="button" onClick={() => setEditing((e) => !e)}>
          {editing ? <LayoutGrid /> : <Settings2 />}
          {editing ? "Done" : "Customize"}
        </Button>
      </div>

      {/* Customize panel — pick what to display, grouped. */}
      {editing ? <CustomizePanel enabled={enabledSet} onToggle={toggle} onReset={reset} /> : null}

      {/* Widget grid */}
      {shown.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border bg-surface-2/20 py-16 text-center">
          <LayoutGrid className="mx-auto size-6 text-quiet" />
          <p className="mt-2 text-[13px] text-muted">No blocks shown.</p>
          <p className="mt-1 text-[11.5px] text-quiet">Open Customize to add widgets back to your cockpit.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          {shown.map((w) => (
            <div key={w.id} className={cn("relative min-w-0", w.span === 2 && "lg:col-span-2")}>
              {editing ? (
                <button
                  type="button"
                  onClick={() => toggle(w.id)}
                  aria-label={`Hide ${w.title}`}
                  title={`Hide ${w.title}`}
                  className="absolute -right-2 -top-2 z-10 inline-flex size-6 items-center justify-center rounded-full border border-border-strong bg-surface text-quiet shadow-card transition-colors hover:border-down/60 hover:bg-down/15 hover:text-down"
                >
                  <X className="size-3.5" />
                </button>
              ) : null}
              {w.render(data)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CustomizePanel({
  enabled,
  onToggle,
  onReset
}: {
  enabled: Set<string>;
  onToggle: (id: string) => void;
  onReset: () => void;
}) {
  const groups: Group[] = ["Edge & money", "Machine", "Research", "Live"];
  return (
    <div className="rounded-lg border border-border/70 bg-surface-2/30 p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-1.5 text-[12px] font-semibold text-foreground">
          <Settings2 className="size-3.5 text-iris-soft" /> Customize cockpit
        </div>
        <button
          type="button"
          onClick={onReset}
          className="inline-flex items-center gap-1 text-[11.5px] font-medium text-quiet transition-colors hover:text-foreground"
        >
          <RotateCcw className="size-3" /> Reset to defaults
        </button>
      </div>
      <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-4">
        {groups.map((g) => (
          <div key={g}>
            <div className="mb-1.5 flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-[0.1em] text-quiet">
              {GROUP_ICON[g]} {g}
            </div>
            <ul className="space-y-1">
              {WIDGETS.filter((w) => w.group === g).map((w) => {
                const on = enabled.has(w.id);
                return (
                  <li key={w.id}>
                    <button
                      type="button"
                      onClick={() => onToggle(w.id)}
                      aria-pressed={on}
                      className={cn(
                        "flex w-full items-center gap-2 rounded-md border px-2.5 py-1.5 text-left text-[12px] transition-colors",
                        on
                          ? "border-iris/40 bg-iris/10 text-foreground"
                          : "border-border/60 bg-surface-2/30 text-quiet hover:text-foreground"
                      )}
                    >
                      <span className={cn("size-2 shrink-0 rounded-full", on ? "bg-iris" : "bg-border-strong")} />
                      {w.title}
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
