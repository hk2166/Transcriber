import { useEffect, useRef, useState } from "react";

import { downloadExport } from "./api";

const FORMATS = [
  { key: "markdown", label: "Markdown (.md)" },
  { key: "pdf", label: "PDF (.pdf)" },
  { key: "docx", label: "Word (.docx)" },
  { key: "json", label: "JSON (.json)" },
];

export function ExportMenu({
  meetingId,
  title,
}: {
  meetingId: number;
  title: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  // Close on outside click.
  useEffect(() => {
    if (!open) return;
    const onClick = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const pick = async (format: string) => {
    setOpen(false);
    try {
      await downloadExport(meetingId, format, title);
    } catch {
      // Surfacing export errors is a Day-14 hardening concern.
    }
  };

  return (
    <div className="export-menu" ref={ref}>
      <button className="export-menu__button" onClick={() => setOpen((o) => !o)}>
        Export ▾
      </button>
      {open && (
        <div className="export-menu__list">
          {FORMATS.map((format) => (
            <button key={format.key} onClick={() => pick(format.key)}>
              {format.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
