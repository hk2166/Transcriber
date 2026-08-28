import { motion } from "framer-motion";

interface RecordButtonProps {
  recording: boolean;
  busy: boolean;
  onClick: () => void;
}

export function RecordButton({ recording, busy, onClick }: RecordButtonProps) {
  return (
    <motion.button
      className={"record-button" + (recording ? " record-button--recording" : "")}
      onClick={onClick}
      disabled={busy}
      aria-label={recording ? "Stop recording" : "Start recording"}
      aria-pressed={recording}
      // Tactile press: respond on pointer-down, spring back on release.
      whileTap={{ scale: 0.92 }}
      transition={{ type: "spring", bounce: 0, duration: 0.3 }}
    >
      <span className="record-button__icon" />
    </motion.button>
  );
}
