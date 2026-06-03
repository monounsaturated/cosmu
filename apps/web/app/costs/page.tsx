// Costs / Infra view — W1.5
// Answers: what does running this machine cost, and do the surviving strategies earn it back?
// Two panels: (1) the static monthly infra table from MASTER_PLAN §9 — always visible,
// never fabricated; (2) per-strategy ROI (opex attributed to a strategy vs its net P&L).
// LLM call ledger is shown as a count + $0 total (all :free OpenRouter models).
// Honest: NotConnected when engine is unreachable; EmptyState when tables have no rows yet.

import { DollarSign, Cpu, TrendingUp, TrendingDown, Bot } from "lucide-react";
import { engineConfigured, getCosts } from "../data";
import type { InfraLine, CostPerStrategy, LlmCallSummary } from "../data";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Stat } from "@/components/ui/stat";
import { SectionHeader } from "@/components/ui/section";
import { EmptyState, NotConnected } from "@/components/ui/honest-state";
import { formatUsd, formatSigned } from "@/lib/utils";

export default async function CostsPage() {
  const { costs, connected } = await getCosts();

  if (!connected) {
    return (
      <div className="mx-auto max-w-[1100px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:px-7">
        <SectionHeader eyebrow="costs · infra" title="What does running this cost?" />
        <NotConnected
          configured={engineConfigured}
          what="Costs shows the monthly infra table and per-strategy ROI (opex vs net P&L). Nothing is fabricated — only real recorded rows."
        />
      </div>
    );
  }

  const totalMonthly = costs.infra_lines.reduce((s, l) => s + l.amount, 0);
  const totalMonthlyMax = costs.infra_lines.reduce((s, l) => s + l.amount_max, 0);

  return (
    <div className="mx-auto max-w-[1100px] space-y-6 px-4 py-6 sm:px-5 sm:py-7 lg:space-y-7 lg:px-7">
      <SectionHeader
        eyebrow="costs · infra"
        title="What does running this cost?"
        aside={
          <Badge variant="iris">
            <DollarSign className="size-3" /> opex vs alpha
          </Badge>
        }
      />

      {/* KPI strip */}
      <section className="grid grid-cols-3 gap-3">
        <Stat
          label="Monthly infra (mid)"
          value={formatUsd(totalMonthly)}
          hint={`ceiling ${formatUsd(totalMonthlyMax)}/mo`}
          accent="iris"
          icon={<Cpu className="size-4" />}
        />
        <Stat
          label="LLM calls recorded"
          value={costs.llm_calls.call_count.toLocaleString()}
          hint={costs.llm_calls.total_cost === 0 ? ":free tier — $0 spend" : formatUsd(costs.llm_calls.total_cost, 4)}
          accent="iris"
          icon={<Bot className="size-4" />}
        />
        <Stat
          label="Opex vs equity"
          value={costs.opex_vs_alpha === 0 ? "—" : `${(costs.opex_vs_alpha * 100).toFixed(2)}%`}
          hint="total costs ÷ sim equity"
          accent={costs.opex_vs_alpha <= 0.02 ? "up" : costs.opex_vs_alpha <= 0.1 ? "warn" : "down"}
          icon={<DollarSign className="size-4" />}
        />
      </section>

      {/* Infra cost table — always rendered (static §9 seed) */}
      <section>
        <h2 className="mb-3 text-[13px] font-semibold text-foreground">Monthly infra (MASTER_PLAN §9)</h2>
        {costs.infra_lines.length === 0 ? (
          <Card>
            <CardContent>
              <EmptyState
                title="Infra table not yet seeded."
                hint="The engine seeds the infra cost table on the first GET /costs call. Trigger a /costs fetch or wait for the next engine boot."
              />
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-[12.5px]">
                  <thead>
                    <tr className="border-b border-border/60 text-[11px] uppercase tracking-wide text-quiet">
                      <th className="px-4 py-2.5 text-left font-medium">Vendor</th>
                      <th className="px-4 py-2.5 text-left font-medium">Category</th>
                      <th className="px-4 py-2.5 text-right font-medium">Mid / mo</th>
                      <th className="px-4 py-2.5 text-right font-medium">Range</th>
                      <th className="px-4 py-2.5 text-left font-medium">Role</th>
                    </tr>
                  </thead>
                  <tbody>
                    {costs.infra_lines.map((line: InfraLine) => (
                      <InfraRow key={line.vendor} line={line} />
                    ))}
                    <tr className="border-t border-border/60 bg-surface-2/30 font-semibold">
                      <td className="px-4 py-2.5 text-foreground" colSpan={2}>Total (mid)</td>
                      <td className="px-4 py-2.5 text-right text-foreground">{formatUsd(totalMonthly)}</td>
                      <td className="px-4 py-2.5 text-right text-muted">
                        {formatUsd(costs.infra_lines.reduce((s, l) => s + l.amount_min, 0))}–
                        {formatUsd(totalMonthlyMax)}
                      </td>
                      <td className="px-4 py-2.5 text-quiet text-[11px]">target ~$50 · ceiling $100</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        )}
      </section>

      {/* LLM call breakdown */}
      <section>
        <h2 className="mb-3 text-[13px] font-semibold text-foreground">LLM calls (ledger)</h2>
        <Card>
          <CardContent className="py-4">
            <LlmCallsPanel summary={costs.llm_calls} />
          </CardContent>
        </Card>
      </section>

      {/* Per-strategy ROI */}
      <section>
        <h2 className="mb-3 text-[13px] font-semibold text-foreground">Per-strategy ROI</h2>
        {costs.per_strategy.length === 0 ? (
          <Card>
            <CardContent>
              <EmptyState
                title="No strategy-attributed costs yet."
                hint="Once LLM calls are attributed to a strategy version, ROI (opex vs net P&L) appears here. Costs accrue when strategies are screened or run."
              />
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {costs.per_strategy.map((row: CostPerStrategy) => (
              <RoiCard key={row.version_id} row={row} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function InfraRow({ line }: { line: InfraLine }) {
  const isFree = line.amount_max === 0;
  return (
    <tr className="border-b border-border/40 last:border-0 transition-colors hover:bg-surface-2/20">
      <td className="px-4 py-2.5 font-medium text-foreground">{line.vendor}</td>
      <td className="px-4 py-2.5">
        <Badge variant={line.category === "infra" ? "iris" : "muted"} className="text-[10px]">
          {line.category}
        </Badge>
      </td>
      <td className="px-4 py-2.5 text-right tabular text-foreground">
        {isFree ? <span className="text-up text-[11px]">free</span> : formatUsd(line.amount)}
      </td>
      <td className="px-4 py-2.5 text-right tabular text-muted text-[11px]">
        {isFree ? "—" : `${formatUsd(line.amount_min)}–${formatUsd(line.amount_max)}`}
      </td>
      <td className="px-4 py-2.5 text-quiet max-w-[220px] truncate">{line.note}</td>
    </tr>
  );
}

function LlmCallsPanel({ summary }: { summary: LlmCallSummary }) {
  const tasks = Object.entries(summary.by_task);
  if (summary.call_count === 0) {
    return (
      <EmptyState
        title="No LLM calls recorded yet."
        hint="Every call through the LLM gateway (strategy authoring, proposals) is recorded here once the engine has run at least one autonomous tick."
        icon={<Bot className="size-5" />}
      />
    );
  }
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-[12.5px]">
        <div>
          <span className="text-quiet">Total calls</span>{" "}
          <span className="font-semibold text-foreground tabular">{summary.call_count.toLocaleString()}</span>
        </div>
        <div>
          <span className="text-quiet">Total cost</span>{" "}
          <span className="font-semibold text-up tabular">
            {summary.total_cost === 0 ? "$0 (:free tier)" : formatUsd(summary.total_cost, 4)}
          </span>
        </div>
      </div>
      {tasks.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {tasks.map(([task, count]) => (
            <div
              key={task}
              className="flex items-center gap-1.5 rounded-md border border-border/60 bg-surface-2/30 px-2.5 py-1 text-[11.5px]"
            >
              <span className="text-quiet capitalize">{task}</span>
              <span className="font-medium text-foreground tabular">{Number(count)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function RoiCard({ row }: { row: CostPerStrategy }) {
  const profitable = row.net >= 0;
  const roi = row.opex > 0 ? row.net / row.opex : null;
  return (
    <Card>
      <CardContent className="space-y-3 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-[13.5px] font-medium text-foreground">{row.name}</div>
            <div className="truncate text-[11px] text-quiet">{row.version_id.slice(0, 8)}</div>
          </div>
          <Badge variant={profitable ? "up" : "down"}>
            {profitable ? <TrendingUp className="size-3" /> : <TrendingDown className="size-3" />}
            {profitable ? "profitable" : "underwater"}
          </Badge>
        </div>
        <div className="grid grid-cols-3 gap-2 text-center">
          <Metric
            label="Opex"
            value={formatUsd(row.opex, 2)}
            tone="text-muted"
          />
          <Metric
            label="Net P&L"
            value={formatSigned(row.net)}
            tone={profitable ? "text-up" : "text-down"}
          />
          <Metric
            label="ROI"
            value={roi !== null ? `${(roi * 100).toFixed(0)}%` : "—"}
            tone={roi === null ? "text-quiet" : roi >= 1 ? "text-up" : roi >= 0 ? "text-warn" : "text-down"}
          />
        </div>
      </CardContent>
    </Card>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="rounded-md border border-border/50 bg-surface-2/30 px-2 py-2">
      <div className={`text-[14px] font-semibold tabular ${tone}`}>{value}</div>
      <div className="mt-0.5 text-[10px] uppercase tracking-wide text-quiet">{label}</div>
    </div>
  );
}
