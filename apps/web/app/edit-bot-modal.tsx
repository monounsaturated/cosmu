"use client";

import { BotFormModal } from "./bot-form-modal";

type EditBotModalProps = {
  botId: string;
  onClose: () => void;
  onSuccess: () => void;
};

export function EditBotModal({ botId, onClose, onSuccess }: EditBotModalProps) {
  return <BotFormModal mode="edit" botId={botId} onClose={onClose} onSuccess={onSuccess} />;
}
