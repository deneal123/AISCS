import React, { useEffect, useRef } from "react";
import { getQualityTier, tierConfig } from "@/three/quality";
import { createSceneRunner } from "@/three/ThreeStage";
import { createFinsScene } from "@/three/scenes/finsScene";

/**
 * WebGL «рёбра» на всю страницу (lazy, fullscreen). `three` уже в async-чанке.
 * Прозрачный canvas с аддитивным свечением над тёмной страницей; рендерер сам
 * подгоняется под окно (fullscreen:true), пауза на скрытой вкладке.
 * Shared visual-примитив: фон-«рёбра» для лендинга и авторизации.
 */
export default function FinsCanvas({ onFail }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    let runner = null;
    let cancelled = false;
    const tier = getQualityTier();
    const cfg = tierConfig(tier);

    import("three")
      .then((THREE) => {
        if (cancelled) return;
        runner = createSceneRunner(canvas, createFinsScene(), {
          THREE,
          tier,
          dprCap: Math.min(cfg.dprCap, 1.6),
          pointer: cfg.parallax,
          scroll: false,
          clearAlpha: 0,
          antialias: false,
          fullscreen: true,
        });
        if (!runner) onFail?.();
      })
      .catch(() => {
        if (!cancelled) onFail?.();
      });

    return () => {
      cancelled = true;
      runner?.dispose();
    };
  }, [onFail]);

  return <canvas ref={canvasRef} aria-hidden style={{ width: "100%", height: "100%", display: "block" }} />;
}
