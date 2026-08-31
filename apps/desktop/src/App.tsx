import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, MotionConfig } from "framer-motion";

import {
  getMeetingProposals,
  getMeetingSegments,
  getMeetings,
  getMeetingSpeakers,
  getMeetingSummary,
  meetingAudioUrl,
  renameSpeaker,
  searchSegments,
  updateSegmentText,
  type AudioSource,
  type Meeting,
  type MeetingSummary,
  type SearchResult,
  type Speaker,
  type SyncProposal,
  type TranscriptSegment,
} from "./api";
import { ActionItems } from "./ActionItems";
import { APP_NAME } from "./config";
import { DetectBanner } from "./DetectBanner";
import {
  IconPlus,
  IconSearch,
  IconSettings,
  IconTasks,
  IconWaveform,
} from "./Icons";
import { ExportMenu } from "./ExportMenu";
import { LiveTranscript } from "./LiveTranscript";
import { MeetingChat } from "./MeetingChat";
import { ModelBanner } from "./ModelBanner";
import { RecordButton } from "./RecordButton";
import { SettingsPanel } from "./SettingsPanel";
import { SourceSelector } from "./SourceSelector";
import { SummaryPanel } from "./SummaryPanel";
import { SyncPanel } from "./SyncPanel";
import { toast } from "./toast";
import { Toasts } from "./Toasts";
import { viewSwap } from "./motion";
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
    case "paused":
      return "Paused";
    case "starting":
      return "Starting…";
    case "stopping":
      return "Saving…";
    default:
      return "Ready when you are";
  }
}

const isTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

