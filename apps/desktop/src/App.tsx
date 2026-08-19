import { useCallback, useEffect, useState } from "react";

import {
  getMeetingSegments,
  getMeetings,
  getMeetingSpeakers,
  getMeetingSummary,
  renameSpeaker,
  searchSegments,
  type AudioSource,
  type Meeting,
  type MeetingSummary,
  type SearchResult,
  type Speaker,
  type TranscriptSegment,
} from "./api";
import { APP_NAME } from "./config";
import { ExportMenu } from "./ExportMenu";
import { LiveTranscript } from "./LiveTranscript";
import { MeetingChat } from "./MeetingChat";
import { RecordButton } from "./RecordButton";
import { SettingsPanel } from "./SettingsPanel";
import { SourceSelector } from "./SourceSelector";
import { SummaryPanel } from "./SummaryPanel";
import { toast } from "./toast";
import { Toasts } from "./Toasts";
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

  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [connected, setConnected] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [pastSegments, setPastSegments] = useState<TranscriptSegment[]>([]);
  const [pastSpeakers, setPastSpeakers] = useState<Speaker[]>([]);
  const [pastSummary, setPastSummary] = useState<MeetingSummary | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [meetingTab, setMeetingTab] = useState<"transcript" | "chat">("transcript");
  const [showSettings, setShowSettings] = useState(false);

  const recording = status === "recording";
  const busy = status === "starting" || status === "stopping";
  const idle = status === "idle";

  const refreshMeetings = useCallback(async () => {
    try {
      setMeetings(await getMeetings());
      setConnected(true);
    } catch {
      setConnected(false);
    }
  }, []);

  // Load meetings on mount and whenever a recording finishes (status → idle).
  useEffect(() => {
    if (idle) refreshMeetings();
  }, [idle, refreshMeetings]);

  // Debounced semantic search.
  useEffect(() => {
    const query = searchQuery.trim();
    if (!query) {
      setSearchResults([]);
      return;
    }
    const id = setTimeout(async () => {
      try {
        setSearchResults(await searchSegments(query));
      } catch {
        setSearchResults([]);
      }
    }, 250);
    return () => clearTimeout(id);
  }, [searchQuery]);

  const selectMeeting = async (id: number) => {
    setSelectedId(id);
    setMeetingTab("transcript");
    try {
      const [segments, speakers, summary] = await Promise.all([
        getMeetingSegments(id),
        getMeetingSpeakers(id),
        getMeetingSummary(id),
      ]);
      setPastSegments(segments);
      setPastSpeakers(speakers);
      setPastSummary(summary);
    } catch {
      setPastSegments([]);
      setPastSpeakers([]);
      setPastSummary(null);
      toast("Couldn't load that meeting.");
    }
  };

  const handleRenameSpeaker = async (speakerId: number, name: string) => {
    try {
      await renameSpeaker(speakerId, name);
      if (selectedId !== null) setPastSpeakers(await getMeetingSpeakers(selectedId));
    } catch {
      // Ignore — the chip keeps its previous name.
    }
  };

  const newRecording = () => {
    setSelectedId(null);
    setPastSegments([]);
    setPastSpeakers([]);
    setPastSummary(null);
  };

  const openResult = (meetingId: number) => {
    setSearchQuery("");
    selectMeeting(meetingId);
  };

  const handleToggle = () => {
    if (recording) {
      stop();
    } else {
      start(source);
    }
  };

  const selectedMeeting = meetings.find((m) => m.id === selectedId) ?? null;
  const viewingPast = selectedMeeting !== null;

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar__header">
          <span className="app-mark" aria-hidden />
          <h1 className="app-name">{APP_NAME}</h1>
        </div>

        <button className="new-meeting" onClick={newRecording} disabled={!idle}>
          <span aria-hidden>＋</span> New meeting
        </button>

        <input
          className="search-input"
          type="search"
          placeholder="Search all meetings…"
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
        />

        <nav className="meeting-list">
          {meetings.length === 0 ? (
            <p className="meeting-list__empty">No meetings yet</p>
          ) : (
            meetings.map((meeting) => (
              <button
                key={meeting.id}
                className={
                  "meeting-item" +
                  (meeting.id === selectedId ? " meeting-item--active" : "")
                }
                onClick={() => selectMeeting(meeting.id)}
                disabled={!idle}
              >
                <span className="meeting-item__title">{meeting.title}</span>
                <span className="meeting-item__meta">
                  {meeting.status === "processing"
                    ? "Finding speakers…"
                    : `${meeting.segment_count} segment${meeting.segment_count === 1 ? "" : "s"}`}
                </span>
              </button>
            ))
          )}
        </nav>

        <div className="sidebar__footer">
          <span className={"dot " + (connected ? "dot--ok" : "dot--off")} />
          {connected ? "Backend connected" : "Backend offline"}
          <button
            className="sidebar__settings"
            onClick={() => setShowSettings(true)}
            aria-label="Settings"
          >
            ⚙
          </button>
        </div>
      </aside>

      {showSettings && (
        <SettingsPanel
          onClose={() => setShowSettings(false)}
          onReset={() => {
            newRecording();
            refreshMeetings();
          }}
        />
      )}

      <Toasts />

      <main className="main">
        {searchQuery.trim() ? (
          <>
            <header className="topbar">
              <div className="topbar__title">
                <h2>Search</h2>
                <p className="topbar__sub">
                  {searchResults.length} result
                  {searchResults.length === 1 ? "" : "s"} for “{searchQuery.trim()}”
                </p>
              </div>
            </header>
            <div className="transcript">
              <div className="search-results">
                {searchResults.length === 0 ? (
                  <p className="meeting-list__empty">No matches yet</p>
                ) : (
                  searchResults.map((result) => (
                    <button
                      className="search-result"
                      key={result.segment_id}
                      onClick={() => openResult(result.meeting_id)}
                    >
                      <span className="search-result__meta">
                        {result.meeting_title}
                      </span>
                      <span className="search-result__text">{result.text}</span>
                    </button>
                  ))
                )}
              </div>
            </div>
          </>
        ) : viewingPast ? (
          <>
            <header className="topbar">
              <div className="topbar__title">
                <h2>{selectedMeeting.title}</h2>
                <p className="topbar__sub">
                  {selectedMeeting.status === "processing"
                    ? "Finding speakers…"
                    : `${selectedMeeting.segment_count} segments · ${SOURCE_LABEL[selectedMeeting.source]}`}
                </p>
              </div>
              <div className="topbar__right">
                <div className="tab-bar">
                  <button
                    className={"tab" + (meetingTab === "transcript" ? " tab--active" : "")}
                    onClick={() => setMeetingTab("transcript")}
                  >
                    Transcript
                  </button>
                  <button
                    className={"tab" + (meetingTab === "chat" ? " tab--active" : "")}
                    onClick={() => setMeetingTab("chat")}
                  >
                    Chat
                  </button>
                </div>
                <ExportMenu
                  meetingId={selectedMeeting.id}
                  title={selectedMeeting.title}
                />
              </div>
            </header>
            {meetingTab === "chat" ? (
              <MeetingChat meetingId={selectedMeeting.id} />
            ) : (
              <LiveTranscript
                segments={pastSegments}
                recording={false}
                speechActive={false}
                speakers={pastSpeakers}
                onRenameSpeaker={handleRenameSpeaker}
                header={
                  <SummaryPanel
                    summary={pastSummary}
                    processing={selectedMeeting.status === "processing"}
                  />
                }
              />
            )}
          </>
        ) : (
          <>
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
              {idle && (
                <SourceSelector value={source} onChange={setSource} disabled={false} />
              )}

              <RecordButton
                recording={recording}
                busy={busy}
                onClick={handleToggle}
              />

              <VolumeMeter level={recording ? level : 0} />

              {error ? (
                <p className="stage__error">{error}</p>
              ) : (
                <p className="stage__hint">
                  {recording ? "Listening…" : SOURCE_HINT[source]}
                </p>
              )}
            </footer>
          </>
        )}
      </main>
    </div>
  );
}

export default App;
