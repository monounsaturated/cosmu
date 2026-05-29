"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Plus, RefreshCw } from "lucide-react";
import { CreateBotModal } from "./create-bot-modal";
import { KillAllBotsButton } from "./kill-all-bots";

type DashboardActionsProps = {
  hasNoBots: boolean;
  activeBotCount: number;
  dashboardUnavailable?: boolean;
};

export function DashboardActions({ hasNoBots, activeBotCount, dashboardUnavailable = false }: DashboardActionsProps) {
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [refreshing, startRefreshTransition] = useTransition();
  const router = useRouter();

  const handleSuccess = () => {
    setShowCreateModal(false);
    router.refresh();
  };

  return (
    <>
      <div className="hero-action-row">
        <button
          className="btn btn-secondary"
          type="button"
          onClick={() => startRefreshTransition(() => router.refresh())}
          disabled={refreshing}
        >
          <RefreshCw size={16} />
          {refreshing ? "Refreshing" : "Refresh"}
        </button>
        <KillAllBotsButton activeBotCount={activeBotCount} disabled={dashboardUnavailable} />
        <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
          <Plus size={16} />
          Create agent
        </button>
      </div>

      {hasNoBots && !dashboardUnavailable && (
        <p className="muted" style={{ marginTop: "8px", fontSize: "14px" }}>
          No agents yet. Create the first venue-scoped strategy to get started.
        </p>
      )}

      {showCreateModal && (
        <CreateBotModal
          onClose={() => setShowCreateModal(false)}
          onSuccess={handleSuccess}
        />
      )}
    </>
  );
}
