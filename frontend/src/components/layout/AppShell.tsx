import { Suspense, useEffect, useRef } from "react";
import { useLocation, useOutlet } from "react-router-dom";
import { AnimatePresence, motion, useIsPresent, useReducedMotion } from "framer-motion";
import { MiniPlayer } from "@/components/player/MiniPlayer";
import { MobileTabs, Navbar } from "@/components/navigation/Navbar";
import { PageLoader } from "@/components/ui/Feedback";
import { pageTransition } from "@/config/motion";
import { usePlayerShortcuts } from "@/features/player/usePlayerShortcuts";
import { useDeviceSync } from "@/hooks/useDeviceSync";
import { usePlayer } from "@/stores/player";
import { cn } from "@/utils/format";

/** Top-level section of a path, so tab changes inside a book don't replay the page transition. */
function sectionKey(pathname: string): string {
  const parts = pathname.split("/").filter(Boolean);
  if (parts[0] === "books" && parts[2] === "listen") return `listen:${parts[1]}`;
  return parts[0] === "books" ? `books:${parts[1]}` : parts[0] ?? "";
}

/**
 * While a page animates out, <Outlet> would already render the *next* route inside
 * the exiting wrapper (mounting it twice). Freeze the exiting page's element instead.
 */
function PresenceOutlet() {
  const outlet = useOutlet();
  const isPresent = useIsPresent();
  const frozen = useRef(outlet);
  if (isPresent) frozen.current = outlet;
  return frozen.current;
}

export function AppShell() {
  const { pathname } = useLocation();
  const hasPlayer = usePlayer((s) => !!s.playback);
  const reduce = useReducedMotion();
  usePlayerShortcuts();
  useDeviceSync();

  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [pathname]);

  return (
    <div className="min-h-dvh">
      <a href="#main" className="sr-only z-[200] rounded-lg bg-paper-100 px-3 py-2 text-ink-950 focus:not-sr-only focus:fixed focus:top-3 focus:left-3">
        Skip to content
      </a>
      <Navbar />
      <main id="main" className={cn("mx-auto max-w-[1320px] px-4 pt-24 sm:px-6 md:px-10 md:pt-28", hasPlayer ? "pb-44 md:pb-32" : "pb-28 md:pb-16")}>
        <AnimatePresence mode="wait" initial={false}>
          <motion.div key={sectionKey(pathname)} variants={reduce ? undefined : pageTransition} initial="initial" animate="animate" exit="exit">
            <Suspense fallback={<PageLoader />}>
              <PresenceOutlet />
            </Suspense>
          </motion.div>
        </AnimatePresence>
      </main>
      <MiniPlayer />
      <MobileTabs />
    </div>
  );
}
