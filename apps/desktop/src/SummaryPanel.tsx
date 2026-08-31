import { useState } from "react";

import { getMeetingSummary, triggerSummary, type MeetingSummary } from "./api";
import { toast } from "./toast";

interface SummaryPanelProps {
  meetingId: number;
  summary: MeetingSummary | null;
  processing: boolean;
  onSummaryUpdated: (summary: MeetingSummary) => void;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export function SummaryPanel({
  meetingId,
  summary,
  processing,
  onSummaryUpdated,
}: SummaryPanelProps) {
  const [generating, setGenerating] = useState(false);

  // Trigger a summary and poll until a new one lands. Covers both the
  // never-summarised case (e.g. Ollama wasn't running) and an explicit redo.
  const generate = async () => {
    setGenerating(true);
    const before = summary?.summary ?? null;
    try {
      await triggerSummary(meetingId);
      const deadline = Date.now() + 60_000;
      for (;;) {
        await sleep(1500);
        const next = await getMeetingSummary(meetingId);
        if (next && next.summary !== before) {
          onSummaryUpdated(next);
          return;
        }
        if (Date.now() > deadline) {
          toast(
            "Couldn't generate a summary. Make sure Ollama is running with a model pulled, or add a cloud API key in Settings.",
          );
          return;
        }
      }
    } catch {
      toast("Couldn't start summary generation.");
    } finally {
      setGenerating(false);
    }
  };

  if (processing) {
    return (
      <div className="summary summary--pending">
        <span className="transcript__pulse" />
        Refining transcript, finding speakers, and summarising…
      </div>
    );
  }

  if (!summary) {
    if (generating) {
      return (
        <div className="summary summary--pending">
          <span className="transcript__pulse" />
          Generating summary…
        </div>
      );
    }
    return (
      <div className="summary summary--empty">
        <p className="summary__empty-title">No summary yet</p>
        <p className="summary__empty-hint">
          Summaries run on a local LLM. Make sure <strong>Ollama</strong> is
          running with a model pulled — or pick a cloud provider and add an API
          key — under Settings. Then generate one:
        </p>
        <button className="summary__generate" onClick={generate}>
          Generate summary
        </button>
      </div>
    );
  }

  const lists: { title: string; items: string[]; checks?: boolean }[] = [
    { title: "Key points", items: summary.key_points },
    { title: "Action items", items: summary.action_items, checks: true },
    { title: "Decisions", items: summary.decisions },
    { title: "Open questions", items: summary.open_questions },
  ];

  return (
    <div className="summary">
      <p className="summary__overview">{summary.summary}</p>
      {lists
        .filter((section) => section.items.length > 0)
        .map((section) => (
          <div className="summary__section" key={section.title}>
            <h3 className="summary__heading">{section.title}</h3>
            <ul
              className={
                "summary__list" + (section.checks ? " summary__list--checks" : "")
              }
            >
              {section.items.map((item, index) => (
                <li key={index}>
                  {section.checks ? (
                    <label className="summary__check">
                      <input type="checkbox" />
                      <span>{item}</span>
                    </label>
                  ) : (
                    item
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      <button
        className="summary__regen"
        onClick={generate}
        disabled={generating}
      >
        {generating ? "Regenerating…" : "Regenerate summary"}
      </button>
    </div>
  );
}
