import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

import { subscribeToasts, type Toast } from "./toast";
import { toastIn } from "./motion";

export function Toasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  useEffect(() => subscribeToasts(setToasts), []);

  return (
    <div className="toasts">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div
            className="toast"
            key={t.id}
            role="status"
            layout
            variants={toastIn}
            initial="initial"
            animate="animate"
            exit="exit"
          >
            {t.message}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
