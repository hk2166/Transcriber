/**
 * Shared motion vocabulary — Apple's fluid-interface values (WWDC "Designing
 * Fluid Interfaces"): critically-damped springs by default (no overshoot),
 * response ~0.3–0.4s. Bounce is reserved for momentum/press moments only.
 * `MotionConfig reducedMotion="user"` (set in App) turns all of this into
 * plain cross-fades when the viewer prefers reduced motion.
 */
import type { Transition, Variants } from "framer-motion";

export const spring: Transition = { type: "spring", bounce: 0, duration: 0.4 };
export const springFast: Transition = { type: "spring", bounce: 0, duration: 0.26 };

/** Full-view swap: search ↔ action items ↔ past meeting ↔ live recorder. */
export const viewSwap: Variants = {
  initial: { opacity: 0, y: 16, scale: 0.99 },
  animate: {
    opacity: 1,
    y: 0,
    scale: 1,
    transition: { type: "spring", bounce: 0, duration: 0.42 },
  },
  exit: { opacity: 0, y: -8, transition: { duration: 0.16 } },
};

/** A streaming transcript line — arrives from just below and settles. */
export const segmentIn: Variants = {
  initial: { opacity: 0, y: 14 },
  animate: {
    opacity: 1,
    y: 0,
    transition: { type: "spring", bounce: 0.15, duration: 0.4 },
  },
};

/** Modal sheet: materialize (scale + fade) from center, over a dimmed scrim. */
export const sheet: Variants = {
  initial: { opacity: 0, scale: 0.96 },
  animate: { opacity: 1, scale: 1, transition: spring },
  exit: { opacity: 0, scale: 0.97, transition: { duration: 0.15 } },
};

export const scrim: Variants = {
  initial: { opacity: 0 },
  animate: { opacity: 1, transition: { duration: 0.2 } },
  exit: { opacity: 0, transition: { duration: 0.15 } },
};

/** Contextual banner (model download, call detected): slides down into place. */
export const bannerIn: Variants = {
  initial: { opacity: 0, y: -10 },
  animate: { opacity: 1, y: 0, transition: spring },
  exit: { opacity: 0, y: -10, transition: springFast },
};

/** Toast: springs up from the bottom, exits back down. */
export const toastIn: Variants = {
  initial: { opacity: 0, y: 16, scale: 0.96 },
  animate: { opacity: 1, y: 0, scale: 1, transition: spring },
  exit: { opacity: 0, y: 10, scale: 0.97, transition: { duration: 0.15 } },
};
