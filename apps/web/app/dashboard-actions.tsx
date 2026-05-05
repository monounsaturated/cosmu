"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { CreateBotModal } from "./create-bot-modal";

type DashboardActionsProps = {
  hasNoBots: boolean;
};

export function DashboardActions({ hasNoBots }: DashboardActionsProps) {
  const [showCreateModal, setShowCreateModal] = useState(false);
  const router = useRouter();

  const handleSuccess = () => {
    setShowCreateModal(false);
    router.refresh();
  };

  return (
    <>
      <button className="btn btn-primary" onClick={() => setShowCreateModal(true)}>
        + Create agent
      </button>

      {hasNoBots && (
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
