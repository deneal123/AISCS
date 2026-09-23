import React, { useEffect, useRef, useState } from "react";
import HeroOrbFallback from "./HeroOrbFallback";
import { getQualityTier, tierConfig } from "@/three/quality";
import { createSceneRunner } from "@/three/ThreeStage";
import { createHeroBlobScene } from "@/three/scenes/heroBlobScene";

/**
 * WebGL морф-блоб (lazy — грузится через React.lazy в HeroVisual только на
 * capable-устройствах). `three` импортируется динамически → отдельный async-чанк.
 * При сбое инициализации показываем CSS-фолбэк.
 */
export default function HeroOrb() {
  const canvasRef = useRef(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    let runner = null;
    let cancelled = false;
    const stateRef = { current: { intensity: 1 } };
    const tier = getQualityTier();
    const cfg = tierConfig(tier);

    import("three")
      .then((THREE) => {
        if (cancelled) return;
        runner = createSceneRunner(canvas, createHeroBlobScene(stateRef), {
          THREE,
          tier,
          dprCap: cfg.dprCap,
          pointer: cfg.parallax,
          scroll: true,
          clearAlpha: 0,
          antialias: tier === "full",
        });
        if (!runner) setFailed(true);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });

    return () => {
      cancelled = true;
      runner?.dispose();
    };
  }, []);

  if (failed) return <HeroOrbFallback />;
  return <canvas ref={canvasRef} aria-hidden style={{ width: "100%", height: "100%" }} />;
}