function App() {
  const [source, setSource] = useState<AudioSource>("both");
  const {
    status,
    level,
    speechActive,
    transcripts,
    elapsedMs,
    error,
    start,
    stop,
    pause,
    resume,
  } = useRecorder();

  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [connected, setConnected] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [pastSegments, setPastSegments] = useState<TranscriptSegment[]>([]);
  const [pastSpeakers, setPastSpeakers] = useState<Speaker[]>([]);
  const [pastSummary, setPastSummary] = useState<MeetingSummary | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [meetingTab, setMeetingTab] = useState<"transcript" | "chat" | "sync">(
    "transcript",
  );
  const [pastProposals, setPastProposals] = useState<SyncProposal[]>([]);
  const [showSettings, setShowSettings] = useState(false);
  const [showActions, setShowActions] = useState(false);

  // Playback state for the past-meeting view.
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playbackMs, setPlaybackMs] = useState<number | null>(null);
  const [playbackOk, setPlaybackOk] = useState(true);

  const recording = status === "recording";
  const paused = status === "paused";
  const sessionLive = recording || paused;
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
    setShowActions(false);
    setMeetingTab("transcript");
    setPlaybackMs(null);
    setPlaybackOk(true);
    setPastProposals([]);
    try {
      const [segments, speakers, summary, proposals] = await Promise.all([
        getMeetingSegments(id),
        getMeetingSpeakers(id),
        getMeetingSummary(id),
        getMeetingProposals(id).catch(() => []),
      ]);
      setPastSegments(segments);
      setPastSpeakers(speakers);
      setPastSummary(summary);
      setPastProposals(proposals);
    } catch {
      setPastSegments([]);
      setPastSpeakers([]);
      setPastSummary(null);
      toast("Couldn't load that meeting.");
    }
  };

  // While the selected meeting is post-processing, poll until it's ready,
  // then refresh its data and surface the new sync suggestions.
  const selectedStatus = meetings.find((m) => m.id === selectedId)?.status;
  useEffect(() => {
    if (selectedId === null || selectedStatus !== "processing") return;
    const meetingId = selectedId;
    const timer = window.setInterval(async () => {
      try {
        const fresh = await getMeetings();
        setMeetings(fresh);
        const meeting = fresh.find((m) => m.id === meetingId);
        if (meeting && meeting.status !== "processing") {
          window.clearInterval(timer);
          const [segments, speakers, summary, proposals] = await Promise.all([
            getMeetingSegments(meetingId),
            getMeetingSpeakers(meetingId),
            getMeetingSummary(meetingId),
            getMeetingProposals(meetingId).catch(() => []),
          ]);
          setPastSegments(segments);
          setPastSpeakers(speakers);
          setPastSummary(summary);
          setPastProposals(proposals);
          const pending = proposals.filter((p) => p.status === "proposed").length;
          if (pending > 0) {
            toast(
              `${pending} sync suggestion${pending === 1 ? "" : "s"} ready — open the Sync tab to review.`,
            );
          }
        }
      } catch {
        // Backend hiccup — keep polling; the connection dot reports it.
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [selectedId, selectedStatus]);

  const handleRenameSpeaker = async (speakerId: number, name: string) => {
    try {
      await renameSpeaker(speakerId, name);
      if (selectedId !== null) setPastSpeakers(await getMeetingSpeakers(selectedId));
    } catch {
      // Ignore — the chip keeps its previous name.
    }
  };

  const handleEditSegment = async (segmentId: number, text: string) => {
    if (selectedId === null) return;
    const previous = pastSegments;
    setPastSegments((segments) =>
      segments.map((s) => (s.id === segmentId ? { ...s, text } : s)),
    );
    try {
      await updateSegmentText(selectedId, segmentId, text);
    } catch {
      setPastSegments(previous);
      toast("Couldn't save that edit.");
    }
  };

  const handleSeek = (ms: number) => {
    const element = audioRef.current;
    if (!element) return;
    element.currentTime = ms / 1000;
    element.play().catch(() => {
      // Autoplay refusal — the user can press play themselves.
    });
  };

  const newRecording = () => {
    setSelectedId(null);
    setShowActions(false);
    setPastSegments([]);
    setPastSpeakers([]);
    setPastSummary(null);
  };

  const openResult = (meetingId: number) => {
    setSearchQuery("");
    selectMeeting(meetingId);
  };

  const handleToggle = () => {
    if (sessionLive) {
      stop();
    } else if (idle) {
      start(source);
    }
  };

  const startFromDetect = useCallback(() => {
    newRecording();
    start(source);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [start, source]);

  // --- Tauri shell glue (tray + global hotkey) — no-ops in the dev browser.
  const toggleRef = useRef(handleToggle);
  useEffect(() => {
    toggleRef.current = handleToggle;
  });

  useEffect(() => {
    if (!isTauri) return;
    let disposed = false;
    let unlisten: (() => void) | undefined;
    import("@tauri-apps/api/event")
      .then(({ listen }) => listen("toggle-record", () => toggleRef.current()))
      .then((fn) => {
        if (disposed) fn();
        else unlisten = fn;
      })
      .catch(() => {});
    return () => {
      disposed = true;
      unlisten?.();
    };
  }, []);

  useEffect(() => {
    if (!isTauri) return;
    import("@tauri-apps/api/core")
      .then(({ invoke }) => invoke("set_recording", { recording: sessionLive }))
      .catch(() => {});
  }, [sessionLive]);

  const selectedMeeting = meetings.find((m) => m.id === selectedId) ?? null;
  const viewingPast = selectedMeeting !== null;
  const pendingProposals = pastProposals.filter(
    (p) => p.status === "proposed" || p.status === "failed",
  ).length;

  // Identity of the currently shown view — drives the crossfade transition.
  const viewKey = searchQuery.trim()
    ? "search"
    : showActions
      ? "actions"
      : viewingPast
        ? `past-${selectedId}`
        : "live";

  return (
    <MotionConfig reducedMotion="user">
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar__header">
          <span className="app-mark" aria-hidden>
            <IconWaveform size={15} />
          </span>
          <h1 className="app-name">{APP_NAME}</h1>
        </div>

        <button className="new-meeting" onClick={newRecording} disabled={!idle}>
          <IconPlus size={15} /> New meeting
        </button>

        <button
          className={"nav-actions" + (showActions ? " nav-actions--active" : "")}
          onClick={() => {
            setSelectedId(null);
            setShowActions(true);
          }}
          disabled={!idle}
        >
          <IconTasks size={15} /> Action items
        </button>

        <div className="search-field">
          <IconSearch size={15} className="search-field__icon" />
          <input
            className="search-input"
            type="search"
            placeholder="Search all meetings…"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
          />
        </div>

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
            <IconSettings size={16} />
          </button>
        </div>
      </aside>

      <AnimatePresence>
        {showSettings && (
          <SettingsPanel
            onClose={() => setShowSettings(false)}
            onReset={() => {
              newRecording();
              refreshMeetings();
            }}
          />
        )}
      </AnimatePresence>

      <Toasts />

      <main className="main">
        {/* Keyed remount runs the enter animation on every view change —
            simpler and more robust than a wait-mode exit handoff. */}
        <motion.div
          key={viewKey}
          className="view"
          variants={viewSwap}
          initial="initial"
          animate="animate"
        >
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
        ) : showActions ? (
          <>
            <header className="topbar">
              <div className="topbar__title">
                <h2>Action items</h2>
                <p className="topbar__sub">Collected from every meeting summary</p>
              </div>
            </header>
            <ActionItems onOpenMeeting={selectMeeting} />
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
                  <button
                    className={"tab" + (meetingTab === "sync" ? " tab--active" : "")}
                    onClick={() => setMeetingTab("sync")}
                  >
                    Sync
                    {pendingProposals > 0 && (
                      <span className="tab__badge">{pendingProposals}</span>
                    )}
                  </button>
                </div>
                <ExportMenu
                  meetingId={selectedMeeting.id}
                  title={selectedMeeting.title}
                />
              </div>
            </header>
            {meetingTab === "transcript" &&
              playbackOk &&
              selectedMeeting.status !== "recording" && (
                <div className="playback">
                  <audio
                    key={selectedMeeting.id}
                    ref={audioRef}
                    src={meetingAudioUrl(selectedMeeting.id)}
                    controls
                    preload="metadata"
                    onTimeUpdate={(event) =>
                      setPlaybackMs(event.currentTarget.currentTime * 1000)
                    }
                    onError={() => setPlaybackOk(false)}
                  />
                </div>
              )}
            {meetingTab !== "sync" && pendingProposals > 0 && (
              <div className="detect-banner">
                <span>
                  <strong>{pendingProposals}</strong> sync suggestion
                  {pendingProposals === 1 ? "" : "s"} ready — file this meeting
                  into your apps?
                </span>
                <div className="detect-banner__actions">
                  <button
                    className="detect-banner__record"
                    onClick={() => setMeetingTab("sync")}
                  >
                    Review
                  </button>
                </div>
              </div>
            )}
            {meetingTab === "sync" ? (
              <SyncPanel
                meetingId={selectedMeeting.id}
                onChange={setPastProposals}
              />
            ) : meetingTab === "chat" ? (
              <MeetingChat meetingId={selectedMeeting.id} />
            ) : (
              <LiveTranscript
                segments={pastSegments}
                recording={false}
                speechActive={false}
                speakers={pastSpeakers}
                onRenameSpeaker={handleRenameSpeaker}
                activeMs={playbackMs}
                onSeek={playbackOk ? handleSeek : undefined}
                onEditSegment={handleEditSegment}
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
                {sessionLive && (
                  <span className="topbar__source">{SOURCE_LABEL[source]}</span>
                )}
                {paused && <span className="paused-badge">Paused</span>}
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
                  {formatElapsed(sessionLive ? elapsedMs : 0)}
                </div>
              </div>
            </header>

            <ModelBanner />
            <DetectBanner active={idle} onRecord={startFromDetect} />

            <LiveTranscript
              segments={transcripts}
              recording={sessionLive}
              speechActive={speechActive}
            />

            <footer className="controlbar">
              {idle && (
                <SourceSelector value={source} onChange={setSource} disabled={false} />
              )}

              <RecordButton
                recording={sessionLive}
                busy={busy}
                onClick={handleToggle}
              />

              {sessionLive && (
                <button
                  className="pause-button"
                  onClick={paused ? resume : pause}
                  title={paused ? "Resume recording" : "Pause recording"}
                >
                  {paused ? "Resume" : "Pause"}
                </button>
              )}

              <VolumeMeter level={recording ? level : 0} />

              {error ? (
                <p className="stage__error">{error}</p>
              ) : (
                <p className="stage__hint">
                  {recording
                    ? "Listening…"
                    : paused
                      ? "Paused — nothing is being recorded."
                      : SOURCE_HINT[source]}
                </p>
              )}
            </footer>
          </>
        )}
          </motion.div>
      </main>
    </div>
    </MotionConfig>
  );
}

export default App;
