import * as THREE from "three";
import { brand } from "@/config/brand";

/** Horizontal orchid → mint gradient used for emissive accents (spine, edge line). */
export function brandGradientTexture(): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = 256;
  c.height = 4;
  const ctx = c.getContext("2d")!;
  const g = ctx.createLinearGradient(0, 0, 256, 0);
  g.addColorStop(0, brand.colors.orchid);
  g.addColorStop(0.55, "#245E86");
  g.addColorStop(1, brand.colors.mint);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 256, 4);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/** Soft radial sprite for the light that emerges from the spine. */
export function glowTexture(): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const ctx = c.getContext("2d")!;
  const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.25, "rgba(222,190,255,0.55)");
  g.addColorStop(0.6, "rgba(196,92,255,0.15)");
  g.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 128, 128);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/** Fine horizontal lines for the page-block edge (reads as stacked paper). */
export function pageEdgeTexture(): THREE.CanvasTexture {
  const c = document.createElement("canvas");
  c.width = 8;
  c.height = 128;
  const ctx = c.getContext("2d")!;
  ctx.fillStyle = "#efe6d6";
  ctx.fillRect(0, 0, 8, 128);
  for (let y = 0; y < 128; y += 2) {
    ctx.fillStyle = `rgba(120,100,80,${0.08 + (y % 6 === 0 ? 0.08 : 0)})`;
    ctx.fillRect(0, y, 8, 1);
  }
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}
