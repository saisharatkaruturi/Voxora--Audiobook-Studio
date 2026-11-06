import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import "./open-book.css";

/**
 * A hardcover book built in CSS 3D: cloth covers with overhang, a spine, a page
 * block whose edges show the paper, endpapers, and a leaf that curls when it turns.
 *
 * It starts closed at a three-quarter angle (cover, spine and page edges all in
 * view), then opens: the cover swings over on its hinge, the book settles flat,
 * and the pages are real text. Changing `spread` turns a page: the leaf lifts from
 * the right, bends across three strips as it travels, and lands on the left.
 */

export interface Spread {
  key: string;
  left: ReactNode;
  right: ReactNode;
}

interface Props {
  spread: Spread;
  title: string;
  author: string;
  /** Delay before the book opens, ms (it opens immediately with reduced motion). */
  openDelay?: number;
  /** Leaf through these spreads on their own, one after another, while true. */
  riffle?: Spread[] | null;
  /** 0..1: how strongly the pages glow (light pours from the binding). */
  glow?: number;
  className?: string;
}

const STRIPS = 3;
const TURN_MS = 1150;
const RIFFLE_TURN_MS = 950;
const RIFFLE_PAUSE_MS = 650;
/** Linger on the first spread (the title page) after the cover opens. */
const FIRST_PAUSE_MS = 1900;

function easeInOut(t: number) {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
}

