import { useEffect, useState } from "react";

import {
  getSettings,
  getSystemStatus,
  putSettings,
  resetAllData,
  type AudioSource,
  type Settings,
  type SystemStatus,
} from "./api";

const WHISPER_MODELS = ["base", "small", "medium"];
const SOURCES: AudioSource[] = ["mic", "system", "both"];

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

  useEffect(() => {
    getSettings().then(setSettings).catch(() => setSettings(null));
    getSystemStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  if (!settings) {
    return (
      <div className="modal-backdrop" onClick={onClose}>
        <div className="modal" onClick={(e) => e.stopPropagation()}>
          <p className="settings__loading">Loading settings…</p>
        </div>
      </div>
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
    if (!confirm("Delete ALL meetings, recordings, and settings? This cannot be undone.")) {
      return;
    }
    await resetAllData();
    onReset();
    onClose();
  };

  const ollamaModels = status?.ollama_models.length
    ? status.ollama_models
    : [settings.ollama_model];

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <header className="modal__header">
          <h2>Settings</h2>
          <button className="modal__close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>

        <div className="settings__status">
          <Status ok={status?.ollama_available} label="Ollama (summaries & chat)" />
          <Status ok={status?.blackhole_available} label="BlackHole (system audio)" />
        </div>

        <label className="settings__field">
          <span>Transcription model</span>
          <select
            value={settings.whisper_model}
            onChange={(e) => patch({ whisper_model: e.target.value })}
          >
            {WHISPER_MODELS.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <small>A change applies after restart.</small>
        </label>

        <label className="settings__field">
          <span>Summary model</span>
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

        <label className="settings__toggle">
          <input
            type="checkbox"
            checked={settings.auto_summarize}
            onChange={(e) => patch({ auto_summarize: e.target.checked })}
          />
          <span>Summarise meetings automatically</span>
        </label>

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
      </div>
    </div>
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
