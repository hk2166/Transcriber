interface VolumeMeterProps {
  level: number; // 0..1
}

export function VolumeMeter({ level }: VolumeMeterProps) {
  const clamped = Math.max(0, Math.min(1, level));
  return (
    <div className="meter" aria-hidden>
      <div className="meter__fill" style={{ transform: `scaleX(${clamped})` }} />
    </div>
  );
}