"use client";

import type { ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import { ModalShell } from "./modal-shell";
import {
  ALL_SYMBOLS_TOKEN,
  DEFAULT_RESEARCH_PROMPT,
  DEFAULT_TRADER_PROMPT,
  FALLBACK_MODELS,
  PROVIDER_ORDER,
  DEFAULT_APP_SETTINGS,
  renderRuntimeTemplate,
  mergeAppSettings,
  pickBestModel,
  uniqueSlug,
  uniqueSymbols,
  VENUE_LABELS,
  FREQUENCY_OPTIONS,
  buildDefaultState,
  type Prompt,
  type TraderPrompt,
  type Model,
  type AppSettings,
  type BotSetup,
  type SymbolResponse,
  type VenueBalance,
  type BotFormModalProps
} from "./bot-form-constants";

// Module-level cache so reopening the modal is instant. Survives until full reload.
// Lists are revalidated in the background; symbols are cached per-venue (they change rarely).
type CatalogCache = {
  prompts: Prompt[];
  models: Model[];
  traderPrompts: TraderPrompt[];
  appSettings: AppSettings;
  nextNumbers: { nextBotNumber: number; nextResearchPromptNumber: number; nextTraderPromptNumber: number } | null;
};
let catalogCache: CatalogCache | null = null;
const symbolsCache: Record<string, string[]> = {};

function InjectedPreviewBlock({
  label,
  preview,
  checked,
  disabled,
  alwaysOn,
  onCheckedChange,
  children
}: {
  label: string;
  preview: string;
  checked: boolean;
  disabled?: boolean;
  alwaysOn?: boolean;
  onCheckedChange?: (checked: boolean) => void;
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`injected-block ${checked ? "" : "injected-block-unchecked"} ${disabled ? "injected-block-disabled" : ""}`}>
      <div className="injected-block-header">
        <label className="injected-block-toggle" onClick={(event) => event.stopPropagation()}>
          <input
            type="checkbox"
            checked={checked}
            disabled={disabled}
            aria-label={`${label} injected data`}
            onChange={(event) => onCheckedChange?.(event.target.checked)}
          />
          <span className="injected-block-check" aria-hidden="true" />
        </label>
      <button
        type="button"
          className="injected-block-main"
        onClick={() => setOpen(!open)}
      >
        <span className="injected-block-label">
          {alwaysOn && <span className="injected-always-badge">always</span>}
          {label}
        </span>
        <span className="injected-block-chevron">{open ? "v" : ">"}</span>
      </button>
      </div>
      {open && (
        <>
          <pre className="injected-block-preview">{preview}</pre>
          {children && <div className="injected-block-extra">{children}</div>}
        </>
      )}
    </div>
  );
}

