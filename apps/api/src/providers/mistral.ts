// module: Mistral provider via the OpenAI-compatible shim.
import {
  createOpenAiCompatibleProvider,
  listOpenAiCompatibleModels,
  runOpenAiCompatibleAgentLoop
} from "./openai-compatible.js";

export const mistralProvider = createOpenAiCompatibleProvider("mistral");

export const listMistralModels = () => listOpenAiCompatibleModels("mistral");

export const runMistralAgentLoop = (
  input: Omit<Parameters<typeof runOpenAiCompatibleAgentLoop>[0], "provider">
) => runOpenAiCompatibleAgentLoop({ provider: "mistral", ...input });