export function OpenBook({ spread, title, author, openDelay = 1300, riffle = null, glow = 0.6, className }: Props) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const [pw, setPw] = useState(300); // one page's width in px
  const [open, setOpen] = useState(false);
  const [shown, setShown] = useState<Spread>(spread);
  const [turning, setTurning] = useState<{ from: Spread; to: Spread; ms: number } | null>(null);
  const [riffleIdx, setRiffleIdx] = useState(0);
  const [resting, setResting] = useState(false); // the pause between two riffled pages
  const stripRefs = useRef<(HTMLDivElement | null)[]>([]);
  const tilt = useRef({ x: 0, y: 0 });
  const bookRef = useRef<HTMLDivElement | null>(null);
  const reduce = typeof window !== "undefined" && (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);

  // Size the book to its stage: two pages plus the cover overhang must fit.
  useLayoutEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const fit = () => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      setPw(Math.max(140, Math.min(340, (w - 40) / 2.12, (h - 40) / 1.58)));
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Open once, shortly after appearing.
  useEffect(() => {
    if (reduce) {
      setOpen(true);
      return;
    }
    const t = setTimeout(() => setOpen(true), openDelay);
    return () => clearTimeout(t);
  }, [openDelay, reduce]);

  // Where the book is heading: the next page of the story while riffling, else the chosen spread.
  // Decided before the cover opens, so the first spread is already in place under it.
  const riffling = !!riffle?.length && !reduce;
  const target = riffling ? riffle![riffleIdx % riffle!.length] : spread;

  // Turn toward the target whenever it differs from what is shown (one turn at a time).
  useEffect(() => {
    if (turning || resting || target.key === shown.key) return;
    if (!open || reduce) {
      setShown(target);
      return;
    }
    setTurning({ from: target.key === spread.key ? shown : shown, to: target, ms: riffling ? RIFFLE_TURN_MS : TURN_MS });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target.key, shown.key, turning, resting, open]);

  // While riffling: after each page lands, rest a moment, then move on to the next.
  useEffect(() => {
    if (!riffling || !open || turning || shown.key !== target.key) return;
    setResting(true);
    const t = setTimeout(() => {
      setResting(false);
      setRiffleIdx((i) => i + 1);
    }, riffleIdx % (riffle?.length || 1) === 0 ? FIRST_PAUSE_MS + 900 : RIFFLE_PAUSE_MS);
    return () => {
      clearTimeout(t);
      setResting(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [riffling, open, turning, shown.key]);

  // Drive the turn frame by frame: the leaf rotates about the spine while its strips bend.
  useEffect(() => {
    if (!turning) return;
    let raf = 0;
    const t0 = performance.now();
    const step = (now: number) => {
      const p = Math.min(1, (now - t0) / turning.ms);
      const e = easeInOut(p);
      const lift = -180 * e;
      const bend = Math.sin(Math.PI * p) * 34; // most curl mid-turn, flat at both ends
      stripRefs.current.forEach((s, i) => {
        if (!s) return;
        const angle = i === 0 ? lift : bend * (i === 1 ? 0.45 : 0.75);
        s.style.transform = `rotateY(${angle}deg)`;
        // Light falls off as the paper faces away: a flat shade, no gradients.
        const facing = Math.abs(Math.cos(((lift + (i ? bend * i * 0.5 : 0)) * Math.PI) / 180));
        s.style.setProperty("--shade", String((1 - facing) * 0.28));
      });
      if (p < 1) raf = requestAnimationFrame(step);
      else {
        setShown(turning.to);
        setTurning(null);
      }
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [turning]);

  // A slight tilt toward the pointer, eased so it never jitters.
  useEffect(() => {
    if (reduce) return;
    let raf = 0;
    const cur = { x: 0, y: 0 };
    const onMove = (e: PointerEvent) => {
      tilt.current = { x: (e.clientY / window.innerHeight - 0.5) * -5, y: (e.clientX / window.innerWidth - 0.5) * 7 };
    };
    const loop = () => {
      cur.x += (tilt.current.x - cur.x) * 0.06;
      cur.y += (tilt.current.y - cur.y) * 0.06;
      bookRef.current?.style.setProperty("--tx", `${cur.x.toFixed(2)}deg`);
      bookRef.current?.style.setProperty("--ty", `${cur.y.toFixed(2)}deg`);
      raf = requestAnimationFrame(loop);
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    raf = requestAnimationFrame(loop);
    return () => {
      window.removeEventListener("pointermove", onMove);
      cancelAnimationFrame(raf);
    };
  }, [reduce]);

  // Same spread with new content (the lit sentence moved): show it live, no turn.
  const base = target.key === shown.key ? target : shown;
  // While turning: the static right page already shows the next right page underneath,
  // the static left page keeps the old left page until the leaf covers it.
  const leftStatic = turning ? turning.from.left : base.left;
  const rightStatic = turning ? turning.to.right : base.right;

  const style = { "--pw": `${pw}px`, "--ph": `${pw * 1.5}px`, "--fs": `${pw * 0.0435}px`, "--glow": glow } as CSSProperties;

  return (
    <div ref={stageRef} className={["ob-stage", className].filter(Boolean).join(" ")} style={style} data-ui>
      <div ref={bookRef} className="ob-book" data-open={open ? "" : undefined} role="figure" aria-label={`${title} by ${author}`}>
        <div className="ob-pose">
        <div className="ob-shadow" />
        {/* Light from the book: an aura behind it and a beam rising out of the binding */}
        <div className="ob-aura" aria-hidden />
        {/* Back cover and the block of pages, fixed on the right of the spine */}
        <div className="ob-back" />
        <div className="ob-block">
          <div className="ob-edge ob-edge-fore" />
          <div className="ob-edge ob-edge-head" />
          <div className="ob-edge ob-edge-tail" />
          <div className="ob-page ob-page-right">{rightStatic}</div>
        </div>

        {/* The left page, revealed once the cover and first leaf have swung over */}
        <div className="ob-page ob-page-left">{leftStatic}</div>

        {/* Front cover: cloth outside, endpaper inside, hinged at the spine */}
        <div className="ob-cover">
          <div className="ob-face ob-cover-out">
            <div className="ob-cover-title">{title}</div>
            <div className="ob-cover-rule" />
            <div className="ob-cover-author">{author}</div>
          </div>
          <div className="ob-face ob-cover-in" />
        </div>
        <div className="ob-spine">
          <span>{title}</span>
        </div>

        <div className="ob-beam" aria-hidden />
        <div className="ob-sparks" aria-hidden>
          {SPARKS.map((k, i) => (
            <span key={i} style={{ "--d": `${k.d}s`, "--x": k.x, "--s": k.s, "--dur": `${k.dur}s` } as CSSProperties} />
          ))}
        </div>
        {/* The turning leaf, cut into strips that bend progressively */}
        {turning && (
          <div className="ob-leaf">
            <Strip index={0} refs={stripRefs} front={turning.from.right} back={turning.to.left} />
          </div>
        )}
        </div>
      </div>
    </div>
  );
}

// Sparks rising from the binding: fixed so they don't reshuffle on every render.
const SPARKS = Array.from({ length: 22 }, (_, i) => {
  const r = (n: number) => ((Math.sin(i * 12.9898 + n * 78.233) * 43758.5453) % 1 + 1) % 1;
  return { d: r(1) * 4, x: (r(2) - 0.5) * 2, s: 0.5 + r(3) * 1.1, dur: 2.6 + r(4) * 2.4 };
});

function Strip({ index, refs, front, back }: { index: number; refs: React.MutableRefObject<(HTMLDivElement | null)[]>; front: ReactNode; back: ReactNode }) {
  return (
    <div
      ref={(el) => {
        refs.current[index] = el;
      }}
      className="ob-strip"
      style={{ "--i": index } as CSSProperties}
    >
      <div className="ob-face ob-strip-front">
        <div className="ob-page-clip" style={{ "--i": index } as CSSProperties}>
          <div className="ob-page-inner">{front}</div>
        </div>
      </div>
      <div className="ob-face ob-strip-back">
        <div className="ob-page-clip ob-page-clip-back" style={{ "--i": index } as CSSProperties}>
          <div className="ob-page-inner">{back}</div>
        </div>
      </div>
      {index < STRIPS - 1 && <Strip index={index + 1} refs={refs} front={front} back={back} />}
    </div>
  );
}
