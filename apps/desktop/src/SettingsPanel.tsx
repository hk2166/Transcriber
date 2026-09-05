import { useEffect, useState } from "react";
import { motion } from "framer-motion";

import { scrim, sheet } from "./motion";
import {
  getIntegrations,
  getLLMProviders,
  getSettings,
  getSystemStatus,
  putSettings,
  resetAllData,
  testLLM,
  type AudioSource,
  type IntegrationInfo,
  type LLMProvider,
  type Settings,
  type SystemStatus,
} from "./api";
import { confirmDialog } from "./confirm";
import { EngineSelector } from "./EngineSelector";
import { GoogleConnect } from "./GoogleConnect";
import { NotionConnect } from "./NotionConnect";
import { IconClose } from "./Icons";
const SOURCES: AudioSource[] = ["mic", "system", "both"];
const REFINE_MODELS = [
  { id: "base", label: "Faster (Whisper Base)" },
  { id: "small", label: "Balanced (Whisper Small)" },
  { id: "medium", label: "Accurate (Whisper Medium)" },
  { id: "large-v3", label: "Best (Whisper Large v3)" },
];
const AUTO_RECORD_LABELS: Record<Settings["auto_record"], string> = {
  off: "Off",
  prompt: "Ask me",
  auto: "Start automatically",
};

