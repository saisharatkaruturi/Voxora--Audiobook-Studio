import { useEffect, useRef } from "react";

/**
 * The night sky behind VOXORA: a deep midnight gradient, slow nebula clouds, a
 * band of Milky Way, three depths of twinkling stars that shift with the pointer
 * and the scroll, and shooting stars. It brightens with the narrator's voice
 * (`setSkyLevel`). One canvas, ~30 fps, paused when hidden, still under reduced motion.
 */

let targetLevel = 0;
export function setSkyLevel(v: number) {
  targetLevel = Math.max(0, Math.min(1, v));
}

interface Star {
  x: number;
  y: number;
  r: number;
  depth: number;
  phase: number;
  speed: number;
  tint: string;
}
interface Shot {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  max: number;
  len: number;
}

const TINTS = ["255,255,255", "243,239,250", "226,214,255", "238,200,255"];

export function GalaxySky({ className }: { className?: string }) {
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

    let w = 0;
    let h = 0;
    let stars: Star[] = [];
    let nebula: HTMLCanvasElement | null = null;
    let light = false;
    let level = 0;
    let raf = 0;
    let last = 0;
    let running = true;
    const shots: Shot[] = [];
    let nextShot = performance.now() + 900;
    const pointer = { x: 0, y: 0, tx: 0, ty: 0 };

    const readTheme = () => {
      light = document.documentElement.dataset.theme === "light";
    };

    // Nebula painted once at low resolution, then drifted and scaled each frame.
    const paintNebula = () => {
      const n = document.createElement("canvas");
      n.width = 480;
      n.height = 300;
      const c = n.getContext("2d")!;
      const blobs = light
        ? [
            [0.25, 0.3, 0.45, "110,60,180", 0.08],
            [0.75, 0.55, 0.5, "196,92,255", 0.1],
            [0.55, 0.85, 0.4, "120,90,220", 0.06],
          ]
        : [
            [0.22, 0.28, 0.5, "90,40,170", 0.45],
            [0.72, 0.42, 0.42, "196,92,255", 0.18],
            [0.58, 0.78, 0.55, "80,50,190", 0.3],
            [0.12, 0.8, 0.35, "200,60,170", 0.22],
            [0.88, 0.15, 0.3, "170,130,255", 0.18],
          ];
      for (const [x, y, r, rgb, a] of blobs as [number, number, number, string, number][]) {
        const g = c.createRadialGradient(x * n.width, y * n.height, 0, x * n.width, y * n.height, r * n.width);
        g.addColorStop(0, `rgba(${rgb},${a})`);
        g.addColorStop(0.5, `rgba(${rgb},${a * 0.35})`);
        g.addColorStop(1, `rgba(${rgb},0)`);
        c.fillStyle = g;
        c.fillRect(0, 0, n.width, n.height);
      }
      nebula = n;
    };

    const build = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.75);
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const count = Math.round(Math.min(900, (w * h) / 2200));
      stars = [];
      for (let i = 0; i < count; i++) {
        const depth = Math.random() ** 2;
        stars.push({
          x: Math.random(),
          y: Math.random(),
          r: 0.35 + depth * 1.35 + (Math.random() < 0.025 ? 1 : 0),
          depth,
          phase: Math.random() * Math.PI * 2,
          speed: 0.5 + Math.random() * 1.8,
          tint: TINTS[Math.floor(Math.random() * TINTS.length)],
        });
      }
      // The Milky Way: a dense diagonal band of faint dust stars.
      for (let i = 0; i < count * 0.9; i++) {
        const t = Math.random();
        const spread = (Math.random() + Math.random() + Math.random() - 1.5) * 0.11;
        stars.push({
          x: t,
          y: 0.95 - t * 0.8 + spread,
          r: 0.25 + Math.random() * 0.45,
          depth: 0.05,
          phase: Math.random() * Math.PI * 2,
          speed: 0.3 + Math.random(),
          tint: TINTS[Math.floor(Math.random() * 3)],
        });
      }
      paintNebula();
    };

    const spawnShot = () => {
      const fromLeft = Math.random() < 0.5;
      const speed = 9 + Math.random() * 7;
      const ang = (fromLeft ? 1 : -1) * (0.35 + Math.random() * 0.35);
      shots.push({
        x: fromLeft ? Math.random() * w * 0.6 : w * 0.4 + Math.random() * w * 0.6,
        y: Math.random() * h * 0.45,
        vx: Math.cos(ang) * speed * (fromLeft ? 1 : 1),
        vy: Math.abs(Math.sin(ang)) * speed,
        life: 0,
        max: 55 + Math.random() * 35,
        len: 120 + Math.random() * 140,
      });
    };

    const draw = (now: number) => {
      const t = now / 1000;
      level += (targetLevel - level) * 0.1;
      pointer.x += (pointer.tx - pointer.x) * 0.05;
      pointer.y += (pointer.ty - pointer.y) * 0.05;
      const scroll = window.scrollY;
      ctx.clearRect(0, 0, w, h);

      // Nebula, drifting and breathing with the voice
      if (nebula) {
        ctx.save();
        ctx.globalAlpha = 0.85 + level * 0.5;
        ctx.globalCompositeOperation = light ? "multiply" : "screen";
        const dx = Math.sin(t * 0.03) * w * 0.04 - pointer.x * 12;
        const dy = Math.cos(t * 0.025) * h * 0.04 - pointer.y * 10 - scroll * 0.03;
        ctx.drawImage(nebula, -w * 0.08 + dx, -h * 0.08 + dy, w * 1.16, h * 1.16);
        ctx.restore();
      }

      // Stars
      for (const s of stars) {
        const tw = reduce ? 0.8 : 0.55 + 0.45 * Math.sin(t * s.speed + s.phase);
        const px = s.x * w - pointer.x * 18 * s.depth;
        let py = s.y * h - pointer.y * 14 * s.depth - scroll * (0.02 + s.depth * 0.08);
        py = ((py % h) + h) % h;
        const a = Math.min(1, tw * (0.35 + s.depth * 0.75) * (1 + level * 0.9));
        const col = light ? `rgba(40,20,80,${a * 0.5})` : `rgba(${s.tint},${a})`;
        ctx.fillStyle = col;
        if (s.r > 1.4 && !light) {
          // bright stars get a soft halo and a faint cross glint
          ctx.globalAlpha = a * 0.25;
          ctx.beginPath();
          ctx.arc(px, py, s.r * 3.2, 0, Math.PI * 2);
          ctx.fill();
          ctx.globalAlpha = a * 0.35;
          ctx.fillRect(px - s.r * 4, py - 0.4, s.r * 8, 0.8);
          ctx.fillRect(px - 0.4, py - s.r * 4, 0.8, s.r * 8);
          ctx.globalAlpha = 1;
        }
        ctx.beginPath();
        ctx.arc(px, py, s.r, 0, Math.PI * 2);
        ctx.fill();
      }

      // Shooting stars
      if (!reduce && now > nextShot) {
        spawnShot();
        if (Math.random() < 0.25) spawnShot();
        nextShot = now + (1400 + Math.random() * 2600) * (1 - level * 0.5);
      }
      for (let i = shots.length - 1; i >= 0; i--) {
        const s = shots[i];
        s.life++;
        s.x += s.vx;
        s.y += s.vy;
        const fade = Math.sin((s.life / s.max) * Math.PI);
        const mag = Math.hypot(s.vx, s.vy);
        const tx = s.x - (s.vx / mag) * s.len;
        const ty = s.y - (s.vy / mag) * s.len;
        const g = ctx.createLinearGradient(s.x, s.y, tx, ty);
        const head = light ? "40,20,80" : "248,235,255";
        const tail = light ? "40,20,80" : "196,92,255";
        g.addColorStop(0, `rgba(${head},${0.95 * fade})`);
        g.addColorStop(0.25, `rgba(${tail},${0.5 * fade})`);
        g.addColorStop(1, `rgba(${tail},0)`);
        ctx.strokeStyle = g;
        ctx.lineWidth = 2;
        ctx.lineCap = "round";
        ctx.beginPath();
        ctx.moveTo(s.x, s.y);
        ctx.lineTo(tx, ty);
        ctx.stroke();
        ctx.fillStyle = `rgba(${head},${fade})`;
        ctx.beginPath();
        ctx.arc(s.x, s.y, 1.8, 0, Math.PI * 2);
        ctx.fill();
        if (s.life > s.max || s.x < -300 || s.x > w + 300 || s.y > h + 300) shots.splice(i, 1);
      }
    };

    const loop = (now: number) => {
      if (!running) return;
      raf = requestAnimationFrame(loop);
      if (now - last < 30) return;
      last = now;
      draw(now);
    };

    readTheme();
    build();
    if (reduce) draw(performance.now());
    else raf = requestAnimationFrame(loop);

    const onMove = (e: PointerEvent) => {
      pointer.tx = e.clientX / window.innerWidth - 0.5;
      pointer.ty = e.clientY / window.innerHeight - 0.5;
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    const ro = new ResizeObserver(() => {
      build();
      if (reduce) draw(performance.now());
    });
    ro.observe(canvas);
    const mo = new MutationObserver(() => {
      readTheme();
      paintNebula();
      if (reduce) draw(performance.now());
    });
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const onVisible = () => {
      if (reduce) return;
      if (document.hidden) {
        running = false;
        cancelAnimationFrame(raf);
      } else if (!running) {
        running = true;
        raf = requestAnimationFrame(loop);
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      running = false;
      cancelAnimationFrame(raf);
      ro.disconnect();
      mo.disconnect();
      window.removeEventListener("pointermove", onMove);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  return <canvas ref={ref} className={className} aria-hidden />;
}
