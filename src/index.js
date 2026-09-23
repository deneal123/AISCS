// Полифиллы для кроссбраузерной совместимости (должны быть первыми)
import "./utils/polyfills";

import React from "react";
import ReactDOM from "react-dom/client";
import { ChakraProvider, ColorModeScript } from "@chakra-ui/react";
import App from "./App";
import theme from "./theme";
import { AuthProvider } from "./app/providers";
import { BillingProvider } from "./features/billing/context/BillingContext";
import { reportWebVitals } from "./utils/webVitals";
import "./xy-theme.css";
import "./styles/motion.css";
import {
  registerServiceWorker,
  unregisterServiceWorker,
} from "./serviceWorkerRegistration";

// Отключаем нативное восстановление скролла: после ПЕРЕЗАГРУЗКИ страница должна
// открываться сверху, а не прыгать на прежнюю (или сдвинутую из-за ленивого
// контента / изменившейся вёрстки) позицию. Роут-переходы делает ScrollToTop.
if ("scrollRestoration" in window.history) {
  window.history.scrollRestoration = "manual";
}

const root = ReactDOM.createRoot(document.getElementById("root"));

root.render(
      <ChakraProvider theme={theme}>
      <ColorModeScript initialColorMode={theme.config.initialColorMode} />
      <AuthProvider>
        <BillingProvider>
          <App />
        </BillingProvider>
      </AuthProvider>
    </ChakraProvider>
);

reportWebVitals({ debug: process.env.NODE_ENV === "development" });

if (process.env.NODE_ENV === "production") {
  registerServiceWorker();
} else {
  unregisterServiceWorker();
}
