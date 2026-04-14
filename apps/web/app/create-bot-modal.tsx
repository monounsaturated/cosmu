"use client";

import { BotFormModal } from "./bot-form-modal";

type CreateBotModalProps = {
  defaultBotNumber: number;
  onClose: () => void;
  onSuccess: () => void;
};

export function CreateBotModal({ defaultBotNumber, onClose, onSuccess }: CreateBotModalProps) {
  return (
    <BotFormModal mode="create" defaultBotNumber={defaultBotNumber} onClose={onClose} onSuccess={onSuccess} />
  );
}
