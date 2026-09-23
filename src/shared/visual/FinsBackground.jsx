import React, { Suspense, useState } from "react";
import { Box } from "@chakra-ui/react";
import { getQualityTier } from "@/three/quality";

// three грузится только на full-tier (lazy → async-чанк). На reduced/off — CSS-фолбэк.
const FinsCanvas = React.lazy(() => import("./FinsCanvas"));

/**
 * Фон-«рёбра» InCellCorp на ВСЮ страницу (fixed, за контентом, не скроллится).
 * tier==='full' → WebGL fullscreen; иначе — лёгкий CSS-фолбэк.
 * Shared visual-примитив: используется PublicLayout (лендинг) и AuthLayout.
 */
export default function FinsBackground() {
  const [tier] = useState(getQualityTier);
  const [failed, setFailed] = useState(false);
  const useWebgl = tier === "full" && !failed;

  return (
    <Box
      position="fixed"
      inset={0}
      zIndex={0}
      overflow="hidden"
      pointerEvents="none"
      aria-hidden
    >
      {useWebgl ? (
        <Suspense fallback={<div className="fins-fallback" />}>
          <FinsCanvas onFail={() => setFailed(true)} />
        </Suspense>
      ) : (
        <div className="fins-fallback" />
      )}
    </Box>
  );
}
