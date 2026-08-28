import { useEffect, useRef, useState } from "react";

import { getMeetingApp, type MeetingApp } from "./api";
import { toast } from "./toast";

/** Polls for a live Zoom/Webex call and prompts (or auto-starts) recording. */
export function DetectBanner({
  active,
  onRecord,
}: {
  /** Poll + show only while the live view is idle. */
  active: boolean;
  onRecord: () => void;
}) {
  const [info, setInfo] = useState<MeetingApp | null>(null);
  const [dismissedSince, setDismissedSince] = useState<number | null>(null);
  const autoFiredRef = useRef<number | null>(null);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const detected = await getMeetingApp();
        if (!cancelled) setInfo(detected);
      } catch {
        // Backend unreachable — the connection dot already reports that.
      }
    };
    tick();
    const id = window.setInterval(tick, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [active]);

  // Auto mode: start once per detection episode.
  useEffect(() => {
    if (
      !active ||
      !info?.app ||
      info.recording ||
      info.mode !== "auto" ||
      info.since == null ||
      autoFiredRef.current === info.since
    ) {
      return;
    }
    autoFiredRef.current = info.since;
    toast(`Recording started — ${info.app} call detected.`);
    onRecord();
  }, [info, active, onRecord]);

  if (
    !active ||
    !info?.app ||
    info.recording ||
    info.mode !== "prompt" ||
    dismissedSince === info.since
  ) {
    return null;
  }

  return (
    <div className="detect-banner">
      <span>
        <strong>{info.app}</strong> call detected — record it?
      </span>
      <div className="detect-banner__actions">
        <button className="detect-banner__record" onClick={onRecord}>
          Record
        </button>
        <button
          className="detect-banner__dismiss"
          onClick={() => setDismissedSince(info.since)}
        >
          Ignore
        </button>
      </div>
    </div>
  );
}
