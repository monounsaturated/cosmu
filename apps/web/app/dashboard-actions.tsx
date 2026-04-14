"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CreateBotModal } from "./create-bot-modal";

type DashboardActionsProps = {
  hasNoBots: boolean;
  botCount: number;
};

export function DashboardActions({ hasNoBots, botCount }: DashboardActionsProps) {
  const [showCreateModal, setShowCreateModal] = useState(false);
  const router = useRouter();

  const handleSuccess = () => {
    setShowCreateModal(false);
    router.refresh();
  };

  return (
    <>
      <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
        + Create Bot
      </button>

      {hasNoBots && (
        <p className="muted" style={{ marginTop: "8px", fontSize: "14px" }}>
          No bots yet. Create your first bot to get started.
        </p>
      )}

      {showCreateModal && (
        <CreateBotModal
          defaultBotNumber={botCount + 1}
          onClose={() => setShowCreateModal(false)}
          onSuccess={handleSuccess}
        />
      )}
    </>
  );
}
