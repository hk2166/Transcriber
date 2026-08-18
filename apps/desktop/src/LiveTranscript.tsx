import { useEffect, useMemo, useRef, useState } from "react";

import type { Speaker, TranscriptSegment } from "./api";

interface LiveTranscriptProps {
  segments: TranscriptSegment[];
  recording: boolean;
  speechActive: boolean;
  speakers?: Speaker[];
  onRenameSpeaker?: (speakerId: number, name: string) => void;
}

function formatTimestamp(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function speakerName(speaker: Speaker): string {
  return speaker.name ?? speaker.label;
}

function SpeakerChip({
  speaker,
  onRename,
}: {
  speaker: Speaker;
  onRename?: (speakerId: number, name: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(speakerName(speaker));

  const save = () => {
    setEditing(false);
    const next = value.trim();
    if (next && next !== speakerName(speaker)) onRename?.(speaker.id, next);
  };

  if (editing) {
    return (
      <input
        className="speaker-chip__input"
        value={value}
        autoFocus
        onChange={(e) => setValue(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === "Enter") save();
          if (e.key === "Escape") setEditing(false);
        }}
      />
    );
  }

  return (
    <button
      className="speaker-chip"
      onClick={() => {
        setValue(speakerName(speaker));
        setEditing(true);
      }}
      title="Click to rename"
      disabled={!onRename}
    >
      <span className="speaker-chip__dot" style={{ background: speaker.color }} />
      {speakerName(speaker)}
    </button>
  );
}

export function LiveTranscript({
  segments,
  recording,
  speechActive,
  speakers,
  onRenameSpeaker,
}: LiveTranscriptProps) {
  const endRef = useRef<HTMLDivElement | null>(null);
  const speakerById = useMemo(
    () => new Map((speakers ?? []).map((s) => [s.id, s])),
    [speakers],
  );

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [segments.length, speechActive, recording]);

  if (!recording && segments.length === 0) {
    return (
      <div className="transcript transcript--empty">
        <p className="transcript__placeholder">
          Your transcript will appear here as you speak.
        </p>
      </div>
    );
  }

  return (
    <div className="transcript">
      {speakers && speakers.length > 0 && (
        <div className="speaker-legend">
          {speakers.map((speaker) => (
            <SpeakerChip
              key={speaker.id}
              speaker={speaker}
              onRename={onRenameSpeaker}
            />
          ))}
        </div>
      )}

      <ol className="transcript__list">
        {segments.map((segment, index) => {
          const speaker =
            segment.speaker_id != null
              ? speakerById.get(segment.speaker_id)
              : undefined;
          return (
            <li className="segment" key={`${segment.start_ms}-${index}`}>
              <span className="segment__time">
                {formatTimestamp(segment.start_ms)}
              </span>
              <span className="segment__body">
                {speaker && (
                  <span
                    className="segment__speaker"
                    style={{ color: speaker.color }}
                  >
                    {speakerName(speaker)}
                  </span>
                )}
                <span className="segment__text">{segment.text}</span>
              </span>
            </li>
          );
        })}
      </ol>

      {recording && (
        <p className="transcript__status">
          {speechActive ? (
            <>
              <span className="transcript__pulse" />
              Transcribing…
            </>
          ) : segments.length === 0 ? (
            "Listening for speech…"
          ) : (
            "Waiting for the next words…"
          )}
        </p>
      )}

      <div ref={endRef} />
    </div>
  );
}
