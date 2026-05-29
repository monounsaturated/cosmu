// module: Hugging Face provider via the OpenAI-compatible shim.
import {
  createOpenAiCompatibleProvider,
  listOpenAiCompatibleModels,
  runOpenAiCompatibleAgentLoop
} from "./openai-compatible.js";

export const huggingFaceProvider = createOpenAiCompatibleProvider("huggingface");

export const listHuggingFaceModels = () => listOpenAiCompatibleModels("huggingface");

export const runHuggingFaceAgentLoop = (
  input: Omit<Parameters<typeof runOpenAiCompatibleAgentLoop>[0], "provider">
) => runOpenAiCompatibleAgentLoop({ provider: "huggingface", ...input });
