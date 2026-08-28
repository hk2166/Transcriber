import { useEffect, useState } from "react";

import { getModelStatus, startModelDownload, type ModelStatus } from "./api";
import { toast } from "./toast";

function formatMB(bytes: number): string {
  return `${Math.round(bytes / (1024 * 1024))} MB`;
}

/** Banner shown while the Whisper model isn't in the local cache yet. */
export function ModelBanner() {
  const [status, setStatus] = useState<ModelStatus | null>(null);
  const [epoch, setEpoch] = useState(0); // bump to re-arm polling

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const tick = async () => {
      try {
        const next = await getModelStatus();
        if (cancelled) return;
        setStatus(next);
        if (next.state === "downloading") {
          timer = window.setTimeout(tick, 800);
        }
      } catch {
        // Backend unreachable — the connection dot already reports that.
      }
    };
    tick();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [epoch]);

  if (!status || status.state === "ready" || status.state === "unknown") {
    return null;
  }

  const begin = async () => {
    try {
      await startModelDownload();
      setEpoch((e) => e + 1);
    } catch {
      toast("Couldn't start the model download.");
    }
  };

  if (status.state === "downloading") {
    const pct = Math.round(status.progress * 100);
    return (
      <div className="model-banner">
        <span>
          Downloading the speech model ({status.model}) — {pct}%
          {status.total_bytes > 0 &&
            ` · ${formatMB(status.done_bytes)} of ${formatMB(status.total_bytes)}`}
        </span>
        <div className="model-banner__bar">
          <div
            className="model-banner__fill"
            style={{ width: `${Math.max(pct, 2)}%` }}
          />
        </div>
      </div>
    );
  }

  if (status.state === "error") {
    return (
      <div className="model-banner model-banner--error">
        <span>Model download failed: {status.error}</span>
        <button className="model-banner__button" onClick={begin}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="model-banner">
      <span>
        The speech model ({status.model}) isn't downloaded yet — recording
        works, but transcription will wait for it.
      </span>
      <button className="model-banner__button" onClick={begin}>
        Download now
      </button>
    </div>
  );
}
