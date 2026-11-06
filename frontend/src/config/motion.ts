import type { Transition, Variants } from "framer-motion";

/** Shared motion language: calm, quick, never bouncy. */
export const ease = {
  out: [0.22, 1, 0.36, 1] as const,
  inOut: [0.65, 0, 0.35, 1] as const,
};

export const duration = { fast: 0.2, base: 0.45, slow: 0.8 };

export const spring: Transition = { type: "spring", stiffness: 260, damping: 30, mass: 0.9 };

export const pageTransition: Variants = {
  initial: { opacity: 0, y: 10, filter: "blur(6px)" },
  // transitionEnd clears transform/filter: either would make the page a containing block for position:fixed children.
  animate: { opacity: 1, y: 0, filter: "blur(0px)", transition: { duration: duration.base, ease: ease.out }, transitionEnd: { filter: "none", transform: "none" } },
  exit: { opacity: 0, y: -6, filter: "blur(4px)", transition: { duration: 0.22, ease: ease.inOut } },
};

/** Sections reveal as they scroll into view. */
export const reveal: Variants = {
  hidden: { opacity: 0, y: 24 },
  show: { opacity: 1, y: 0, transition: { duration: duration.slow, ease: ease.out } },
};

export const stagger = (step = 0.06): Variants => ({
  hidden: {},
  show: { transition: { staggerChildren: step } },
});

export const cardHover = { y: -4, transition: { duration: duration.fast, ease: ease.out } };
