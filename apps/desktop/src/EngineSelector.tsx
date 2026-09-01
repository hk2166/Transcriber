import { useEffect, useState } from "react";

import {
  getASREngines,
  getModelStatus,
  getSettings,
  putSettings,
  startModelDownload,
  type ASREngine,
} from "./api";
import { confirmDialog } from "./confirm";
import { toast } from "./toast";

const isTauri =
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

async function restartApp(): Promise<boolean> {
  if (!isTauri) return false;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("restart_app"); // process exits; call never really returns
    return true;
  } catch {
    return false;
  }
}

/** Transcription engines as a list: which is active, which are downloaded,
 *  a Download action per engine, and switch-with-restart. */
export function EngineSelector() {
  const [engines, setEngines] = useState<ASREngine[] | null>(null);
  const [progress, setProgress] = useState<Record<string, number>>({});
  const [switching, setSwitching] = useState(false);

  const load = () => getASREngines().then(setEngines).catch(() => setEngines([]));
  useEffect(() => {
    load();
  }, []);

  const active = engines?.find((e) => e.active)?.id;

  const download = async (id: string) => {
    setProgress((p) => ({ ...p, [id]: 0 }));
    try {
      await startModelDownload(id);
    } catch {
      setProgress((p) => {
        const next = { ...p };
        delete next[id];
        return next;
      });
      toast("Couldn't start the download.");
      return;
    }
    const poll = async () => {
      const status = await getModelStatus(id).catch(() => null);
      if (!status) return;
      if (status.state === "downloading") {
        setProgress((p) => ({ ...p, [id]: status.progress }));
        window.setTimeout(poll, 800);
      } else {
        setProgress((p) => {
          const next = { ...p };
          delete next[id];
          return next;
        });
        load();
        if (status.state === "error") toast("Model download failed.");
      }
    };
    window.setTimeout(poll, 500);
  };

  const switchTo = async (engine: ASREngine) => {
    if (engine.id === active || switching) return;
    const after = isTauri
      ? "Confab will restart to load it."
      : "It loads on your next recording.";
    const ok = await confirmDialog({
      message: `Switch transcription to “${engine.label}”? ${after}`,
      confirmLabel: isTauri ? "Switch & restart" : "Switch",
    });
    if (!ok) return;
    setSwitching(true);
    try {
      const settings = await getSettings();
      await putSettings({ ...settings, transcription_engine: engine.id });
      if (isTauri) {
        toast("Switching engine — restarting Confab…");
        const ok = await restartApp();
        if (!ok) {
          await load();
          toast("Engine switched — restart Confab to apply.");
        }
      } else {
        await load();
        toast(`Switched to ${engine.label} — loads on your next recording.`);
      }
    } catch {
      toast("Couldn't switch engine.");
    } finally {
      setSwitching(false);
    }
  };

  if (engines === null) {
    return <p className="settings__loading">Loading engines…</p>;
  }

  return (
    <div className="engines">
      {engines.map((engine) => {
        const pct = progress[engine.id];
        const isActive = engine.id === active;
        const langs =
          engine.languages === "English"
            ? "English"
            : `${engine.languages} languages`;
        return (
          <div
            key={engine.id}
            className={"engine-row" + (isActive ? " engine-row--active" : "")}
          >
            <button
              className="engine-row__pick"
              onClick={() => switchTo(engine)}
              disabled={switching}
            >
              <span className="engine-row__radio" aria-hidden />
              <span className="engine-row__text">
                <span className="engine-row__label">
                  {engine.label}
                  {isActive && <span className="engine-row__active">Active</span>}
                </span>
                <span className="engine-row__meta">
                  {engine.note} · {langs} · ~{engine.size_mb} MB
                </span>
              </span>
            </button>
            <span className="engine-row__status">
              {pct !== undefined ? (
                <span className="engine-row__downloading">
                  Downloading… {Math.round(pct * 100)}%
                </span>
              ) : engine.downloaded ? (
                <span className="engine-row__done">Downloaded ✓</span>
              ) : (
                <button
                  className="engine-row__download"
                  onClick={() => download(engine.id)}
                >
                  Download
                </button>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}
