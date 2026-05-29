"use client";

import { useDeferredValue, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useRouter } from "next/navigation";
import type { DashboardPayload } from "@cosmu/shared";
import { BotControls } from "./bot-controls";
import { LocalTime } from "./local-time";

type BotRow = DashboardPayload["bots"][number] & {
  llmHourlyUsd?: number | null;
  llmDailyUsd?: number | null;
  llmCostPerRunUsd?: number | null;
  llmTokens?: number | null;
  llmWarning?: string | null;
};
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
  | "llmHourly"
  | "llmDaily"
  | "llmRun"
  | "llmTokens"
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
  compact?: boolean;
  maxRows?: number;
  defaultSortField?: ColumnId;
  defaultSortOrder?: SortOrder;
  showCreatedByDefault?: boolean;
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

const formatSpend = (value: number | null | undefined, digits = 2) => {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: value >= 100 ? 0 : 2,
    maximumFractionDigits: digits
  });
};

const formatInt = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : value.toLocaleString("en-US");

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
    id: "llmHourly",
    label: "LLM / h",
    align: "right",
    defaultVisible: true,
    sortValue: (bot) => bot.llmHourlyUsd ?? null,
    render: (bot) => (
      <span className={bot.llmWarning ? "value-red" : ""} title={bot.llmWarning ?? undefined}>
        {formatSpend(bot.llmHourlyUsd)}
      </span>
    )
  },
  {
    id: "llmDaily",
    label: "LLM / day",
    align: "right",
    defaultVisible: false,
    sortValue: (bot) => bot.llmDailyUsd ?? null,
    render: (bot) => formatSpend(bot.llmDailyUsd, 0)
  },
  {
    id: "llmRun",
    label: "LLM / run",
    align: "right",
    defaultVisible: false,
    sortValue: (bot) => bot.llmCostPerRunUsd ?? null,
    render: (bot) => formatSpend(bot.llmCostPerRunUsd, 4)
  },
  {
    id: "llmTokens",
    label: "Tokens",
    align: "right",
    defaultVisible: false,
    sortValue: (bot) => bot.llmTokens ?? null,
    render: (bot) => formatInt(bot.llmTokens)
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
    defaultVisible: true,
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

const DEFAULT_VISIBLE_COLUMNS: ColumnId[] = [
  "agent",
  "status",
  "account",
  "cadence",
  "value",
  "netPnl",
  "returnPct",
  "trades",
  "llmHourly",
  "lastDecision",
  "actions"
];
const COMPACT_VISIBLE_COLUMNS: ColumnId[] = ["agent", "status", "account", "value", "netPnl", "actions"];

const getInitialVisibleColumns = (compact: boolean, showCreatedByDefault: boolean): ColumnId[] => {
  const base = compact ? COMPACT_VISIBLE_COLUMNS : DEFAULT_VISIBLE_COLUMNS;
  if (!showCreatedByDefault || base.includes("created")) return base;
  const insertAfter = base.indexOf("account");
  if (insertAfter === -1) return [...base, "created"];
  return [...base.slice(0, insertAfter + 1), "created", ...base.slice(insertAfter + 1)];
};

export function BotTable({
  dashboard,
  title = "Agent Performance",
  description = "Compare every active and stopped strategy from one shared table. Sort, filter, and choose columns here; every mode uses the same surface.",
  emptyMessage = "No agents created yet.",
  workspaceMode,
  compact = false,
  maxRows,
  defaultSortField = "returnPct",
  defaultSortOrder = "desc",
  showCreatedByDefault = false
}: Props) {
  const scopedBots = useMemo(() => {
    const spendByBotId = new Map(
      (dashboard.llmSpendEstimate?.bots ?? []).map((bot) => [bot.botId, bot])
    );
    const enriched = dashboard.bots.map((bot) => {
      const spend = spendByBotId.get(bot.id);
      return {
        ...bot,
        llmHourlyUsd: spend?.estimatedHourlyUsd ?? null,
        llmDailyUsd: spend?.estimatedDailyUsd ?? null,
        llmCostPerRunUsd: spend?.estimatedCostPerRunUsd ?? null,
        llmTokens: spend ? spend.sampleInputTokens + spend.sampleOutputTokens : null,
        llmWarning: spend?.warning ?? null
      };
    });
    if (!workspaceMode) return enriched;
    return enriched.filter((bot) => (bot.workspaceMode ?? "light") === workspaceMode);
  }, [dashboard.bots, dashboard.llmSpendEstimate?.bots, workspaceMode]);
  const router = useRouter();
  const [sortField, setSortField] = useState<ColumnId>(defaultSortField);
  const [sortOrder, setSortOrder] = useState<SortOrder>(defaultSortOrder);
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const [statusFilter, setStatusFilter] = useState<FilterValue>("all");
  const [accountFilter, setAccountFilter] = useState<FilterValue>("all");
  const [qualityFilter, setQualityFilter] = useState<FilterValue>("all");
  const [visibleColumns, setVisibleColumns] = useState<ColumnId[]>(() =>
    getInitialVisibleColumns(compact, showCreatedByDefault)
  );

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
    const search = deferredQuery.trim().toLowerCase();
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
  }, [accountFilter, deferredQuery, qualityFilter, scopedBots, statusFilter]);

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

  const visibleColumnDefs = useMemo(
    () => COLUMN_DEFS.filter((column) => visibleColumns.includes(column.id)),
    [visibleColumns]
  );
  const displayedBots = typeof maxRows === "number" ? sortedBots.slice(0, maxRows) : sortedBots;

  const overview = useMemo(() => {
    const activeBots = scopedBots.filter((bot) => bot.enabled);
    const active = activeBots.length;
    const totalValue = activeBots.reduce((sum, bot) => sum + (bot.currentPortfolioUsd ?? 0), 0);
    const netPnl = activeBots.reduce((sum, bot) => sum + (bot.netPnlUsd ?? 0), 0);
    const llmHourly = activeBots.reduce((sum, bot) => sum + (bot.llmHourlyUsd ?? 0), 0);
    const best = scopedBots.reduce<BotRow | null>((current, bot) => {
      if (getReturnPct(bot) === null) return current;
      if (!current || (getReturnPct(bot) ?? -Infinity) > (getReturnPct(current) ?? -Infinity)) return bot;
      return current;
    }, null);
    return { active, totalValue, netPnl, llmHourly, best };
  }, [scopedBots]);

  const SortIndicator = ({ field }: { field: ColumnId }) => {
    if (sortField !== field) return <span style={{ opacity: 0.25 }}>↕</span>;
    return <span>{sortOrder === "asc" ? "↑" : "↓"}</span>;
  };

  if (dashboard.backendError) {
    return (
      <section className="panel performance-surface agent-performance-surface">
        <div className="performance-header">
          <div>
            <h3>{title}</h3>
            <p className="muted">{description}</p>
          </div>
        </div>
        <div className="dashboard-error-state">
          <strong>Agents unavailable</strong>
          <p>The backend dashboard could not be loaded, so the app is not showing an empty agent list.</p>
          <code>{dashboard.backendError}</code>
        </div>
      </section>
    );
  }

  return (
    <section className="panel performance-surface agent-performance-surface">
      <div className="performance-header">
        <div>
          <h3>{title}</h3>
          <p className="muted">{description}</p>
        </div>
        <div className="performance-summary">
          <span><strong>{scopedBots.length}</strong> total</span>
          <span><strong>{overview.active}</strong> active</span>
          <span><strong>{formatUsd(overview.totalValue)}</strong> active value</span>
          <span className={valueTone(overview.netPnl)}><strong>{formatUsd(overview.netPnl, { signed: true })}</strong> net</span>
          <span><strong>{formatSpend(overview.llmHourly)}</strong> LLM / h</span>
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

      <div className="table-scroll agent-table-scroll">
        <table className="table table-compact agent-table">
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
            {displayedBots.map((bot) => (
              <tr
                key={bot.id}
                className="run-row"
                onClick={() => router.push(`/bots/${bot.id}`)}
              >
                {visibleColumnDefs.map((column) => (
                  <td
                    key={column.id}
                    className={column.align === "right" ? "text-right" : ""}
                    data-label={column.label || "Actions"}
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
      {typeof maxRows === "number" && sortedBots.length > maxRows ? (
        <p className="muted table-empty table-more-note">
          Showing {maxRows} important agents. Open Agents for the full table.
        </p>
      ) : null}
    </section>
  );
}
