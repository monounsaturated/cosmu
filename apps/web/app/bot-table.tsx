"use client";

import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useRouter } from "next/navigation";
import type { DashboardPayload } from "@cosmu/shared";
import { BotControls } from "./bot-controls";
import { LocalTime } from "./local-time";

type BotRow = DashboardPayload["bots"][number];
type ColumnId =
  | "agent"
  | "status"
  | "account"
  | "created"
  | "cadence"
  | "budget"
  | "research"
  | "trader"
  | "value"
  | "netPnl"
  | "returnPct"
  | "trades"
  | "runs"
  | "quality"
  | "lastDecision"
  | "actions";
type SortOrder = "asc" | "desc";
type FilterValue = "all" | string;

type Props = {
  dashboard: DashboardPayload;
  title?: string;
  description?: string;
  emptyMessage?: string;
  workspaceMode?: "light" | "research" | "pro";
};

const venueLabel = (venue: "binance" | "binance-testnet") =>
  venue === "binance-testnet" ? "Binance Testnet" : "Binance";

const accountLabel = (mode: "testnet" | "live") => mode === "live" ? "Live" : "Paper";

const displayName = (bot: BotRow) => {
  const trimmed = bot.name?.trim() ?? "";
  const isPlaceholder = trimmed === "" || /^#\d+$/.test(trimmed);
  return isPlaceholder ? `#${bot.botNumber}` : `#${bot.botNumber} ${trimmed}`;
};

const getReturnPct = (bot: BotRow) =>
  bot.netPnlUsd !== null ? (bot.netPnlUsd / bot.budgetUsdt) * 100 : null;

const formatUsd = (value: number | null, options: { signed?: boolean } = {}) => {
  if (value === null) return "—";
  const prefix = options.signed && value > 0 ? "+" : "";
  return `${prefix}$${value.toFixed(2)}`;
};

const formatPct = (value: number | null) => {
  if (value === null) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
};

const valueTone = (value: number | null) =>
  value === null ? "" : value > 0 ? "value-green" : value < 0 ? "value-red" : "";

type ColumnDef = {
  id: ColumnId;
  label: string;
  align?: "right";
  defaultVisible: boolean;
  sortValue?: (bot: BotRow) => string | number | boolean | null;
  render: (bot: BotRow) => ReactNode;
};

const COLUMN_DEFS: ColumnDef[] = [
  {
    id: "agent",
    label: "Agent",
    defaultVisible: true,
    sortValue: (bot) => bot.botNumber,
    render: (bot) => <strong>{displayName(bot)}</strong>
  },
  {
    id: "status",
    label: "Status",
    defaultVisible: true,
    sortValue: (bot) => bot.enabled,
    render: (bot) => (
      <span className="status-label">
        <span className={`status-dot ${bot.enabled ? "status-active" : "status-inactive"}`} />
        {bot.enabled ? "Active" : "Stopped"}
      </span>
    )
  },
  {
    id: "account",
    label: "Account",
    defaultVisible: true,
    sortValue: (bot) => `${bot.mode}-${bot.venue}`,
    render: (bot) => (
      <span>
        {accountLabel(bot.mode)}
        <span className="muted table-subtext">{venueLabel(bot.venue)}</span>
      </span>
    )
  },
  {
    id: "created",
    label: "Created",
    defaultVisible: false,
    sortValue: (bot) => bot.startedAt,
    render: (bot) => <LocalTime value={bot.startedAt} mode="date" />
  },
  {
    id: "cadence",
    label: "Cadence",
    defaultVisible: false,
    sortValue: (bot) => bot.frequencyMinutes,
    render: (bot) => `${bot.frequencyMinutes}m`
  },
  {
    id: "budget",
    label: "Budget",
    align: "right",
    defaultVisible: false,
    sortValue: (bot) => bot.budgetUsdt,
    render: (bot) => `$${bot.budgetUsdt.toFixed(0)}`
  },
  {
    id: "research",
    label: "Research",
    defaultVisible: true,
    sortValue: (bot) => bot.researchModelName ?? bot.modelProfileName,
    render: (bot) => (
      <span className="table-model-cell">
        <span className="badge badge-neutral">{bot.promptVersionLabel}</span>
        <span>{bot.researchModelName ?? bot.modelProfileName}</span>
        {bot.researchModelProvider && <span className="muted">{bot.researchModelProvider}</span>}
      </span>
    )
  },
  {
    id: "trader",
    label: "Trader",
    defaultVisible: true,
    sortValue: (bot) => bot.traderModelName ?? bot.modelProfileName,
    render: (bot) => (
      <span className="table-model-cell">
        {bot.traderPromptVersionLabel && <span className="badge badge-neutral">{bot.traderPromptVersionLabel}</span>}
        <span>{bot.traderModelName ?? bot.modelProfileName}</span>
        {bot.traderModelProvider && <span className="muted">{bot.traderModelProvider}</span>}
      </span>
    )
  },
  {
    id: "value",
    label: "Value",
    align: "right",
    defaultVisible: true,
    sortValue: (bot) => bot.currentPortfolioUsd,
    render: (bot) => formatUsd(bot.currentPortfolioUsd)
  },
  {
    id: "netPnl",
    label: "Net PnL",
    align: "right",
    defaultVisible: true,
    sortValue: (bot) => bot.netPnlUsd,
    render: (bot) => <span className={valueTone(bot.netPnlUsd)}>{formatUsd(bot.netPnlUsd, { signed: true })}</span>
  },
  {
    id: "returnPct",
    label: "Return",
    align: "right",
    defaultVisible: true,
    sortValue: getReturnPct,
    render: (bot) => {
      const value = getReturnPct(bot);
      return <span className={valueTone(value)}>{formatPct(value)}</span>;
    }
  },
  {
    id: "trades",
    label: "Trades",
    align: "right",
    defaultVisible: true,
    sortValue: (bot) => bot.tradeCount,
    render: (bot) => bot.tradeCount
  },
  {
    id: "runs",
    label: "Runs",
    align: "right",
    defaultVisible: false,
    sortValue: (bot) => bot.runCount,
    render: (bot) => bot.runCount
  },
  {
    id: "quality",
    label: "Sample",
    defaultVisible: false,
    sortValue: (bot) => bot.sampleQuality,
    render: (bot) => <span className="badge badge-neutral">{bot.sampleQuality}</span>
  },
  {
    id: "lastDecision",
    label: "Latest Decision",
    defaultVisible: false,
    sortValue: (bot) => bot.latestDecisionSummary ?? "",
    render: (bot) => <span className="table-truncate">{bot.latestDecisionSummary ?? bot.latestError ?? "—"}</span>
  },
  {
    id: "actions",
    label: "",
    defaultVisible: true,
    render: (bot) => <BotControls botId={bot.id} isActive={bot.enabled} />
  }
];

