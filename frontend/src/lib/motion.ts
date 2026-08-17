import type { Variants } from "framer-motion";

/** Shared, restrained motion vocabulary. Framer-motion also honours
 *  prefers-reduced-motion via MotionConfig in App.tsx. */

export const spring = { type: "spring", stiffness: 420, damping: 34 } as const;

export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: spring },
  exit: { opacity: 0, y: -6, transition: { duration: 0.15 } },
};

/** Stagger container for lists that mutate. */
export const listContainer: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.04 } },
};

export const listItem: Variants = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: spring },
  exit: { opacity: 0, x: -12, transition: { duration: 0.16 } },
};

export const routeFade: Variants = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.28, ease: [0.22, 1, 0.36, 1] } },
  exit: { opacity: 0, y: -8, transition: { duration: 0.16 } },
};
