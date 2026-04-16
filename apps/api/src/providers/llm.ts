/** Provider-agnostic LLM interface for Cosmu v2. */

export type LLMMessage = {
  role: "system" | "user" | "assistant";
  content: string;
};

export type LLMUsage = {
  inputTokens: number;
  outputTokens: number;
};

export type LLMResponse = {
  content: string;
  usage: LLMUsage | null;
  model: string;
  strategy: string;
};

export type LLMChatInput = {
  model: string;
  messages: LLMMessage[];
  responseFormat?: Record<string, unknown>;
  temperature?: number;
};

export type LLMProvider = {
  readonly name: string;
  chat: (input: LLMChatInput) => Promise<LLMResponse>;
};
