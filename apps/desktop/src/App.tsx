import { useState } from "react";

import type { AudioSource } from "./api";
import { APP_NAME } from "./config";
import { LiveTranscript } from "./LiveTranscript";
import { RecordButton } from "./RecordButton";
import { SourceSelector } from "./SourceSelector";
import { useRecorder, type RecorderStatus } from "./useRecorder";
import { VolumeMeter } from "./VolumeMeter";

const SOURCE_HINT: Record<AudioSource, string> = {
  mic: "Captures your microphone",
  system: "Captures system audio via BlackHole",
  both: "Captures mic + system audio",
};

const SOURCE_LABEL: Record<AudioSource, string> = {
  mic: "Mic",
  system: "System",
  both: "Mic + System",
};

function formatElapsed(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function subtitleFor(status: RecorderStatus): string {
  switch (status) {
    case "recording":
      return "Recording…";
    case "starting":
      return "Starting…";
    case "stopping":
      return "Saving…";
    default:
      return "Ready when you are";
  }
}

function App() {
  const [source, setSource] = useState<AudioSource>("both");
  const { status, level, speechActive, transcripts, elapsedMs, error, start, stop } =
    useRecorder();

  const recording = status === "recording";
  const busy = status === "starting" || status === "stopping";

  const handleToggle = () => {
    if (recording) {
      stop();
    } else {
      start(source);
    }
  };

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar__header">
          <span className="app-mark" aria-hidden />
          <h1 className="app-name">{APP_NAME}</h1>
        </div>

        <button className="new-meeting">
          <span aria-hidden>＋</span> New meeting
        </button>

        <nav className="meeting-list">
          <p className="meeting-list__empty">No meetings yet</p>
        </nav>

        <div className="sidebar__footer">
          <span className="dot dot--ok" />
          Backend connected
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="topbar__title">
            <h2>New recording</h2>
            <p className="topbar__sub">{subtitleFor(status)}</p>
          </div>
          <div className="topbar__right">
            {recording && (
              <span className="topbar__source">{SOURCE_LABEL[source]}</span>
            )}
            {recording && (
              <div
                className={
                  "speech-indicator" +
                  (speechActive ? " speech-indicator--active" : "")
                }
              >
                <span className="speech-dot" />
                {speechActive ? "Speech" : "Silence"}
              </div>
            )}
            <div className="elapsed">
              {formatElapsed(recording ? elapsedMs : 0)}
            </div>
          </div>
        </header>

        <LiveTranscript
          segments={transcripts}
          recording={recording}
          speechActive={speechActive}
        />

        <footer className="controlbar">
          {status === "idle" && (
            <SourceSelector value={source} onChange={setSource} disabled={false} />
          )}

          <RecordButton recording={recording} busy={busy} onClick={handleToggle} />

          <VolumeMeter level={recording ? level : 0} />

          {error ? (
            <p className="stage__error">{error}</p>
          ) : (
            <p className="stage__hint">
              {recording ? "Listening…" : SOURCE_HINT[source]}
            </p>
          )}
        </footer>
      </main>
    </div>
  );
}

export default App;