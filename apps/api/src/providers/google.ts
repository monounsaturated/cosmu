// module: Google Gemini provider via the OpenAI-compatible shim.
import {
  createOpenAiCompatibleProvider,
  listOpenAiCompatibleModels,
  runOpenAiCompatibleAgentLoop
} from "./openai-compatible.js";

export const googleProvider = createOpenAiCompatibleProvider("google");

export const listGoogleModels = () => listOpenAiCompatibleModels("google");

export const runGoogleAgentLoop = (
  input: Omit<Parameters<typeof runOpenAiCompatibleAgentLoop>[0], "provider">
) => runOpenAiCompatibleAgentLoop({ provider: "google", ...input });
