import type { MeetingSummary } from "./api";

interface SummaryPanelProps {
  summary: MeetingSummary | null;
  processing: boolean;
}

export function SummaryPanel({ summary, processing }: SummaryPanelProps) {
  if (processing) {
    return (
      <div className="summary summary--pending">
        <span className="transcript__pulse" />
        Finding speakers and summarising…
      </div>
    );
  }

  if (!summary) return null;

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
    </div>
  );
}
