import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { motion } from "framer-motion";

import type { Speaker, TranscriptSegment } from "./api";
import { segmentIn } from "./motion";

interface LiveTranscriptProps {
  segments: TranscriptSegment[];
  recording: boolean;
  speechActive: boolean;
  speakers?: Speaker[];
  onRenameSpeaker?: (speakerId: number, name: string) => void;
  header?: ReactNode;
  /** Playback position (ms) — highlights + follows the matching segment. */
  activeMs?: number | null;
  /** Click a timestamp to jump playback there. */
  onSeek?: (ms: number) => void;
  /** Click a line's text to correct it (past meetings only). */
  onEditSegment?: (segmentId: number, text: string) => void;
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

function SegmentText({
  segment,
  onEdit,
}: {
  segment: TranscriptSegment;
  onEdit?: (segmentId: number, text: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(segment.text);

  const editable = onEdit !== undefined && segment.id !== undefined;

  const save = () => {
    setEditing(false);
    const next = value.trim();
    if (next && next !== segment.text && segment.id !== undefined) {
      onEdit?.(segment.id, next);
    }
  };

  if (editing) {
    return (
      <textarea
        className="segment__editor"
        value={value}
        autoFocus
        rows={Math.max(1, Math.ceil(value.length / 80))}
        onChange={(e) => setValue(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            save();
          }
          if (e.key === "Escape") {
            setValue(segment.text);
            setEditing(false);
          }
        }}
      />
    );
  }

  return (
    <span
      className={"segment__text" + (editable ? " segment__text--editable" : "")}
      title={editable ? "Click to correct" : undefined}
      onClick={() => {
        if (!editable) return;
        setValue(segment.text);
        setEditing(true);
      }}
    >
      {segment.text}
    </span>
  );
}

export function LiveTranscript({
  segments,
  recording,
  speechActive,
  speakers,
  onRenameSpeaker,
  header,
  activeMs,
  onSeek,
  onEditSegment,
}: LiveTranscriptProps) {
  const endRef = useRef<HTMLDivElement | null>(null);
  const activeRef = useRef<HTMLLIElement | null>(null);
  const speakerById = useMemo(
    () => new Map((speakers ?? []).map((s) => [s.id, s])),
    [speakers],
  );

  // The segment playback is currently inside (last one whose start has passed).
  const activeIndex = useMemo(() => {
    if (activeMs == null) return -1;
    let index = -1;
    for (let i = 0; i < segments.length; i++) {
      if (segments[i].start_ms <= activeMs) index = i;
      else break;
    }
    return index;
  }, [activeMs, segments]);

  // Live view: follow the newest line. Playback: follow the active line.
  useEffect(() => {
    if (!recording) return;
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [segments.length, speechActive, recording]);

  useEffect(() => {
    if (recording || activeIndex < 0) return;
    activeRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [activeIndex, recording]);

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
      {header}
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
          const active = index === activeIndex;
          return (
            <motion.li
              className={"segment" + (active ? " segment--active" : "")}
              key={segment.id ?? `${segment.start_ms}-${index}`}
              ref={active ? activeRef : undefined}
              variants={segmentIn}
              // Live: each new line springs in. Past: appear instantly — the
              // whole-view crossfade already handles the entrance.
              initial={recording ? "initial" : false}
              animate="animate"
            >
              {onSeek ? (
                <button
                  className="segment__time segment__time--seek"
                  title="Jump playback here"
                  onClick={() => onSeek(segment.start_ms)}
                >
                  {formatTimestamp(segment.start_ms)}
                </button>
              ) : (
                <span className="segment__time">
                  {formatTimestamp(segment.start_ms)}
                </span>
              )}
              <span className="segment__body">
                {speaker && (
                  <span
                    className="segment__speaker"
                    style={{ color: speaker.color }}
                  >
                    {speakerName(speaker)}
                  </span>
                )}
                <SegmentText segment={segment} onEdit={onEditSegment} />
              </span>
            </motion.li>
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
