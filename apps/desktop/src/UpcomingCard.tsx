import type { UpcomingMeeting } from "./api";

/** "in 8 min" / "starting now" / "started 3 min ago" from the event's start. */
function relativeStart(startIso: string): string {
  const start = new Date(startIso).getTime();
  if (Number.isNaN(start)) return "";
  const minutes = Math.round((start - Date.now()) / 60000);
  if (minutes > 1) return `in ${minutes} min`;
  if (minutes >= -1) return "starting now";
  return `started ${-minutes} min ago`;
}

/** Presentational pre-call card — App owns polling, dismissal, and navigation. */
export function UpcomingCard({
  upcoming,
  onPrep,
  onDismiss,
}: {
  upcoming: UpcomingMeeting;
  onPrep: (personId: number) => void;
  onDismiss: () => void;
}) {
  const primary = upcoming.people[0];
  const others =
    (primary ? upcoming.people.length - 1 : 0) + upcoming.unknown_count;
  const plural = others === 1 ? "" : "s";
  const who = primary
    ? primary.display_name + (others > 0 ? ` + ${others} other${plural}` : "")
    : others > 0
      ? `${others} attendee${plural}`
      : "";
  const when = relativeStart(upcoming.start_iso);

  return (
    <div className="detect-banner">
      <span>
        {who && (
          <>
            <strong>{who}</strong> ·{" "}
          </>
        )}
        {upcoming.event_title}
        {when ? ` ${when}` : ""}
      </span>
      <div className="detect-banner__actions">
        {primary && (
          <button
            className="detect-banner__record"
            onClick={() => onPrep(primary.id)}
          >
            Prep
          </button>
        )}
        <button className="detect-banner__dismiss" onClick={onDismiss}>
          Dismiss
        </button>
      </div>
    </div>
  );
}