export function SettingsPanel({
  onClose,
  onReset,
}: {
  onClose: () => void;
  onReset: () => void;
}) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [saving, setSaving] = useState(false);
  const [providers, setProviders] = useState<LLMProvider[]>([]);
  const [integrations, setIntegrations] = useState<IntegrationInfo[]>([]);
  const [testState, setTestState] = useState<
    { kind: "idle" } | { kind: "testing" } | { kind: "ok" } | { kind: "fail"; message: string }
  >({ kind: "idle" });

  useEffect(() => {
    getSettings().then(setSettings).catch(() => setSettings(null));
    getSystemStatus().then(setStatus).catch(() => setStatus(null));
    getLLMProviders().then(setProviders).catch(() => setProviders([]));
    getIntegrations().then(setIntegrations).catch(() => setIntegrations([]));
  }, []);

  // Dismiss on Escape, like a native macOS sheet.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!settings) {
    return (
      <motion.div
        className="modal-backdrop"
        onClick={onClose}
        variants={scrim}
        initial="initial"
        animate="animate"
        exit="exit"
      >
        <motion.div
          className="modal"
          onClick={(e) => e.stopPropagation()}
          variants={sheet}
        >
          <p className="settings__loading">Loading settings…</p>
        </motion.div>
      </motion.div>
    );
  }

  const patch = (p: Partial<Settings>) => setSettings({ ...settings, ...p });

  const save = async () => {
    setSaving(true);
    try {
      await putSettings(settings);
      onClose();
    } finally {
      setSaving(false);
    }
  };

  const wipe = async () => {
    const ok = await confirmDialog({
      message:
        "Delete ALL meetings, recordings, and settings? This cannot be undone.",
      confirmLabel: "Delete everything",
      danger: true,
    });
    if (!ok) return;
    await resetAllData();
    onReset();
    onClose();
  };

  const ollamaModels = status?.ollama_models.length
    ? status.ollama_models
    : [settings.ollama_model];

  const provider = providers.find((p) => p.id === settings.llm_provider);

  const runTest = async () => {
    setTestState({ kind: "testing" });
    try {
      const result = await testLLM(settings);
      setTestState(
        result.ok
          ? { kind: "ok" }
          : { kind: "fail", message: result.error ?? "No reply from the model." },
      );
    } catch {
      setTestState({ kind: "fail", message: "Couldn't reach the backend." });
    }
  };

  return (
    <motion.div
      className="modal-backdrop"
      onClick={onClose}
      variants={scrim}
      initial="initial"
      animate="animate"
      exit="exit"
    >
      <motion.div
        className="modal modal--wide"
        onClick={(e) => e.stopPropagation()}
        variants={sheet}
      >
        <header className="modal__header">
          <h2>Settings</h2>
          <button className="modal__close" onClick={onClose} aria-label="Close">
            <IconClose size={16} />
          </button>
        </header>

        <div className="settings__status">
          <Status ok={status?.ollama_available} label="Ollama (summaries & chat)" />
          <Status ok={status?.blackhole_available} label="BlackHole (system audio)" />
        </div>

        <div className="settings__columns">
        <div className="settings__col">
        <div className="settings__field">
          <span>Transcription engine</span>
          <EngineSelector />
        </div>
        </div>

        <div className="settings__col">
        <div className="settings__group">
          <label className="settings__field">
            <span>AI provider (summaries &amp; chat)</span>
            <select
              value={settings.llm_provider}
              onChange={(e) => {
                patch({ llm_provider: e.target.value, llm_model: "" });
                setTestState({ kind: "idle" });
              }}
            >
              {(providers.length
                ? providers
                : [{ id: "ollama", label: "Local (Ollama)" } as LLMProvider]
              ).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
            {provider && !provider.local && (
              <small className="settings__privacy">
                Transcripts are sent to {provider.label} for summaries and chat.
                Local (Ollama) keeps everything on this Mac.
              </small>
            )}
          </label>

          {settings.llm_provider === "ollama" ? (
            <label className="settings__field">
              <span>Model</span>
              <select
                value={settings.ollama_model}
                onChange={(e) => patch({ ollama_model: e.target.value })}
              >
                {ollamaModels.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <>
              {provider?.needs_key && (
                <label className="settings__field">
                  <span>API key</span>
                  <input
                    type="password"
                    autoComplete="off"
                    placeholder={`${provider.label} API key`}
                    value={settings.api_keys[settings.llm_provider] ?? ""}
                    onChange={(e) => {
                      patch({
                        api_keys: {
                          ...settings.api_keys,
                          [settings.llm_provider]: e.target.value,
                        },
                      });
                      setTestState({ kind: "idle" });
                    }}
                  />
                  {provider.key_url && (
                    <small>
                      Stored only on this Mac.{" "}
                      <a href={provider.key_url} target="_blank" rel="noreferrer">
                        Get an API key ↗
                      </a>
                    </small>
                  )}
                </label>
              )}
              {provider?.needs_base_url && (
                <label className="settings__field">
                  <span>Server URL</span>
                  <input
                    type="text"
                    placeholder="http://localhost:1234/v1"
                    value={settings.llm_base_url}
                    onChange={(e) => patch({ llm_base_url: e.target.value })}
                  />
                  <small>Any OpenAI-compatible server (LM Studio, llama.cpp, vLLM…).</small>
                </label>
              )}
              <label className="settings__field">
                <span>Model</span>
                <input
                  type="text"
                  placeholder={provider?.default_model || "model id"}
                  value={settings.llm_model}
                  onChange={(e) => patch({ llm_model: e.target.value })}
                />
                {provider?.default_model && (
                  <small>Leave empty for {provider.default_model}.</small>
                )}
              </label>
            </>
          )}

          <div className="settings__testrow">
            <button
              className="settings__secondary"
              onClick={runTest}
              disabled={testState.kind === "testing"}
            >
              {testState.kind === "testing" ? "Testing…" : "Test connection"}
            </button>
            {testState.kind === "ok" && (
              <small className="settings__test-ok">Connected ✓</small>
            )}
            {testState.kind === "fail" && (
              <small className="settings__error">{testState.message}</small>
            )}
          </div>
        </div>

        <label className="settings__toggle">
          <input
            type="checkbox"
            checked={settings.auto_summarize}
            onChange={(e) => patch({ auto_summarize: e.target.checked })}
          />
          <span>Summarise meetings automatically</span>
        </label>

        <div className="settings__field">
          <label className="settings__toggle">
            <input
              type="checkbox"
              checked={settings.refine_transcript}
              onChange={(e) => patch({ refine_transcript: e.target.checked })}
            />
            <span>Refine transcript after each meeting</span>
          </label>
          <small>
            The live transcript is fast but rough. When a meeting ends, Confab
            re-transcribes the whole recording for cleaner text and punctuation,
            then labels the speakers — replacing the live version.
          </small>
          {settings.refine_transcript && (
            <label className="settings__field settings__subfield">
              <span>Refine accuracy</span>
              <select
                value={settings.refine_model}
                onChange={(e) => patch({ refine_model: e.target.value })}
              >
                {REFINE_MODELS.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
        </div>

        <div className="settings__col">
        <label className="settings__field">
          <span>Default audio source</span>
          <select
            value={settings.default_source}
            onChange={(e) => patch({ default_source: e.target.value as AudioSource })}
          >
            {SOURCES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>

        <label className="settings__field">
          <span>Speech sensitivity ({settings.vad_threshold.toFixed(2)})</span>
          <input
            type="range"
            min="0.2"
            max="0.8"
            step="0.05"
            value={settings.vad_threshold}
            onChange={(e) => patch({ vad_threshold: Number(e.target.value) })}
          />
        </label>

        <label className="settings__field">
          <span>When a meeting starts (Zoom, Meet, Teams…)</span>
          <select
            value={settings.auto_record}
            onChange={(e) =>
              patch({ auto_record: e.target.value as Settings["auto_record"] })
            }
          >
            {(Object.keys(AUTO_RECORD_LABELS) as Settings["auto_record"][]).map(
              (mode) => (
                <option key={mode} value={mode}>
                  {AUTO_RECORD_LABELS[mode]}
                </option>
              ),
            )}
          </select>
        </label>

        <div className="settings__field">
          <span>Sync suggestions</span>
          <small>
            After each meeting, Confab proposes items for these apps. Nothing
            is sent until you approve it on the Sync tab.
          </small>
          {integrations.map((integration) => (
            <label className="settings__toggle" key={integration.id}>
              <input
                type="checkbox"
                disabled={!integration.configured}
                checked={
                  settings.integrations_enabled[integration.id] ?? true
                }
                onChange={(e) =>
                  patch({
                    integrations_enabled: {
                      ...settings.integrations_enabled,
                      [integration.id]: e.target.checked,
                    },
                  })
                }
              />
              <span>
                {integration.label}
                {integration.configured ? "" : " (set up below)"}
              </span>
            </label>
          ))}
        </div>

        <NotionConnect
          settings={settings}
          patch={patch}
          configured={
            integrations.find((i) => i.id === "notion")?.configured ?? false
          }
        />
        <GoogleConnect />
        </div>
        </div>

        <footer className="settings__footer">
          <button className="settings__danger" onClick={wipe}>
            Delete all data
          </button>
          <div className="settings__actions">
            <button className="settings__cancel" onClick={onClose}>
              Cancel
            </button>
            <button className="settings__save" onClick={save} disabled={saving}>
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </footer>
      </motion.div>
    </motion.div>
  );
}

function Status({ ok, label }: { ok: boolean | undefined; label: string }) {
  return (
    <div className="settings__check">
      <span className={"dot " + (ok ? "dot--ok" : "dot--off")} />
      {label}
      <span className="settings__check-state">{ok ? "ready" : "not detected"}</span>
    </div>
  );
}
