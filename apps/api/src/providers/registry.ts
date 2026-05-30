// module: LLM provider registry — add providers here, keep concrete adapters isolated.
import type { LLMProvider } from "./llm.js";
import { xaiProvider } from "./xai.js";
import { nousProvider } from "./nous.js";
import { openaiProvider } from "./openai.js";
import { anthropicProvider } from "./anthropic.js";
import { huggingFaceProvider } from "./huggingface.js";
import { googleProvider } from "./google.js";
import { mistralProvider } from "./mistral.js";

const providers: Record<string, LLMProvider> = {
  xai: xaiProvider,
  nous: nousProvider,
  openai: openaiProvider,
  anthropic: anthropicProvider,
  huggingface: huggingFaceProvider,
  google: googleProvider,
  mistral: mistralProvider
};

export const getProvider = (name: string): LLMProvider => {
  const provider = providers[name];
  if (!provider) {
    throw new Error(`Unknown LLM provider: ${name}. Available: ${Object.keys(providers).join(", ")}`);
  }
  return provider;
};

export const registerProvider = (provider: LLMProvider) => {
  providers[provider.name] = provider;
};

export const listProviderNames = (): string[] => Object.keys(providers);