const DEFAULT_VISIBLE_COLUMNS = COLUMN_DEFS.filter((column) => column.defaultVisible).map((column) => column.id);

export function BotTable({
  dashboard,
  title = "Agent Performance",
  description = "Compare every active and stopped strategy from one shared table. Sort, filter, and choose columns here; every mode uses the same surface.",
  emptyMessage = "No agents created yet.",
  workspaceMode
}: Props) {
  const scopedBots = useMemo(() => {
    if (!workspaceMode) return dashboard.bots;
    return dashboard.bots.filter((bot) => (bot.workspaceMode ?? "light") === workspaceMode);
  }, [dashboard.bots, workspaceMode]);
  const router = useRouter();
  const [sortField, setSortField] = useState<ColumnId>("returnPct");
  const [sortOrder, setSortOrder] = useState<SortOrder>("desc");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<FilterValue>("all");
  const [accountFilter, setAccountFilter] = useState<FilterValue>("all");
  const [qualityFilter, setQualityFilter] = useState<FilterValue>("all");
  const [visibleColumns, setVisibleColumns] = useState<ColumnId[]>(DEFAULT_VISIBLE_COLUMNS);

  const handleSort = (field: ColumnId) => {
    if (!COLUMN_DEFS.find((column) => column.id === field)?.sortValue) return;
    if (sortField === field) {
      setSortOrder((value) => (value === "asc" ? "desc" : "asc"));
      return;
    }

    setSortField(field);
    setSortOrder(field === "agent" || field === "created" ? "asc" : "desc");
  };

  const toggleColumn = (columnId: ColumnId) => {
    if (columnId === "agent") return;
    setVisibleColumns((current) =>
      current.includes(columnId)
        ? current.filter((id) => id !== columnId)
        : [...current, columnId]
    );
  };

  const filteredBots = useMemo(() => {
    const search = query.trim().toLowerCase();
    return scopedBots.filter((bot) => {
      if (statusFilter === "active" && !bot.enabled) return false;
      if (statusFilter === "stopped" && bot.enabled) return false;
      if (statusFilter === "errors" && !bot.latestError) return false;
      if (accountFilter !== "all" && bot.mode !== accountFilter) return false;
      if (qualityFilter !== "all" && bot.sampleQuality !== qualityFilter) return false;
      if (!search) return true;

      return [
        displayName(bot),
        bot.slug,
        bot.promptVersionLabel,
        bot.traderPromptVersionLabel ?? "",
        bot.researchModelName ?? bot.modelProfileName,
        bot.traderModelName ?? bot.modelProfileName,
        bot.latestDecisionSummary ?? "",
        bot.latestError ?? "",
        venueLabel(bot.venue),
        accountLabel(bot.mode)
      ].some((value) => value.toLowerCase().includes(search));
    });
  }, [accountFilter, dashboard.bots, qualityFilter, query, statusFilter]);

  const sortedBots = useMemo(() => {
    const column = COLUMN_DEFS.find((item) => item.id === sortField);
    if (!column?.sortValue) return filteredBots;

    return [...filteredBots].sort((a, b) => {
      const aValue = column.sortValue?.(a) ?? null;
      const bValue = column.sortValue?.(b) ?? null;
      if (aValue === null && bValue !== null) return sortOrder === "asc" ? -1 : 1;
      if (aValue !== null && bValue === null) return sortOrder === "asc" ? 1 : -1;
      if (aValue === null && bValue === null) return 0;
      if (typeof aValue === "string" && typeof bValue === "string") {
        return sortOrder === "asc" ? aValue.localeCompare(bValue) : bValue.localeCompare(aValue);
      }
      if (typeof aValue === "boolean" && typeof bValue === "boolean") {
        const result = Number(aValue) - Number(bValue);
        return sortOrder === "asc" ? result : -result;
      }
      const aComparable = typeof aValue === "boolean" ? Number(aValue) : aValue!;
      const bComparable = typeof bValue === "boolean" ? Number(bValue) : bValue!;
      if (aComparable < bComparable) return sortOrder === "asc" ? -1 : 1;
      if (aComparable > bComparable) return sortOrder === "asc" ? 1 : -1;
      return 0;
    });
  }, [filteredBots, sortField, sortOrder]);

  const visibleColumnDefs = COLUMN_DEFS.filter((column) => visibleColumns.includes(column.id));

  const overview = useMemo(() => {
    const active = scopedBots.filter((bot) => bot.enabled).length;
    const totalValue = scopedBots.reduce((sum, bot) => sum + (bot.currentPortfolioUsd ?? 0), 0);
    const netPnl = scopedBots.reduce((sum, bot) => sum + (bot.netPnlUsd ?? 0), 0);
    const best = scopedBots.reduce<BotRow | null>((current, bot) => {
      if (getReturnPct(bot) === null) return current;
      if (!current || (getReturnPct(bot) ?? -Infinity) > (getReturnPct(current) ?? -Infinity)) return bot;
      return current;
    }, null);
    return { active, totalValue, netPnl, best };
  }, [scopedBots]);

  const SortIndicator = ({ field }: { field: ColumnId }) => {
    if (sortField !== field) return <span style={{ opacity: 0.25 }}>↕</span>;
    return <span>{sortOrder === "asc" ? "↑" : "↓"}</span>;
  };

  return (
    <section className="panel performance-surface">
      <div className="performance-header">
        <div>
          <h3>{title}</h3>
          <p className="muted">{description}</p>
        </div>
        <div className="performance-summary">
          <span><strong>{scopedBots.length}</strong> total</span>
          <span><strong>{overview.active}</strong> active</span>
          <span><strong>{formatUsd(overview.totalValue)}</strong> value</span>
          <span className={valueTone(overview.netPnl)}><strong>{formatUsd(overview.netPnl, { signed: true })}</strong> net</span>
          <span><strong>{overview.best ? displayName(overview.best) : "—"}</strong> best</span>
        </div>
      </div>

      <div className="table-toolbar">
        <input
          className="table-search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search agents, prompts, models, decisions..."
        />
        <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
          <option value="all">All statuses</option>
          <option value="active">Active</option>
          <option value="stopped">Stopped</option>
          <option value="errors">Has errors</option>
        </select>
        <select value={accountFilter} onChange={(event) => setAccountFilter(event.target.value)}>
          <option value="all">All accounts</option>
          <option value="testnet">Paper</option>
          <option value="live">Live</option>
        </select>
        <select value={qualityFilter} onChange={(event) => setQualityFilter(event.target.value)}>
          <option value="all">All samples</option>
          <option value="low">Low sample</option>
          <option value="medium">Medium sample</option>
          <option value="high">High sample</option>
        </select>
        <details className="column-picker">
          <summary>Columns</summary>
          <div className="column-picker-menu">
            {COLUMN_DEFS.filter((column) => column.id !== "actions").map((column) => (
              <label key={column.id} className="column-picker-option">
                <input
                  type="checkbox"
                  checked={visibleColumns.includes(column.id)}
                  disabled={column.id === "agent"}
                  onChange={() => toggleColumn(column.id)}
                />
                {column.label}
              </label>
            ))}
          </div>
        </details>
      </div>

      <div className="table-scroll">
        <table className="table table-compact">
          <thead>
            <tr>
              {visibleColumnDefs.map((column) => (
                <th
                  key={column.id}
                  className={`${column.sortValue ? "clickable" : ""} ${column.align === "right" ? "text-right" : ""}`}
                  onClick={() => handleSort(column.id)}
                >
                  {column.label} {column.sortValue && <SortIndicator field={column.id} />}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedBots.map((bot) => (
              <tr
                key={bot.id}
                className="run-row"
                onClick={() => router.push(`/bots/${bot.id}`)}
              >
                {visibleColumnDefs.map((column) => (
                  <td
                    key={column.id}
                    className={column.align === "right" ? "text-right" : ""}
                    onClick={column.id === "actions" ? (event) => event.stopPropagation() : undefined}
                  >
                    {column.render(bot)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {sortedBots.length === 0 && (
        <p className="muted table-empty">
          {scopedBots.length === 0 ? emptyMessage : "No agents match the current filters."}
        </p>
      )}
    </section>
  );
}