// ── Prompt Section Component ────────────────────────────────────────────
function PromptSection({
  phase,
  phaseColor,
  strategy,
  onStrategyChange,
  promptOptions,
  selectedVersionId,
  onVersionChange,
  promptName,
  onNameChange,
  promptBody,
  onBodyChange,
  promptBodyPlaceholder,
  savedBody,
  showBodyEditor,
  onToggleEditor,
  editedBody,
  onEditedBodyChange,
  onSaveNewVersion,
  savingVersion,
  loadingBody,
  alwaysInjected,
  optionalModules,
  activeModules,
  onToggleModule,
  pastTradesLookback,
  onLookbackChange,
  nextPromptNumber,
  providerOptions,
  selectedProvider,
  onProviderChange,
  availableModels,
  selectedModelId,
  onModelChange,
  dataLoaded,
  disabled,
}: {
  phase: "research" | "trader";
  phaseColor: string;
  strategy: "new" | "existing";
  onStrategyChange: (s: "new" | "existing") => void;
  promptOptions: { id: string; promptId?: string; label: string; body: string }[];
  selectedVersionId: string;
  onVersionChange: (id: string) => void;
  promptName: string;
  onNameChange: (n: string) => void;
  promptBody: string;
  onBodyChange: (b: string) => void;
  promptBodyPlaceholder: string;
  savedBody: string | null;
  showBodyEditor: boolean;
  onToggleEditor: (v: boolean) => void;
  editedBody: string;
  onEditedBodyChange: (b: string) => void;
  onSaveNewVersion: () => void;
  savingVersion: boolean;
  loadingBody: boolean;
  alwaysInjected: { label: string; preview: string }[];
  optionalModules?: { key: string; label: string; preview: string }[];
  activeModules?: Record<string, boolean>;
  onToggleModule?: (key: string, value: boolean) => void;
  pastTradesLookback?: number;
  onLookbackChange?: (n: number) => void;
  nextPromptNumber?: number | null;
  // Provider/Model per prompt section
  providerOptions?: string[];
  selectedProvider?: string;
  onProviderChange?: (p: string) => void;
  availableModels?: Model[];
  selectedModelId?: string;
  onModelChange?: (id: string) => void;
  dataLoaded?: boolean;
  disabled?: boolean;
}) {
  const title = phase === "research" ? "Research Prompt" : "Trader Prompt";
  const hasInjectedData = alwaysInjected.length > 0 || (optionalModules?.length ?? 0) > 0;

  const defaultPromptName = nextPromptNumber
    ? `${title} #${nextPromptNumber}`
    : title;
  const renderInjectedData = () => (
    <div className="prompt-composer-injected">
      <div className="injected-separator">
        <span className="injected-separator-label">Injected Data (auto-appended at runtime)</span>
      </div>
      {alwaysInjected.map((item) => (
        <InjectedPreviewBlock
          key={item.label}
          label={item.label}
          preview={item.preview}
          checked
          disabled
          alwaysOn
        />
      ))}
      {optionalModules?.map((m) => {
        const moduleChecked = activeModules?.[m.key] ?? false;
        return (
          <InjectedPreviewBlock
            key={m.key}
            label={m.label}
            preview={m.preview}
            checked={moduleChecked}
            onCheckedChange={(checked) => onToggleModule?.(m.key, checked)}
          >
            {m.key === "includePastTrades" && moduleChecked && pastTradesLookback !== undefined && (
              <label className="injected-lookback-field">
                <span>Lookback</span>
                <input
                  type="number"
                  min={1}
                  max={200}
                  value={pastTradesLookback}
                  onChange={(e) => onLookbackChange?.(Number(e.target.value))}
                />
              </label>
            )}
          </InjectedPreviewBlock>
        );
      })}
    </div>
  );

  return (
    <div className="form-section" style={{ borderLeft: `3px solid ${phaseColor}` }}>
      <h3 style={{ color: phaseColor }}>{title}</h3>

      <div className="segmented-control">
        <button
          type="button"
          className={`segmented-option ${strategy === "new" ? "segmented-option-active" : ""}`}
          aria-pressed={strategy === "new"}
          onClick={() => onStrategyChange("new")}
        >
          New Prompt
        </button>
        <button
          type="button"
          className={`segmented-option ${strategy === "existing" ? "segmented-option-active" : ""}`}
          aria-pressed={strategy === "existing"}
          onClick={() => onStrategyChange("existing")}
          disabled={promptOptions.length === 0}
        >
          Saved Prompt
        </button>
      </div>

      {/* Prompt Name (new prompt only) */}
      {strategy === "new" && (
        <div className="form-row" style={{ marginBottom: "12px" }}>
          <label>
            Prompt Name
            <input
              type="text"
              value={promptName}
              onChange={(e) => onNameChange(e.target.value)}
              placeholder={defaultPromptName}
            />
          </label>
        </div>
      )}

      {/* Saved prompt dropdown (existing only) — shown above Provider/Model */}
      {strategy === "existing" && (
        <div className="form-row" style={{ marginBottom: "12px" }}>
          <label>
            Prompt
            <select
              value={selectedVersionId}
              onChange={(e) => onVersionChange(e.target.value)}
              required
            >
              <option value="">Select a prompt</option>
              {promptOptions.map((p) => (
                <option key={p.id} value={p.id}>{p.label}</option>
              ))}
            </select>
          </label>
        </div>
      )}

      {providerOptions && providerOptions.length > 0 && (
        <div className="form-grid" style={{ marginBottom: "12px" }}>
          <div className="form-row">
            <label>
              Provider
              <select
                value={selectedProvider ?? ""}
                onChange={(e) => onProviderChange?.(e.target.value)}
                disabled={disabled}
              >
                {providerOptions.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="form-row">
            <label>
              Model
              <select
                value={selectedModelId ?? ""}
                onChange={(e) => onModelChange?.(e.target.value)}
                required
                disabled={disabled || !availableModels || availableModels.length === 0}
              >
                {!availableModels || availableModels.length === 0 ? (
                  <option value="">{dataLoaded ? "Not available" : "Loading..."}</option>
                ) : (
                  <>
                    <option value="">Select a model</option>
                    {availableModels.map((m) => (
                      <option key={m.id} value={m.id}>{m.name} ({m.model})</option>
                    ))}
                  </>
                )}
              </select>
            </label>
            {phase === "trader" && (
              <span className="field-help" style={{ marginTop: "4px", fontSize: "0.75rem", opacity: 0.7 }}>
                Tip: a reasoning model works best here — the trader uses tools to verify pairs and prices.
              </span>
            )}
          </div>
        </div>
      )}

      {strategy === "new" ? (
        <div className="form-grid">
          <div className="form-row" style={{ gridColumn: "1 / -1" }}>
            <label>Prompt Body</label>
            <div className="prompt-composer">
              <textarea
                className="prompt-composer-textarea"
                value={promptBody}
                onChange={(e) => onBodyChange(e.target.value)}
                placeholder={promptBodyPlaceholder}
                rows={10}
                required
              />
              {hasInjectedData && renderInjectedData()}
            </div>
          </div>
        </div>
      ) : (
        <>
          {selectedVersionId && (
            <div className="prompt-body-panel">
              <div className="prompt-body-header">
                <span className="field-help">Prompt body</span>
                {!showBodyEditor && (
                  <button
                    type="button"
                    className="btn btn-xs"
                    onClick={() => onToggleEditor(true)}
                    disabled={loadingBody || !savedBody}
                  >
                    {loadingBody ? "Loading..." : "Edit"}
                  </button>
                )}
              </div>

              {showBodyEditor ? (
                <>
                  <textarea
                    className="prompt-body-textarea"
                    value={editedBody}
                    onChange={(e) => onEditedBodyChange(e.target.value)}
                    rows={10}
                  />
                  <div className="prompt-body-actions">
                    <button
                      type="button"
                      className="btn"
                      onClick={() => { onToggleEditor(false); onEditedBodyChange(savedBody ?? ""); }}
                      disabled={savingVersion}
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={onSaveNewVersion}
                      disabled={savingVersion || !editedBody.trim()}
                    >
                      {savingVersion ? "Saving..." : "Save as new prompt"}
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <pre className="prompt-body-preview">
                    {loadingBody ? "Loading..." : (savedBody ?? "\u2014")}
                  </pre>
                  {hasInjectedData && renderInjectedData()}
                </>
              )}
            </div>
          )}
        </>
      )}

    </div>
  );
}

export function BotFormModal({ mode, botId, onClose, onSuccess }: BotFormModalProps) {
  const [prompts, setPrompts] = useState<Prompt[]>(() => catalogCache?.prompts ?? []);
  const [traderPrompts, setTraderPrompts] = useState<TraderPrompt[]>(() => catalogCache?.traderPrompts ?? []);
  const [models, setModels] = useState<Model[]>(() => catalogCache?.models ?? []);
  const [symbols, setSymbols] = useState<string[]>([]);
  const [loading, setLoading] = useState(mode === "edit");
  const [dataLoaded, setDataLoaded] = useState(false);
  // Flips true on the first real user edit so background defaults never overwrite typed input.
  const dirtyRef = useRef(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadTrigger, setLoadTrigger] = useState(0);
  const [symbolSearch, setSymbolSearch] = useState("");
  const [pairsOpen, setPairsOpen] = useState(false);
  const pairsRef = useRef<HTMLDivElement>(null);
  const [selectedResearchProvider, setSelectedResearchProvider] = useState("xai");
  const [selectedTraderProvider, setSelectedTraderProvider] = useState("xai");
  const [appSettings, setAppSettings] = useState<AppSettings>(() => catalogCache?.appSettings ?? DEFAULT_APP_SETTINGS);
  const [formData, setFormData] = useState(buildDefaultState());
  const [nextBotNumber, setNextBotNumber] = useState<number | null>(() => catalogCache?.nextNumbers?.nextBotNumber ?? null);
  const [nextResearchPromptNumber, setNextResearchPromptNumber] = useState<number | null>(() => catalogCache?.nextNumbers?.nextResearchPromptNumber ?? null);
  const [nextTraderPromptNumber, setNextTraderPromptNumber] = useState<number | null>(() => catalogCache?.nextNumbers?.nextTraderPromptNumber ?? null);

  // Research prompt editor state
  const [researchSavedBody, setResearchSavedBody] = useState<string | null>(null);
  const [researchShowEditor, setResearchShowEditor] = useState(false);
  const [researchEditedBody, setResearchEditedBody] = useState("");
  const [researchSavingVersion, setResearchSavingVersion] = useState(false);

  // Trader prompt editor state
  const [traderSavedBody, setTraderSavedBody] = useState<string | null>(null);
  const [traderShowEditor, setTraderShowEditor] = useState(false);
  const [traderEditedBody, setTraderEditedBody] = useState("");
  const [traderSavingVersion, setTraderSavingVersion] = useState(false);

  const [isSyncing, setIsSyncing] = useState(false);
  const [venueBalance, setVenueBalance] = useState<VenueBalance | null>(null);
  const [venueConnectionError, setVenueConnectionError] = useState<string | null>(null);
  const [symbolLoadError, setSymbolLoadError] = useState<string | null>(null);
  const [loadingBalance, setLoadingBalance] = useState(false);

  const providerOptions = useMemo(() => {
    const fromApi = Array.from(new Set(models.map((m) => m.provider)));
    return Array.from(new Set([...PROVIDER_ORDER, ...fromApi])).sort((a, b) => {
      const ai = PROVIDER_ORDER.indexOf(a);
      const bi = PROVIDER_ORDER.indexOf(b);
      if (ai === -1 && bi === -1) return a.localeCompare(b);
      if (ai === -1) return 1;
      if (bi === -1) return -1;
      return ai - bi;
    });
  }, [models]);

  const researchAvailableModels = useMemo(() => {
    const fromApi = models.filter((m) => m.provider === selectedResearchProvider);
    if (fromApi.length > 0) return fromApi;
    return FALLBACK_MODELS.filter((m) => m.provider === selectedResearchProvider);
  }, [models, selectedResearchProvider]);

  const traderAvailableModels = useMemo(() => {
    const fromApi = models.filter((m) => m.provider === selectedTraderProvider);
    if (fromApi.length > 0) return fromApi;
    return FALLBACK_MODELS.filter((m) => m.provider === selectedTraderProvider);
  }, [models, selectedTraderProvider]);

  // Research prompt options — sorted by last used (most recent first), then by creation date
  const researchPromptOptions = useMemo(() => {
    const opts = prompts
      .filter((prompt) => Boolean(prompt.latestVersionId))
      .map((prompt) => ({
        id: prompt.latestVersionId!,
        promptId: prompt.id,
        createdAt: prompt.latestVersionCreatedAt ?? prompt.createdAt,
        lastUsedAt: prompt.lastUsedAt,
        body: prompt.latestBody ?? "",
        label: `Research Prompt #${prompt.promptNumber} — ${prompt.name}`,
        isDefault: prompt.name.toLowerCase().includes("default")
      }));

    return opts.sort((a, b) => {
      if (a.lastUsedAt && b.lastUsedAt) return b.lastUsedAt.localeCompare(a.lastUsedAt);
      if (a.lastUsedAt && !b.lastUsedAt) return -1;
      if (!a.lastUsedAt && b.lastUsedAt) return 1;
      if (a.isDefault && !b.isDefault) return -1;
      if (!a.isDefault && b.isDefault) return 1;
      return b.createdAt.localeCompare(a.createdAt);
    });
  }, [prompts]);

  // Trader prompt options — sorted by last used (most recent first), then by creation date
  const traderPromptOptions = useMemo(() => {
    const opts = traderPrompts
      .filter((tp) => Boolean(tp.latestVersionId))
      .map((tp) => ({
        id: tp.latestVersionId!,
        promptId: tp.id,
        label: `Trader Prompt #${tp.promptNumber} — ${tp.name}`,
        body: tp.latestBody ?? "",
        lastUsedAt: tp.lastUsedAt,
        createdAt: tp.latestVersionCreatedAt ?? tp.createdAt,
      }));

    return opts.sort((a, b) => {
      if (a.lastUsedAt && b.lastUsedAt) return b.lastUsedAt.localeCompare(a.lastUsedAt);
      if (a.lastUsedAt && !b.lastUsedAt) return -1;
      if (!a.lastUsedAt && b.lastUsedAt) return 1;
      return b.createdAt.localeCompare(a.createdAt);
    });
  }, [traderPrompts]);

  const filteredSymbols = useMemo(() => {
    const query = symbolSearch.trim().toUpperCase();
    const source = query ? symbols.filter((s) => s.includes(query)) : symbols;
    return source.slice(0, 120);
  }, [symbolSearch, symbols]);

  const safeFetch = async <T,>(
    url: string,
    options: { timeoutMs?: number } = {}
  ): Promise<{ data: T | null; error: string | null }> => {
    const timeoutMs = options.timeoutMs ?? 8000;
    const controller = new AbortController();
    const timeout = setTimeout(() => {
      controller.abort(new Error(`Request timed out after ${timeoutMs}ms`));
    }, timeoutMs);
    try {
      const res = await fetch(url, { signal: controller.signal });
      if (!res.ok) {
        let errorMsg = `HTTP ${res.status}`;
        try { const errData = await res.json(); if (errData.error) errorMsg = errData.error; } catch (_) {}
        return { data: null, error: errorMsg };
      }
      return { data: (await res.json()) as T, error: null };
    } catch (e) {
      if (e instanceof Error && e.name === "AbortError") {
        return { data: null, error: `Request timed out after ${timeoutMs}ms` };
      }
      return { data: null, error: e instanceof Error ? e.message : String(e) };
    } finally {
      clearTimeout(timeout);
    }
  };

  const syncModels = async () => {
    setIsSyncing(true);
    setError(null);
    try {
      const res = await fetch("/api/internal/catalog/sync?force=true", {
        method: "POST",
        headers: { "Content-Type": "application/json" }
      });
      if (!res.ok) throw new Error(`Sync failed: ${res.status}`);
      const modelsRes = await safeFetch<Model[]>("/api/models");
      if (modelsRes.data && modelsRes.data.length > 0) {
        setModels(modelsRes.data);
        setError(null);
      } else {
        setError("Sync completed but no models available. Check XAI_API_KEY configuration.");
      }
    } catch (e) {
      setError(`Failed to sync models: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setIsSyncing(false);
    }
  };

  const resolveModelId = async (id: string, modelsList: Model[]) => {
    const needsCreation = id.startsWith("fallback:") || id.startsWith("live:");
    if (!needsCreation) return id;

    const selected = modelsList.find((m) => m.id === id);
    if (!selected) throw new Error("Selected model is invalid");

    const res = await fetch("/api/models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: selected.name,
        provider: selected.provider,
        model: selected.model,
        settings: { temperature: 0.2 }
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error ?? "Failed to create model profile");
    return data.id as string;
  };

  // Initial data load
  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setDataLoaded(false);
      setError(null);

      const [promptsRes, modelsRes, botRes, traderPromptsRes, numbersRes, appSettingsRes] = await Promise.all([
        safeFetch<Prompt[]>("/api/prompts"),
        safeFetch<Model[]>("/api/models"),
        mode === "edit" && botId ? safeFetch<BotSetup>(`/api/bots/${botId}`) : Promise.resolve({ data: null, error: null }),
        safeFetch<TraderPrompt[]>("/api/trader-prompts"),
        safeFetch<{ nextBotNumber: number; nextResearchPromptNumber: number; nextTraderPromptNumber: number }>("/api/next-numbers"),
        safeFetch<AppSettings>("/api/settings/app"),
      ]);

      if (cancelled) return;

      if (promptsRes.data) setPrompts(promptsRes.data);
      const loadedModels = modelsRes.data && modelsRes.data.length > 0 ? modelsRes.data : FALLBACK_MODELS;
      setModels(loadedModels);
      if (traderPromptsRes.data) setTraderPrompts(traderPromptsRes.data);
      if (numbersRes.data) {
        setNextBotNumber(numbersRes.data.nextBotNumber);
        setNextResearchPromptNumber(numbersRes.data.nextResearchPromptNumber);
        setNextTraderPromptNumber(numbersRes.data.nextTraderPromptNumber);
      }
      const mergedAppSettings = mergeAppSettings(appSettingsRes.data ?? DEFAULT_APP_SETTINGS);
      setAppSettings(mergedAppSettings);

      // Refresh the module cache so the next modal open is instant.
      catalogCache = {
        prompts: promptsRes.data ?? catalogCache?.prompts ?? [],
        models: loadedModels,
        traderPrompts: traderPromptsRes.data ?? catalogCache?.traderPrompts ?? [],
        appSettings: mergedAppSettings,
        nextNumbers: numbersRes.data ?? catalogCache?.nextNumbers ?? null,
      };

      if (cancelled) return;

      const errors: string[] = [];
      if (loadedModels.length === 0) errors.push("models");
      if (mode === "edit" && botId && !botRes.data) errors.push("bot config");

      if (errors.length) {
        if (errors.includes("models")) {
          setError(modelsRes.error
            ? `Could not load AI models: "${modelsRes.error}".`
            : "Could not load AI models. Try clicking 'Sync Models from xAI' below.");
        } else {
          setError(`Could not load: ${errors.join(", ")}. Check API connectivity.`);
        }
      }

      if (mode === "edit" && botRes.data) {
        const setup = botRes.data;
        const botModel = (modelsRes.data ?? []).find((m) => m.id === setup.modelProfileId);
        const traderModel = (modelsRes.data ?? []).find((m) => m.id === (setup.traderModelProfileId ?? setup.modelProfileId));
        if (botModel?.provider) setSelectedResearchProvider(botModel.provider);
        else if (setup.modelProvider) setSelectedResearchProvider(setup.modelProvider);
        if (traderModel?.provider) setSelectedTraderProvider(traderModel.provider);
        else if (setup.traderModelProvider ?? setup.modelProvider) setSelectedTraderProvider(setup.traderModelProvider ?? setup.modelProvider);

        const mergedVenue: "binance" | "binance-testnet" =
          setup.runtimeConfig.venue === "binance-testnet" ? "binance-testnet" : "binance";

        setFormData({
          name: setup.name,
          researchStrategy: "existing",
          existingPromptVersionId: setup.promptVersionId,
          newResearchName: "",
          newResearchBody: "",
          traderStrategy: setup.traderPromptVersionId ? "existing" : "new",
          existingTraderVersionId: setup.traderPromptVersionId ?? "",
          newTraderName: "",
          newTraderBody: "",
          researchModelProfileId: setup.modelProfileId,
          traderModelProfileId: setup.traderModelProfileId ?? setup.modelProfileId,
          modelProfileId: setup.modelProfileId,
          promptConfig: setup.promptConfig,
          venue: mergedVenue,
          frequencyMinutes: String(setup.runtimeConfig.frequencyMinutes),
          budgetUsdt: setup.runtimeConfig.budgetUsdt ?? 1000,
          symbolScope: setup.runtimeConfig.symbolScope,
          contextSymbols: setup.runtimeConfig.contextSymbols,
          execution: {
            ...buildDefaultState().execution,
            ...setup.runtimeConfig.execution
          }
        });
      } else if (!dirtyRef.current) {
        const settings = mergedAppSettings;
        const researchDefault = settings.agentDefaults.research;
        const traderDefault = settings.agentDefaults.trader;
        const runtimeDefault = settings.agentDefaults.runtime;
        const researchModels = loadedModels.filter((m) => m.provider === researchDefault.provider);
        const traderModels = loadedModels.filter((m) => m.provider === traderDefault.provider);
        const researchModel =
          loadedModels.find((m) => m.id === researchDefault.modelProfileId) ??
          pickBestModel(researchModels.length > 0 ? researchModels : loadedModels);
        const traderModel =
          loadedModels.find((m) => m.id === traderDefault.modelProfileId) ??
          pickBestModel(traderModels.length > 0 ? traderModels : loadedModels);
        const savedResearchPromptExists = promptsRes.data?.some((prompt) => prompt.latestVersionId === researchDefault.prompt.versionId) ?? false;
        const savedTraderPromptExists = traderPromptsRes.data?.some((prompt) => prompt.latestVersionId === traderDefault.prompt.versionId) ?? false;
        const hasAnyResearchPrompt = (promptsRes.data ?? []).some((prompt) => Boolean(prompt.latestVersionId));
        const hasAnyTraderPrompt = (traderPromptsRes.data ?? []).some((prompt) => Boolean(prompt.latestVersionId));

        if (researchModel || traderModel) {
          setSelectedResearchProvider(researchModel?.provider ?? researchDefault.provider);
          setSelectedTraderProvider(traderModel?.provider ?? traderDefault.provider);
          setFormData((cur) => ({
            ...cur,
            researchStrategy:
              researchDefault.prompt.mode === "saved" && (savedResearchPromptExists || hasAnyResearchPrompt)
                ? "existing"
                : "new",
            existingPromptVersionId: savedResearchPromptExists ? researchDefault.prompt.versionId ?? "" : cur.existingPromptVersionId,
            traderStrategy:
              traderDefault.prompt.mode === "saved" && (savedTraderPromptExists || hasAnyTraderPrompt)
                ? "existing"
                : "new",
            existingTraderVersionId: savedTraderPromptExists ? traderDefault.prompt.versionId ?? "" : cur.existingTraderVersionId,
            researchModelProfileId: cur.researchModelProfileId || researchModel?.id || "",
            traderModelProfileId: cur.traderModelProfileId || traderModel?.id || researchModel?.id || "",
            modelProfileId: cur.modelProfileId || researchModel?.id || "",
            venue: runtimeDefault.venue,
            frequencyMinutes: String(runtimeDefault.frequencyMinutes),
            budgetUsdt: runtimeDefault.budgetUsdt,
            symbolScope: runtimeDefault.symbolScope,
            execution: { ...buildDefaultState().execution, ...runtimeDefault.execution },
            name: cur.name || "",
          }));
        }
      }

      // If trader defaults to "existing" but no saved prompts exist, fall back to "new"
      if (mode === "create" && !dirtyRef.current && (!traderPromptsRes.data || traderPromptsRes.data.filter(tp => tp.latestVersionId).length === 0)) {
        setFormData((cur) => ({ ...cur, traderStrategy: "new" }));
      }
      if (mode === "create" && !dirtyRef.current && (!promptsRes.data || promptsRes.data.filter((p) => p.latestVersionId).length === 0)) {
        setFormData((cur) => ({ ...cur, researchStrategy: "new" }));
      }

      setDataLoaded(true);
      setLoading(false);
    };

    load();
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [botId, mode, loadTrigger]);

  // Set default bot name once we know the count
  useEffect(() => {
    if (mode === "create" && nextBotNumber && !formData.name) {
      setFormData((cur) => ({ ...cur, name: `#${nextBotNumber}` }));
    }
  }, [nextBotNumber, mode, formData.name]);

  // Pre-fill prompt names with real text (not just placeholder)
  useEffect(() => {
    if (mode === "create" && nextResearchPromptNumber && !formData.newResearchName) {
      setFormData((cur) => ({ ...cur, newResearchName: `Research Prompt #${nextResearchPromptNumber}` }));
    }
  }, [nextResearchPromptNumber, mode, formData.newResearchName]);

  useEffect(() => {
    if (mode === "create" && nextTraderPromptNumber && !formData.newTraderName) {
      setFormData((cur) => ({ ...cur, newTraderName: `Trader Prompt #${nextTraderPromptNumber}` }));
    }
  }, [nextTraderPromptNumber, mode, formData.newTraderName]);

  // Sync model selection when research provider changes
  useEffect(() => {
    const hasSelection = researchAvailableModels.some((model) => model.id === formData.researchModelProfileId);
    if (!hasSelection && researchAvailableModels.length > 0) {
      const best = pickBestModel(researchAvailableModels);
      if (best) setFormData((cur) => ({ ...cur, researchModelProfileId: best.id }));
    }
  }, [researchAvailableModels, formData.researchModelProfileId]);

  // Sync model selection when trader provider changes
  useEffect(() => {
    const hasSelection = traderAvailableModels.some((model) => model.id === formData.traderModelProfileId);
    if (!hasSelection && traderAvailableModels.length > 0) {
      const best = pickBestModel(traderAvailableModels);
      if (best) setFormData((cur) => ({ ...cur, traderModelProfileId: best.id }));
    }
  }, [traderAvailableModels, formData.traderModelProfileId]);

  useEffect(() => {
    if (!pairsOpen) return;
    const handlePointer = (event: MouseEvent | TouchEvent) => {
      if (pairsRef.current && !pairsRef.current.contains(event.target as Node)) {
        setPairsOpen(false);
      }
    };
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPairsOpen(false);
    };
    document.addEventListener("mousedown", handlePointer);
    document.addEventListener("touchstart", handlePointer, { passive: true });
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handlePointer);
      document.removeEventListener("touchstart", handlePointer);
      document.removeEventListener("keydown", handleKey);
    };
  }, [pairsOpen]);

  // Auto-select first research prompt
  useEffect(() => {
    if (!formData.existingPromptVersionId && researchPromptOptions[0]?.id) {
      setFormData((cur) => ({ ...cur, existingPromptVersionId: researchPromptOptions[0]!.id }));
    }
  }, [researchPromptOptions, formData.existingPromptVersionId]);

  // Auto-select first trader prompt
  useEffect(() => {
    if (!formData.existingTraderVersionId && traderPromptOptions[0]?.id) {
      setFormData((cur) => ({ ...cur, existingTraderVersionId: traderPromptOptions[0]!.id }));
    }
  }, [traderPromptOptions, formData.existingTraderVersionId]);

  // Load research prompt body when saved prompt selected
  useEffect(() => {
    if (formData.researchStrategy !== "existing" || !formData.existingPromptVersionId) {
      setResearchSavedBody(null);
      setResearchShowEditor(false);
      return;
    }
    const selected = researchPromptOptions.find((o) => o.id === formData.existingPromptVersionId);
    setResearchSavedBody(selected?.body ?? null);
    setResearchEditedBody(selected?.body ?? "");
    setResearchShowEditor(false);
  }, [formData.existingPromptVersionId, formData.researchStrategy, researchPromptOptions]);

  // Load trader prompt body when saved prompt selected
  useEffect(() => {
    if (formData.traderStrategy !== "existing" || !formData.existingTraderVersionId) {
      setTraderSavedBody(null);
      setTraderShowEditor(false);
      return;
    }
    const selected = traderPromptOptions.find((o) => o.id === formData.existingTraderVersionId);
    setTraderSavedBody(selected?.body ?? null);
    setTraderEditedBody(selected?.body ?? "");
    setTraderShowEditor(false);
  }, [formData.existingTraderVersionId, formData.traderStrategy, traderPromptOptions]);

  // Fetch venue readiness and pair universe when venue changes.
  useEffect(() => {
    let cancelled = false;
    const venue = formData.venue;
    setLoadingBalance(true);
    setVenueBalance(null);
    setVenueConnectionError(null);
    setSymbolLoadError(null);

    // Show cached pairs immediately (they change rarely); the fetch below refreshes them.
    const cachedSymbols = symbolsCache[venue];
    if (cachedSymbols?.length) setSymbols(cachedSymbols);
    else setSymbols([]);

    const loadVenue = async () => {
      try {
        // No `force` — rely on the upstream caches (balance 30s TTL, symbols 24h TTL).
        const [balanceRes, symbolsRes] = await Promise.all([
          safeFetch<VenueBalance>(`/api/venues/${venue}/balance`, { timeoutMs: 25000 }),
          safeFetch<SymbolResponse>(`/api/venues/${venue}/symbols`, { timeoutMs: 25000 })
        ]);

        if (cancelled) return;

        setVenueBalance(balanceRes.data);
        const venueLabel = VENUE_LABELS[venue] ?? venue;
        const backendError = balanceRes.data?.error ?? balanceRes.error;
        setVenueConnectionError(
          balanceRes.data?.connected
            ? null
            : `${venueLabel} account check failed: ${backendError ?? "backend returned disconnected"}`
        );

        const nextSymbols = symbolsRes.data?.symbols ?? [];

        if (nextSymbols.length) {
          symbolsCache[venue] = nextSymbols;
          setSymbols(nextSymbols);
          setSymbolLoadError(null);
        } else if (!symbolsCache[venue]?.length) {
          setSymbols([]);
          setSymbolLoadError(symbolsRes.error ?? "Pair list failed to load");
        }
      } finally {
        if (!cancelled) setLoadingBalance(false);
      }
    };

    void loadVenue();
    return () => { cancelled = true; };
  }, [formData.venue]);

  const handleSaveResearchVersion = async () => {
    setResearchSavingVersion(true);
    setError(null);
    try {
      const selected = researchPromptOptions.find((option) => option.id === formData.existingPromptVersionId);
      if (!selected?.promptId) throw new Error("Choose a saved research prompt first");
      const res = await fetch(`/api/prompts/${selected.promptId}/versions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: researchEditedBody.trim() })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Failed to save prompt");

      const promptsRes = await safeFetch<Prompt[]>("/api/prompts");
      if (promptsRes.data) setPrompts(promptsRes.data);
      setFormData((cur) => ({ ...cur, existingPromptVersionId: data.promptVersionId }));
      setResearchShowEditor(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save prompt");
    } finally {
      setResearchSavingVersion(false);
    }
  };

  const handleSaveTraderVersion = async () => {
    setTraderSavingVersion(true);
    setError(null);
    try {
      const selected = traderPromptOptions.find((option) => option.id === formData.existingTraderVersionId);
      if (!selected?.promptId) throw new Error("Choose a saved trader prompt first");
      const res = await fetch(`/api/trader-prompts/${selected.promptId}/versions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: traderEditedBody.trim() })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Failed to save trader prompt");

      // Refresh trader prompts list
      const traderPromptsRes = await safeFetch<TraderPrompt[]>("/api/trader-prompts");
      if (traderPromptsRes.data) setTraderPrompts(traderPromptsRes.data);
      setFormData((cur) => ({ ...cur, existingTraderVersionId: data.promptVersionId }));
      setTraderShowEditor(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save trader prompt");
    } finally {
      setTraderSavingVersion(false);
    }
  };

  const toggleSymbol = (symbol: string) => {
    if (formData.symbolScope === "all") return;
    dirtyRef.current = true;
    setFormData((cur) => ({
      ...cur,
      contextSymbols: cur.contextSymbols.includes(symbol)
        ? cur.contextSymbols.filter((s) => s !== symbol)
        : [...cur.contextSymbols, symbol]
    }));
  };

  const updateModule = (key: string, value: boolean) => {
    setFormData((cur) => ({
      ...cur,
      promptConfig: {
        ...cur.promptConfig,
        modules: { ...cur.promptConfig.modules, [key]: value }
      }
    }));
  };

  const resolveResearchPromptVersionId = async () => {
    if (formData.researchStrategy === "existing") {
      if (!formData.existingPromptVersionId) throw new Error("Choose a research prompt");
      return formData.existingPromptVersionId;
    }
    const res = await fetch("/api/prompts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: formData.newResearchName.trim(),
        slug: uniqueSlug(formData.newResearchName || "research"),
        initialBody: formData.newResearchBody.trim()
      })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error ?? "Failed to create prompt");
    return data.promptVersionId as string;
  };

  const selectedVenueLabel = VENUE_LABELS[formData.venue] ?? formData.venue;
  const selectedVenueConnected = Boolean(venueBalance?.connected && !venueConnectionError);
  const venueBlocked = !loadingBalance && !selectedVenueConnected;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);

    try {
      if (loadingBalance) throw new Error(`Checking ${selectedVenueLabel} connection. Try again in a moment.`);
      if (!selectedVenueConnected) throw new Error(`${selectedVenueLabel} is not connected. Add valid API credentials before creating an agent for this venue.`);
      if (!formData.researchModelProfileId) throw new Error("Choose a research model");
      if (!formData.traderModelProfileId) throw new Error("Choose a trader model");
      if (formData.researchStrategy === "new" && !formData.newResearchBody.trim()) throw new Error("Research prompt body is required");
      if (formData.symbolScope === "selected" && formData.contextSymbols.length === 0) {
        throw new Error("Select at least one pair, or choose All Pairs");
      }

      // Resolve trader prompt version ID
      let traderPromptVersionId: string | null = null;
      if (formData.traderStrategy === "existing") {
        traderPromptVersionId = formData.existingTraderVersionId || null;
        if (!traderPromptVersionId) throw new Error("Choose a trader prompt or create a new one");
      } else if (formData.newTraderBody.trim()) {
        const traderRes = await fetch("/api/trader-prompts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: formData.newTraderName.trim(),
            slug: uniqueSlug(formData.newTraderName || "trader"),
            initialBody: formData.newTraderBody.trim()
          })
        });
        const traderData = await traderRes.json();
        if (!traderRes.ok) throw new Error(traderData.error ?? "Failed to create trader prompt");
        traderPromptVersionId = traderData.promptVersionId;
      }

      const promptVersionId = await resolveResearchPromptVersionId();
      const researchModelId = await resolveModelId(formData.researchModelProfileId, researchAvailableModels);
      const traderModelId = await resolveModelId(formData.traderModelProfileId, traderAvailableModels);
      const contextSymbols =
        formData.symbolScope === "all" ? [ALL_SYMBOLS_TOKEN] : uniqueSymbols(formData.contextSymbols);

      if (mode === "create") {
        const res = await fetch("/api/bots", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: formData.name.trim(),
            slug: uniqueSlug(formData.name),
            promptVersionId,
            modelProfileId: researchModelId,
            traderModelProfileId: traderModelId,
            promptConfig: formData.promptConfig,
            traderPromptVersionId,
            runtimeConfig: {
              venue: formData.venue,
              frequencyMinutes: Number(formData.frequencyMinutes),
              assetClass: "spot",
              budgetUsdt: formData.budgetUsdt,
              symbolScope: formData.symbolScope,
              execution: formData.execution,
              contextSymbols
            }
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error ?? "Failed to create bot");
      } else {
        const res = await fetch(`/api/bots/${botId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: formData.name.trim(),
            promptVersionId,
            modelProfileId: researchModelId,
            traderModelProfileId: traderModelId,
            traderPromptVersionId,
            promptConfig: formData.promptConfig,
            runtimeConfig: {
              venue: formData.venue,
              frequencyMinutes: Number(formData.frequencyMinutes),
              assetClass: "spot",
              budgetUsdt: formData.budgetUsdt,
              symbolScope: formData.symbolScope,
              execution: formData.execution,
              contextSymbols
            }
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error ?? "Failed to update bot");
      }

      onSuccess();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Failed to save bot");
    } finally {
      setSaving(false);
    }
  };

  const templates = appSettings.promptRuntime.injectedDataTemplates;
  const optionalModules = ([
    "includeWalletOverview",
    "includePerformanceStats",
    "includeBotRanking",
    "includePastTrades"
  ] as const).map((key) => {
    const val = templates[key];
    return {
      key,
      label: val.label,
      preview: renderRuntimeTemplate(val.preview),
    };
  });

  const alwaysInjectedTrader = [
    templates.traderResearchOutput,
    templates.traderSession,
    templates.traderExecutionRules,
    templates.traderWallet,
    templates.traderTradingScope,
    templates.traderNonNegotiable
  ].map((item) => ({
    label: item.label,
    preview: renderRuntimeTemplate(item.preview)
  }));

  const activeModules: Record<string, boolean> = {
    includeWalletOverview: formData.promptConfig.modules.includeWalletOverview,
    includePerformanceStats: formData.promptConfig.modules.includePerformanceStats,
    includePastTrades: formData.promptConfig.modules.includePastTrades,
    includeBotRanking: formData.promptConfig.modules.includeBotRanking,
  };

  return (
    <ModalShell
      title={mode === "create" ? "New Agent" : "Edit Agent"}
      wide
      onClose={onClose}
    >
      {loading ? (
        <p className="muted">Loading configuration...</p>
      ) : (
        <form className="modal-form" onSubmit={handleSubmit} onChange={() => { dirtyRef.current = true; }} onInput={() => { dirtyRef.current = true; }}>

            {/* ── Core Settings ── */}
            <div className="form-section">
              <div className="section-header">
                <h3>Core Settings</h3>
                {dataLoaded && models.length === 0 && (
                  <button type="button" className="btn btn-xs" onClick={() => setLoadTrigger((n) => n + 1)}>
                    Retry
                  </button>
                )}
              </div>
              <div className="form-grid form-grid-3col">
                <div className="form-row">
                  <label>
                    Agent name
                    <input
                      type="text"
                      value={formData.name}
                      onChange={(e) => setFormData((cur) => ({ ...cur, name: e.target.value }))}
                      placeholder={nextBotNumber ? `#${nextBotNumber}` : "My Strategy"}
                    />
                  </label>
                </div>

                <div className="form-row">
                  <label>
                    Venue
                    <select
                      value={formData.venue}
                      onChange={(e) => {
                        setPairsOpen(false);
                        setSymbolSearch("");
                        setFormData((cur) => ({
                          ...cur,
                          venue: e.target.value as "binance" | "binance-testnet",
                          contextSymbols: []
                        }));
                      }}
                    >
                      <option value="binance-testnet">Binance Testnet</option>
                      <option value="binance">Binance</option>
                    </select>
                  </label>
                  <span className={`venue-status ${loadingBalance ? "" : selectedVenueConnected ? "venue-status-ok" : "venue-status-error"}`}>
                    {loadingBalance ? <Loader2 size={14} /> : selectedVenueConnected ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
                    {loadingBalance
                      ? "Checking connection"
                      : selectedVenueConnected
                        ? `$${venueBalance!.totalFreeUsdt.toFixed(2)} cash available`
                        : venueConnectionError ?? "Venue not connected"}
                  </span>
                </div>

                <div className="form-row pair-selector-field">
                  <span className="form-label">Pairs</span>
                  <div className="pairs-picker pairs-picker-inline" ref={pairsRef}>
                    <div className="segmented-control">
                      <button
                        type="button"
                        className={`segmented-option ${formData.symbolScope === "all" ? "segmented-option-active" : ""}`}
                        aria-pressed={formData.symbolScope === "all"}
                        onClick={() => {
                          dirtyRef.current = true;
                          setPairsOpen(false);
                          setSymbolSearch("");
                          setFormData((cur) => ({ ...cur, symbolScope: "all", contextSymbols: [] }));
                        }}
                      >
                        All pairs
                      </button>
                      <button
                        type="button"
                        className={`segmented-option ${formData.symbolScope === "selected" ? "segmented-option-active" : ""}`}
                        aria-pressed={formData.symbolScope === "selected"}
                        onClick={() => {
                          dirtyRef.current = true;
                          setFormData((cur) => ({ ...cur, symbolScope: "selected" }));
                          setPairsOpen(true);
                        }}
                      >
                        Selected
                      </button>
                    </div>
                    {formData.symbolScope === "all" ? (
                      <span className="field-help">All stable-quoted pairs for {selectedVenueLabel}.</span>
                    ) : (
                      <>
                        <div className="pairs-search-wrap">
                          <input
                            type="text"
                            className="pairs-search"
                            value={symbolSearch}
                            onFocus={() => setPairsOpen(true)}
                            onChange={(e) => {
                              setSymbolSearch(e.target.value);
                              setPairsOpen(true);
                            }}
                            placeholder={formData.contextSymbols.length > 0 ? `${formData.contextSymbols.length} selected - search pairs...` : "Search pairs..."}
                            aria-label="Authorized pairs"
                          />
                          {formData.contextSymbols.length > 0 && !symbolSearch && (
                            <button
                              type="button"
                              className="pairs-count-badge"
                              onClick={() => setPairsOpen(true)}
                            >
                              {formData.contextSymbols.length}
                            </button>
                          )}
                        </div>
                        {pairsOpen && (
                          <div className="pairs-dropdown" role="group" aria-label="Authorized pair choices">
                            <div className="pairs-dropdown-toolbar">
                              <span>{formData.contextSymbols.length} selected</span>
                              <button type="button" className="btn btn-xs" onClick={() => setPairsOpen(false)}>
                                Done
                              </button>
                            </div>
                            <div className="pairs-dropdown-list">
                              {symbols.length === 0 ? (
                                <p className="pairs-empty">{symbolLoadError ?? (dataLoaded ? "Pair list failed to load." : "Loading pairs...")}</p>
                              ) : filteredSymbols.length === 0 ? (
                                <p className="pairs-empty">No match</p>
                              ) : (
                                filteredSymbols.map((symbol) => (
                                  <label
                                    key={symbol}
                                    className="pairs-row"
                                  >
                                    <input
                                      type="checkbox"
                                      checked={formData.contextSymbols.includes(symbol)}
                                      onChange={() => toggleSymbol(symbol)}
                                    />
                                    <span>{symbol}</span>
                                  </label>
                                ))
                              )}
                            </div>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                  {formData.symbolScope === "selected" && formData.contextSymbols.length > 0 && (
                    <div className="selected-symbols">
                      {formData.contextSymbols.map((symbol) => (
                        <button key={symbol} type="button" className="badge badge-button" onClick={() => toggleSymbol(symbol)}>
                          {symbol} x
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                <div className="form-row">
                  <label>
                    Budget ($)
                    <input
                      type="number"
                      min={10}
                      step={10}
                      value={formData.budgetUsdt}
                      onChange={(e) => setFormData((cur) => ({ ...cur, budgetUsdt: Math.max(10, Number(e.target.value)) }))}
                    />
                  </label>
                  <span className="field-help">USDT or USDC — auto-swapped</span>
                </div>

                <div className="form-row">
                  <label>
                    Frequency
                    <select
                      value={formData.frequencyMinutes}
                      onChange={(e) => setFormData((cur) => ({ ...cur, frequencyMinutes: e.target.value }))}
                    >
                      {FREQUENCY_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                  </label>
                </div>
              </div>
              {venueBlocked && (
                <div className="form-warning" role="alert">
                  <AlertTriangle size={16} />
                  <span>{selectedVenueLabel} must be connected before this agent can be created or saved.</span>
                </div>
              )}
            </div>

            <div className="full-section">
              <PromptSection
                phase="research"
                phaseColor="#60a5fa"
                strategy={formData.researchStrategy}
                onStrategyChange={(s) => { dirtyRef.current = true; setFormData((cur) => ({ ...cur, researchStrategy: s })); }}
                promptOptions={researchPromptOptions}
                selectedVersionId={formData.existingPromptVersionId}
                onVersionChange={(id) => setFormData((cur) => ({ ...cur, existingPromptVersionId: id }))}
                promptName={formData.newResearchName}
                onNameChange={(n) => setFormData((cur) => ({ ...cur, newResearchName: n }))}
                promptBody={formData.newResearchBody}
                onBodyChange={(b) => setFormData((cur) => ({ ...cur, newResearchBody: b }))}
                promptBodyPlaceholder={DEFAULT_RESEARCH_PROMPT}
                savedBody={researchSavedBody}
                showBodyEditor={researchShowEditor}
                onToggleEditor={setResearchShowEditor}
                editedBody={researchEditedBody}
                onEditedBodyChange={setResearchEditedBody}
                onSaveNewVersion={handleSaveResearchVersion}
                savingVersion={researchSavingVersion}
                loadingBody={false}
                alwaysInjected={[{
                  label: appSettings.promptRuntime.injectedDataTemplates.researchGrounding.label,
                  preview: renderRuntimeTemplate(appSettings.promptRuntime.researchGroundingRules)
                }]}
                nextPromptNumber={nextResearchPromptNumber}
                providerOptions={providerOptions}
                selectedProvider={selectedResearchProvider}
                onProviderChange={(p) => {
                  setSelectedResearchProvider(p);
                  setFormData((cur) => ({ ...cur, researchModelProfileId: "" }));
                }}
                availableModels={researchAvailableModels}
                selectedModelId={formData.researchModelProfileId}
                onModelChange={(id) => setFormData((cur) => ({ ...cur, researchModelProfileId: id }))}
                dataLoaded={dataLoaded}
                disabled={false}
              />
            </div>

            <div className="full-section">
              <PromptSection
                phase="trader"
                phaseColor="#a78bfa"
                strategy={formData.traderStrategy}
                onStrategyChange={(s) => { dirtyRef.current = true; setFormData((cur) => ({ ...cur, traderStrategy: s })); }}
                promptOptions={traderPromptOptions}
                selectedVersionId={formData.existingTraderVersionId}
                onVersionChange={(id) => setFormData((cur) => ({ ...cur, existingTraderVersionId: id }))}
                promptName={formData.newTraderName}
                onNameChange={(n) => setFormData((cur) => ({ ...cur, newTraderName: n }))}
                promptBody={formData.newTraderBody}
                onBodyChange={(b) => setFormData((cur) => ({ ...cur, newTraderBody: b }))}
                promptBodyPlaceholder={DEFAULT_TRADER_PROMPT}
                savedBody={traderSavedBody}
                showBodyEditor={traderShowEditor}
                onToggleEditor={setTraderShowEditor}
                editedBody={traderEditedBody}
                onEditedBodyChange={setTraderEditedBody}
                onSaveNewVersion={handleSaveTraderVersion}
                savingVersion={traderSavingVersion}
                loadingBody={false}
                alwaysInjected={alwaysInjectedTrader}
                optionalModules={optionalModules}
                activeModules={activeModules}
                onToggleModule={updateModule}
                pastTradesLookback={formData.promptConfig.modules.pastTradesLookback}
                onLookbackChange={(n) => setFormData((cur) => ({
                  ...cur,
                  promptConfig: { ...cur.promptConfig, modules: { ...cur.promptConfig.modules, pastTradesLookback: n } }
                }))}
                nextPromptNumber={nextTraderPromptNumber}
                providerOptions={providerOptions}
                selectedProvider={selectedTraderProvider}
                onProviderChange={(p) => {
                  setSelectedTraderProvider(p);
                  setFormData((cur) => ({ ...cur, traderModelProfileId: "" }));
                }}
                availableModels={traderAvailableModels}
                selectedModelId={formData.traderModelProfileId}
                onModelChange={(id) => setFormData((cur) => ({ ...cur, traderModelProfileId: id }))}
                dataLoaded={dataLoaded}
                disabled={false}
              />
            </div>

            <div className="form-section">
              <h3>Deterministic settings</h3>
              <div className="deterministic-toggle-grid">
                <div className={`execution-toggle-card ${formData.execution.maxDrawdownEnabled ? "execution-toggle-card-active" : ""}`}>
                  <label className="checkbox-label execution-cap-toggle">
                    <input
                      type="checkbox"
                      checked={formData.execution.maxDrawdownEnabled}
                      onChange={(e) =>
                        setFormData((cur) => ({
                          ...cur,
                          execution: { ...cur.execution, maxDrawdownEnabled: e.target.checked }
                        }))
                      }
                    />
                    <span>
                      <strong>Kill on max drawdown</strong>
                      <small>{formData.execution.maxDrawdownEnabled ? `Kill the bot if portfolio value falls ${formData.execution.maxDrawdownPct}% from starting budget.` : "Off by default. Turn on when you want a hard loss stop."}</small>
                    </span>
                  </label>
                  {formData.execution.maxDrawdownEnabled && (
                    <label className="compact-number-field">
                      <span>Max drawdown (%)</span>
                      <input
                        type="number"
                        min={1}
                        max={100}
                        step={0.5}
                        value={formData.execution.maxDrawdownPct}
                        onChange={(e) =>
                          setFormData((cur) => ({
                            ...cur,
                            execution: {
                              ...cur.execution,
                              maxDrawdownPct: Math.min(100, Math.max(1, Number(e.target.value) || 1))
                            }
                          }))
                        }
                      />
                    </label>
                  )}
                </div>
                <label className="checkbox-label execution-cap-toggle">
                  <input
                    type="checkbox"
                    checked={formData.execution.enabled}
                    onChange={(e) =>
                      setFormData((cur) => ({ ...cur, execution: { ...cur.execution, enabled: e.target.checked } }))
                    }
                  />
                  <span>
                    <strong>Use strict order caps</strong>
                    <small>{formData.execution.enabled ? "Order placement is enabled with count, size, reserve, and order-type limits." : "Off: the bot researches and records decisions without placing orders."}</small>
                  </span>
                </label>
              </div>

              {formData.execution.enabled && (
                <>
                  <div className="checkbox-row">
                    <label className="checkbox-label">
                      <input
                        type="checkbox"
                        checked={formData.execution.allowMarketOrders}
                        onChange={(e) =>
                          setFormData((cur) => ({ ...cur, execution: { ...cur.execution, allowMarketOrders: e.target.checked } }))
                        }
                      />
                      <span>Market orders</span>
                    </label>
                    <label className="checkbox-label">
                      <input
                        type="checkbox"
                        checked={formData.execution.allowLimitOrders}
                        onChange={(e) =>
                          setFormData((cur) => ({ ...cur, execution: { ...cur.execution, allowLimitOrders: e.target.checked } }))
                        }
                      />
                      <span>Limit orders</span>
                    </label>
                  </div>

                  <div className="form-grid">
                    <div className="form-row">
                      <label>
                        Max orders / run
                        <input
                          type="number"
                          min={1}
                          max={20}
                          value={formData.execution.maxOrdersPerRun}
                          onChange={(e) =>
                            setFormData((cur) => ({ ...cur, execution: { ...cur.execution, maxOrdersPerRun: Number(e.target.value) } }))
                          }
                        />
                      </label>
                    </div>
                    <div className="form-row">
                      <label>
                        Max notional / order (USD)
                        <input
                          type="number"
                          min={1}
                          value={formData.execution.maxNotionalPerOrderUsd}
                          onChange={(e) =>
                            setFormData((cur) => ({ ...cur, execution: { ...cur.execution, maxNotionalPerOrderUsd: Number(e.target.value) } }))
                          }
                        />
                      </label>
                    </div>
                    <div className="form-row">
                      <label>
                        Min cash reserve (USD)
                        <input
                          type="number"
                          min={0}
                          value={formData.execution.minCashReserveUsd}
                          onChange={(e) =>
                            setFormData((cur) => ({ ...cur, execution: { ...cur.execution, minCashReserveUsd: Number(e.target.value) } }))
                          }
                        />
                      </label>
                    </div>
                  </div>
                </>
              )}
            </div>

            {error && (
              <div className="form-error" role="alert" aria-live="assertive">
                <p>{error}</p>
                {error.includes("models") && (
                  <div style={{ marginTop: "0.75rem", display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                    <button type="button" className="btn btn-small" onClick={syncModels} disabled={isSyncing}>
                      {isSyncing ? "Syncing..." : "Sync Models from xAI"}
                    </button>
                    <button type="button" className="btn btn-small" onClick={() => window.location.reload()} disabled={isSyncing}>
                      Reload Page
                    </button>
                  </div>
                )}
              </div>
            )}

            <div className="form-actions">
              <button type="button" className="btn" onClick={onClose} disabled={saving}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary" disabled={saving || loadingBalance || !selectedVenueConnected}>
                {saving
                  ? mode === "create" ? "Creating..." : "Saving..."
                  : mode === "create" ? "Create Agent" : "Save Changes"}
              </button>
            </div>
        </form>
      )}
    </ModalShell>
  );
}
