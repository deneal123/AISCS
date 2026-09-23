export const PROJECT_NAME = "GPTHub";
// Версия подтягивается из frontend/package.json (проброшена craco как
// REACT_APP_VERSION) — единый источник, без хардкода. Фоллбэк — на случай сред,
// где переменная не задана (напр. отдельные unit-прогоны).
export const PROJECT_VERSION = process.env.REACT_APP_VERSION || "0.0.0";
export const COMPANY_NAME = "InCellCorp";
export const ORG_GITHUB_URL = "https://github.com/Prischli-Drink-Coffee";
export const ORG_VK_URL = "https://vk.com/incellcorp";
