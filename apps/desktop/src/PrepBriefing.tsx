import { useEffect, useRef, useState, type ReactNode } from "react";

import { ApiError, streamPrep, type PrepSource } from "./api";

type LensStatus = "loading" | "streaming" | "done" | "empty";

interface Lens {
  key: string;
  title: string;
  text: string;
  sources: PrepSource[];
  status: LensStatus;
}

// Briefings finished this session, so opening a cited meeting and coming back
// doesn't re-run four model calls. Never persisted — prep is a computed view.
const briefings = new Map<number, Lens[]>();

/** The model cites passages as [n]; each becomes a chip naming its meeting. */
function renderCited(
  text: string,
  sources: PrepSource[],
  onOpenMeeting: (meetingId: number) => void,
): ReactNode[] {
  const pattern = /\[(\d+(?:\s*,\s*\d+)*)\]/g;
  const parts: ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    parts.push(text.slice(last, match.index));
    const cited = new Set<number>();
    for (const n of match[1].split(",")) {
      const source = sources[Number(n) - 1];
      if (!source || cited.has(source.meeting_id)) continue;
      cited.add(source.meeting_id);
      parts.push(
        <button
          key={`${match.index}-${n.trim()}`}
          className="prep__cite"
          title={source.text}
          onClick={() => onOpenMeeting(source.meeting_id)}
        >
          {source.meeting_title}
          {source.date ? ` · ${source.date}` : ""}
        </button>,
      );
    }
    if (cited.size === 0) parts.push(match[0]); // unknown index — keep the text
    last = match.index + match[0].length;
  }
  parts.push(text.slice(last));
  return parts;
}

function LensCard({
  lens,
  onOpenMeeting,
}: {
  lens: Lens;
  onOpenMeeting: (meetingId: number) => void;
}) {
  return (
    <article className="prep__lens">
      <h4 className="prep__lens-title">{lens.title}</h4>
      {lens.status === "empty" ? (
        <p className="prep__state">Nothing on record</p>
      ) : lens.status === "loading" ? (
        <p className="prep__state">
          <span className="transcript__pulse" /> Reading their meetings…
        </p>
      ) : (
        <p className="prep__text">
          {renderCited(lens.text, lens.sources, onOpenMeeting)}
        </p>
      )}
      {lens.sources.length > 0 && (
        <details className="chat__sources">
          <summary>
            {lens.sources.length} passage{lens.sources.length === 1 ? "" : "s"}
          </summary>
          <ul>
            {lens.sources.map((source, index) => (
              <li key={source.segment_id}>
                <span className="prep__source-meta">
                  [{index + 1}] {source.meeting_title}
                  {source.date ? ` · ${source.date}` : ""}
                </span>{" "}
                {source.text}
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}

export function PrepBriefing({
  personId,
  personName,
  meetingCount,
  onOpenMeeting,
}: {
  personId: number;
  personName: string;
  meetingCount: number;
  onOpenMeeting: (meetingId: number) => void;
}) {
  const [lenses, setLenses] = useState<Lens[] | null>(
    () => briefings.get(personId) ?? null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Leaving the page cancels an in-flight stream — no orphaned model calls.
  useEffect(() => () => abortRef.current?.abort(), []);

  const run = async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    // Mirror the stream into a local array so the finished briefing can be
    // cached without waiting on React state.
    let current: Lens[] = [];
    let failed = false;
    const commit = (next: Lens[]) => {
      current = next;
      setLenses(next);
    };
    const patch = (key: string, change: (lens: Lens) => Lens) =>
      commit(current.map((lens) => (lens.key === key ? change(lens) : lens)));

    setBusy(true);
    setError(null);
    commit([]);
    try {
      await streamPrep(
        personId,
        {
          onLens: (key, title) =>
            commit([
              ...current,
              { key, title, text: "", sources: [], status: "loading" },
            ]),
          onSources: (key, sources) => patch(key, (lens) => ({ ...lens, sources })),
          onToken: (key, text) =>
            patch(key, (lens) => ({
              ...lens,
              text: lens.text + text,
              status: "streaming",
            })),
          onLensEmpty: (key) => patch(key, (lens) => ({ ...lens, status: "empty" })),
          onLensDone: (key) => patch(key, (lens) => ({ ...lens, status: "done" })),
          onError: (message) => {
            failed = true;
            setError(message);
          },
        },
        controller.signal,
      );
      if (!failed) briefings.set(personId, current);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(
        err instanceof ApiError
          ? err.message
          : "The assistant didn't respond. Please try again.",
      );
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  };

  const started = lenses !== null && (lenses.length > 0 || busy);

  return (
    <section className="person__section">
      <div className="person__section-head">
        <h3 className="summary__heading">Prep</h3>
        {busy ? (
          <span className="prep__state">
            <span className="transcript__pulse" /> Preparing…
          </span>
        ) : (
          started && (
            <button className="prep__refresh" onClick={run}>
              Refresh
            </button>
          )
        )}
      </div>

      {!started ? (
        meetingCount === 0 ? (
          <p className="prep__intro">
            No meetings linked yet — there's nothing to prepare from.
          </p>
        ) : (
          <>
            <p className="prep__intro">
              Confab reads the {meetingCount} meeting
              {meetingCount === 1 ? "" : "s"} you've had with {personName} and
              briefs you on open commitments, recent decisions, open questions,
              and recurring context. Nothing is stored.
            </p>
            <button className="prep__run" onClick={run}>
              Prepare to meet
            </button>
          </>
        )
      ) : (
        <div className="prep__lenses">
          {(lenses ?? []).map((lens) => (
            <LensCard key={lens.key} lens={lens} onOpenMeeting={onOpenMeeting} />
          ))}
        </div>
      )}

      {error && <p className="prep__error">{error}</p>}
    </section>
  );
}
