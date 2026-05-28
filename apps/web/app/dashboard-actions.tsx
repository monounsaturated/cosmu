"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { CreateBotModal } from "./create-bot-modal";
import { KillAllBotsButton } from "./kill-all-bots";

type DashboardActionsProps = {
  hasNoBots: boolean;
  activeBotCount: number;
  dashboardUnavailable?: boolean;
};

export function DashboardActions({ hasNoBots, activeBotCount, dashboardUnavailable = false }: DashboardActionsProps) {
  const [showCreateModal, setShowCreateModal] = useState(false);
  const router = useRouter();

  const handleSuccess = () => {
    setShowCreateModal(false);
    router.refresh();
  };

  return (
    <>
      <div className="hero-action-row">
        <KillAllBotsButton activeBotCount={activeBotCount} disabled={dashboardUnavailable} />
        <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
          <Plus size={16} />
          Create agent
        </button>
      </div>

      {hasNoBots && !dashboardUnavailable && (
        <p className="muted" style={{ marginTop: "8px", fontSize: "14px" }}>
          No agents yet. Create the first paper or live strategy to get started.
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
