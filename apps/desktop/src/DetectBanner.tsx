import type { MeetingApp } from "./api";

/** Presentational prompt for a detected meeting — App owns polling/decisions. */
export function DetectBanner({
  info,
  onRecord,
  onDismiss,
}: {
  info: MeetingApp;
  onRecord: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className="detect-banner">
      <span>
        {info.source === "microphone" ? (
          <>
            <strong>A meeting</strong> seems to be happening (microphone in
            use) — record it?
          </>
        ) : (
          <>
            <strong>{info.app}</strong> call detected — record it?
          </>
        )}
      </span>
      <div className="detect-banner__actions">
        <button className="detect-banner__record" onClick={onRecord}>
          Record
        </button>
        <button className="detect-banner__dismiss" onClick={onDismiss}>
          Ignore
        </button>
      </div>
    </div>
  );
}
