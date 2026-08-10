import type { AudioSource } from "./api";

interface SourceSelectorProps {
  value: AudioSource;
  onChange: (source: AudioSource) => void;
  disabled: boolean;
}

const OPTIONS: { value: AudioSource; label: string }[] = [
  { value: "mic", label: "Mic" },
  { value: "system", label: "System" },
  { value: "both", label: "Both" },
];

export function SourceSelector({ value, onChange, disabled }: SourceSelectorProps) {
  return (
    <div className="source-selector" role="group" aria-label="Audio source">
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          className={"segment" + (opt.value === value ? " segment--active" : "")}
          onClick={() => onChange(opt.value)}
          disabled={disabled}
          aria-pressed={opt.value === value}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}