// module: OpenAI provider via the OpenAI-compatible shim.
import {
  createOpenAiCompatibleProvider,
  listOpenAiCompatibleModels,
  runOpenAiCompatibleAgentLoop
} from "./openai-compatible.js";

export const openaiProvider = createOpenAiCompatibleProvider("openai");

export const listOpenAIModels = () => listOpenAiCompatibleModels("openai");

export const runOpenAIAgentLoop = (input: Omit<Parameters<typeof runOpenAiCompatibleAgentLoop>[0], "provider">) =>
  runOpenAiCompatibleAgentLoop({ provider: "openai", ...input });
