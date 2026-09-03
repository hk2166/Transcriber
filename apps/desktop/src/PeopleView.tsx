import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { motion } from "framer-motion";

import {
  getPeople,
  getPerson,
  patchPerson,
  type Person,
  type PersonDetail,
} from "./api";
import { IconChevronLeft } from "./Icons";
import { viewSwap } from "./motion";
import { PrepBriefing } from "./PrepBriefing";
import { toast } from "./toast";

function personName(person: Person): string {
  return person.display_name || person.primary_email || `Person ${person.id}`;
}

/** "Met yesterday", "Met 3 weeks ago" — by calendar day, not 24-hour windows. */
function metWhen(iso: string | null): string {
  if (!iso) return "Not met yet";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  const midnight = (d: Date) =>
    new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((midnight(new Date()) - midnight(then)) / 86400000);
  const ago = (n: number, unit: string) =>
    `Met ${n} ${unit}${n === 1 ? "" : "s"} ago`;
  if (days <= 0) return "Met today";
  if (days === 1) return "Met yesterday";
  if (days < 7) return ago(days, "day");
  if (days < 30) return ago(Math.floor(days / 7), "week");
  if (days < 365) return ago(Math.floor(days / 30), "month");
  return ago(Math.floor(days / 365), "year");
}

function meetingDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function PeopleView({
  onOpenMeeting,
}: {
  onOpenMeeting: (meetingId: number) => void;
}) {
  const [people, setPeople] = useState<Person[] | null>(null);
  const [selected, setSelected] = useState<Person | null>(null);

  useEffect(() => {
    getPeople()
      .then(setPeople)
      .catch(() => {
        setPeople([]);
        toast("Couldn't load people.");
      });
  }, []);

  const back = useCallback(() => setSelected(null), []);

  // Keyed remount runs the enter animation on roster ↔ person, like App's views.
  return (
    <motion.div
      key={selected?.id ?? "roster"}
      className="view"
      variants={viewSwap}
      initial="initial"
      animate="animate"
    >
      {selected === null ? (
        <Roster people={people} onOpen={setSelected} />
      ) : (
        <PersonPage
          person={selected}
          onBack={back}
          onOpenMeeting={onOpenMeeting}
        />
      )}
    </motion.div>
  );
}

function Roster({
  people,
  onOpen,
}: {
  people: Person[] | null;
  onOpen: (person: Person) => void;
}) {
  const subtitle =
    people === null
      ? "Loading…"
      : people.length === 0
        ? "Linked from your calendar after each recording"
        : `${people.length} ${people.length === 1 ? "person" : "people"} · linked from your calendar`;

  return (
    <>
      <header className="topbar">
        <div className="topbar__title">
          <h2>People</h2>
          <p className="topbar__sub">{subtitle}</p>
        </div>
      </header>
      {people === null ? (
        <div className="transcript transcript--empty">
          <p className="transcript__placeholder">Loading people…</p>
        </div>
      ) : people.length === 0 ? (
        <div className="transcript transcript--empty">
          <p className="transcript__placeholder">
            No people yet — attendees are linked from your Google Calendar after
            each recording.
          </p>
        </div>
      ) : (
        <div className="transcript">
          <div className="people">
            {people.map((person, index) => (
              <button
                key={person.id}
                className="person-row"
                style={{ "--i": index } as CSSProperties}
                onClick={() => onOpen(person)}
              >
                <span className="person-row__main">
                  <span className="person-row__name">{personName(person)}</span>
                  {person.display_name && person.primary_email && (
                    <span className="person-row__email">{person.primary_email}</span>
                  )}
                </span>
                <span className="person-row__meta">
                  <span>
                    {person.meeting_count} meeting
                    {person.meeting_count === 1 ? "" : "s"}
                  </span>
                  <span>{metWhen(person.last_met)}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

function PersonPage({
  person,
  onBack,
  onOpenMeeting,
}: {
  person: Person;
  onBack: () => void;
  onOpenMeeting: (meetingId: number) => void;
}) {
  const [detail, setDetail] = useState<PersonDetail | null>(null);

  useEffect(() => {
    let cancelled = false;
    getPerson(person.id)
      .then((loaded) => {
        if (!cancelled) setDetail(loaded);
      })
      .catch(() => {
        if (cancelled) return;
        toast("Couldn't load that person.");
        onBack();
      });
    return () => {
      cancelled = true;
    };
  }, [person.id, onBack]);

  // Escape: if you're typing notes, blur (which saves); otherwise back to the roster.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // A sheet or confirm dialog on top owns Escape (they listen on window too).
      if (document.querySelector(".modal-backdrop, .confirm-backdrop")) return;
      const active = document.activeElement;
      if (active instanceof HTMLTextAreaElement) {
        active.blur();
        return;
      }
      onBack();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onBack]);

  const meetingCount = detail?.meetings.length ?? person.meeting_count;
  const subtitle = [
    person.display_name ? person.primary_email : null,
    `${meetingCount} meeting${meetingCount === 1 ? "" : "s"}`,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <>
      <header className="topbar">
        <div className="person-topbar">
          <button
            className="topbar__back"
            onClick={onBack}
            aria-label="Back to people"
            title="Back to people (Esc)"
          >
            <IconChevronLeft size={15} />
          </button>
          <div className="topbar__title">
            <h2>{personName(person)}</h2>
            <p className="topbar__sub">{subtitle}</p>
          </div>
        </div>
      </header>

      <div className="transcript">
        <div className="person">
          <section className="person__section">
            <h3 className="summary__heading">Meetings</h3>
            {detail === null ? (
              <p className="person__empty">Loading…</p>
            ) : detail.meetings.length === 0 ? (
              <p className="person__empty">No meetings linked yet.</p>
            ) : (
              <ul className="person__meetings">
                {detail.meetings.map((meeting) => (
                  <li key={meeting.id}>
                    <button
                      className="person__meeting"
                      onClick={() => onOpenMeeting(meeting.id)}
                      title="Open this meeting"
                    >
                      <span>{meeting.title}</span>
                      <span className="person__meeting-date">
                        {meetingDate(meeting.started_at)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {detail && (
            <NotesEditor personId={person.id} initial={detail.person.notes} />
          )}

          <PrepBriefing
            personId={person.id}
            personName={personName(person)}
            meetingCount={meetingCount}
            onOpenMeeting={onOpenMeeting}
          />
        </div>
      </div>
    </>
  );
}

/** Saves on blur — one PATCH per edit session, no keystroke chatter. */
function NotesEditor({
  personId,
  initial,
}: {
  personId: number;
  initial: string;
}) {
  const [notes, setNotes] = useState(initial);
  const [saved, setSaved] = useState(false);
  const lastSaved = useRef(initial);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const save = async () => {
    if (notes === lastSaved.current) return;
    try {
      const person = await patchPerson(personId, { notes });
      lastSaved.current = person.notes;
      setSaved(true);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setSaved(false), 1800);
    } catch {
      toast("Couldn't save the notes.");
    }
  };

  return (
    <section className="person__section">
      <div className="person__section-head">
        <h3 className="summary__heading">Notes</h3>
        {saved && (
          <span className="person__saved" role="status">
            Saved
          </span>
        )}
      </div>
      <textarea
        className="person__notes"
        value={notes}
        onChange={(event) => setNotes(event.target.value)}
        onBlur={save}
        placeholder="Things to remember about this person — context, preferences, what you owe each other…"
        rows={4}
      />
    </section>
  );
}
