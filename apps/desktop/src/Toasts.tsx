import { useEffect, useState } from "react";

import { subscribeToasts, type Toast } from "./toast";

export function Toasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  useEffect(() => subscribeToasts(setToasts), []);

  if (toasts.length === 0) return null;

  return (
    <div className="toasts">
      {toasts.map((t) => (
        <div className="toast" key={t.id} role="status">
          {t.message}
        </div>
      ))}
    </div>
  );
}
