interface RecordButtonProps {
  recording: boolean;
  busy: boolean;
  onClick: () => void;
}

export function RecordButton({ recording, busy, onClick }: RecordButtonProps) {
  return (
    <button
      className={"record-button" + (recording ? " record-button--recording" : "")}
      onClick={onClick}
      disabled={busy}
      aria-label={recording ? "Stop recording" : "Start recording"}
      aria-pressed={recording}
    >
      <span className="record-button__icon" />
    </button>
  );
}
