"use client";

import { BotFormModal } from "./bot-form-modal";

type CreateBotModalProps = {
  onClose: () => void;
  onSuccess: () => void;
};

export function CreateBotModal({ onClose, onSuccess }: CreateBotModalProps) {
  return (
    <BotFormModal mode="create" onClose={onClose} onSuccess={onSuccess} />
  );
}
