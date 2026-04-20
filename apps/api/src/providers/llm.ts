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

/**
 * xAI Live Search parameters. Provider-specific (xAI only). Other providers
 * receive this field and silently ignore it. See docs.x.ai/docs/guides/live-search.
 */
export type LiveSearchParameters = {
  mode?: "auto" | "on" | "off";
  sources?: Array<
    | { type: "web" }
    | { type: "x"; x_handles?: string[] }
    | { type: "news" }
    | { type: "rss"; links: string[] }
  >;
  max_search_results?: number;
  return_citations?: boolean;
  from_date?: string;
  to_date?: string;
};

export type LLMChatInput = {
  model: string;
  messages: LLMMessage[];
  responseFormat?: Record<string, unknown>;
  temperature?: number;
  /** xAI Live Search (ignored by other providers). */
  searchParameters?: LiveSearchParameters;
};

export type LLMProvider = {
  readonly name: string;
  chat: (input: LLMChatInput) => Promise<LLMResponse>;
};
