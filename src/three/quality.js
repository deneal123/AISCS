import { isCoarsePointer, isFigmaCaptureMode, prefersReducedMotion } from "@utils/motion";
import { localPrefGet, localPrefSet } from "@utils/localPrefs";

/**
 * Quality-gate для WebGL. Порт docs/design_transfer/09 (quality.ts) в JS.
 * Тиры: full | reduced | off. off — reduced-motion / capture / нет WebGL
 * (→ CSS-фолбэк, three НЕ грузится). reduced — слабые устройства. full — иначе.
 * `?fx=full|reduced|off` — override (липкий через localStorage).
 */

const FX_PREF_KEY = "fx-tier";

function isTier(v) {
  return v === "full" || v === "reduced" || v === "off";
}

let cachedWebGL = null;
function webglSupported() {
  if (cachedWebGL !== null) return cachedWebGL;
  if (typeof window === "undefined") {
    cachedWebGL = false;
    return cachedWebGL;
  }
  try {
    const c = document.createElement("canvas");
    cachedWebGL = !!(
      window.WebGLRenderingContext &&
      (c.getContext("webgl") || c.getContext("experimental-webgl"))
    );
  } catch {
    cachedWebGL = false;
  }
  return cachedWebGL;
}

function forcedTier() {
  if (typeof window === "undefined") return null;
  const m = /[?&#]fx=(full|reduced|off)\b/.exec(window.location.search + window.location.hash);
  return m ? m[1] : null;
}

export function getQualityTier() {
  if (typeof window === "undefined") return "off";
  const forced = forcedTier();
  if (forced) {
    const t = webglSupported() ? forced : "off";
    localPrefSet(FX_PREF_KEY, t);
    return t;
  }
  if (isFigmaCaptureMode() || prefersReducedMotion()) return "off";
  if (!webglSupported()) return "off";
  const stored = localPrefGet(FX_PREF_KEY, null);
  if (isTier(stored)) return stored;
  const nav = navigator || {};
  const cores = nav.hardwareConcurrency ?? 8;
  const mem = nav.deviceMemory ?? 8;
  if (isCoarsePointer() || cores <= 2 || mem <= 2) return "reduced";
  return "full";
}

export function tierConfig(tier) {
  switch (tier) {
    case "full":
      return { dprCap: 2.5, bloom: true, parallax: true, heroParticles: 320 };
    case "reduced":
      return { dprCap: 1.5, bloom: false, parallax: false, heroParticles: 90 };
    default:
      return { dprCap: 1, bloom: false, parallax: false, heroParticles: 0 };
  }
}
