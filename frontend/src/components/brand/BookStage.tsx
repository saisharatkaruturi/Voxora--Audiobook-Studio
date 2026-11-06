import { Component, lazy, Suspense, useMemo, type ReactNode } from "react";
import { VoxoraBook } from "@/components/brand/VoxoraBook";
import type { HeroSceneProps } from "@/components/3d/HeroScene";
import { cn } from "@/utils/format";

const HeroScene = lazy(() => import("@/components/3d/HeroScene"));

function hasWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

class SceneBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/**
 * The VOXORA Book in 3D (three.js, lazy-loaded). Falls back to the CSS book when
 * WebGL is unavailable or while the 3D bundle loads, so layout never jumps.
 */
export function BookStage({ className, fallbackSize = 240, ...props }: HeroSceneProps & { fallbackSize?: number }) {
  const webgl = useMemo(hasWebGL, []);
  const fallback = (
    <div className={cn("flex items-center justify-center", className)}>
      <VoxoraBook size={fallbackSize} flowing={props.mode === "flowing"} />
    </div>
  );
  if (!webgl) return fallback;
  return (
    <SceneBoundary fallback={fallback}>
      <Suspense fallback={fallback}>
        <HeroScene className={className} {...props} />
      </Suspense>
    </SceneBoundary>
  );
}
