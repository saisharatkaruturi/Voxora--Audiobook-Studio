import { GalaxySky } from "@/components/layout/GalaxySky";

/**
 * Behind every page: a midnight sky (deep at the top, lifting toward the horizon)
 * with the galaxy drawn over it: nebula, Milky Way, twinkling and shooting stars.
 */
export function Ambient() {
  return (
    <div className="pointer-events-none fixed inset-0 -z-10 [background:var(--sky)] transition-[background] duration-500" aria-hidden>
      <GalaxySky className="absolute inset-0 size-full" />
    </div>
  );
}
