import { useEffect, useRef } from "react";

import type { TranscriptSegment } from "./api";

interface LiveTranscriptProps {
  segments: TranscriptSegment[];
  recording: boolean;
  speechActive: boolean;
}

function formatTimestamp(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function LiveTranscript({
  segments,
  recording,
  speechActive,
}: LiveTranscriptProps) {
  const endRef = useRef<HTMLDivElement | null>(null);

  // Keep the newest line in view as speech arrives.
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
      <ol className="transcript__list">
        {segments.map((segment, index) => (
          <li className="segment" key={`${segment.start_ms}-${index}`}>
            <span className="segment__time">
              {formatTimestamp(segment.start_ms)}
            </span>
            <span className="segment__text">{segment.text}</span>
          </li>
        ))}
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
