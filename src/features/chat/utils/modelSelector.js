export const AUTO_MODE_LABEL = "Автоматический режим (Auto)";

export const normalizeModelList = (models) => {
  if (!Array.isArray(models)) return [];
  const unique = new Set();
  const result = [];

  for (const value of models) {
    const model = String(value || "").trim();
    if (!model || unique.has(model)) continue;
    unique.add(model);
    result.push(model);
  }

  return result;
};

export const resolveModelTriggerLabel = (selectedModel) => {
  if (!selectedModel) return AUTO_MODE_LABEL;
  const meta = parseModelMeta(selectedModel);
  return meta.label || AUTO_MODE_LABEL;
};

export const resolveMessageModelLabel = (message, lastUsedModel = '') => {
  const metadata = message?.metadata || {};
  const usage = metadata.usage || {};
  return metadata.actual_authoring_model
    || usage.actual_model
    || metadata.selected_model
    || usage.model
    || metadata.model
    || lastUsedModel
    || 'Ассистент';
};

const PROVIDER_LABELS = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  google: "Google",
  "meta-llama": "Meta",
  meta: "Meta",
  mistralai: "Mistral",
  mistral: "Mistral",
  deepseek: "DeepSeek",
  qwen: "Qwen",
  "x-ai": "xAI",
  cohere: "Cohere",
  perplexity: "Perplexity",
  mws: "MWS",
  gigachat: "GigaChat",
  yandexgpt: "YandexGPT",
};

const prettifyProvider = (provider) => {
  const key = String(provider || "").toLowerCase();
  if (PROVIDER_LABELS[key]) return PROVIDER_LABELS[key];
  return key ? key.charAt(0).toUpperCase() + key.slice(1) : "";
};

/**
 * Разбор метаданных модели ЧИСТО из строки id — без выдумывания цен/возможностей.
 * "openai/gpt-4o" -> { provider: "openai", providerLabel: "OpenAI", label: "gpt-4o" }.
 * Модели без префикса провайдера получают только label = id.
 */
export const parseModelMeta = (modelId) => {
  const id = String(modelId || "").trim();
  const slash = id.indexOf("/");
  if (slash > 0) {
    const provider = id.slice(0, slash);
    return { id, provider, providerLabel: prettifyProvider(provider), label: id.slice(slash + 1) || id };
  }
  // Провайдеры без «/»: у российских id имя провайдера — это сам префикс.
  // "GigaChat" → gigachat; "GigaChat-Pro" → gigachat; "mws-gpt-alpha" → mws;
  // "yandexgpt-lite" → yandexgpt. Иначе — модель без провайдера (label = id).
  const lower = id.toLowerCase();
  for (const key of Object.keys(PROVIDER_LABELS)) {
    if (lower === key || lower.startsWith(`${key}-`)) {
      return { id, provider: key, providerLabel: prettifyProvider(key), label: id };
    }
  }
  return { id, provider: null, providerLabel: null, label: id };
};

// Домашние/первично-значимые провайдеры показываем первыми — иначе среди 400+
// моделей их (напр. GigaChat, MWS) не видно в усечённом до N списке без поиска.
const PROVIDER_PRIORITY = ["gigachat", "mws", "yandexgpt"];

const providerRank = (meta) => {
  const i = PROVIDER_PRIORITY.indexOf(String(meta.provider || "").toLowerCase());
  return i === -1 ? PROVIDER_PRIORITY.length : i;
};

/** Список моделей, отсортированный: приоритетные провайдеры → провайдер → имя. */
export const sortModelsByProvider = (models) => {
  return [...normalizeModelList(models)].sort((a, b) => {
    const ma = parseModelMeta(a);
    const mb = parseModelMeta(b);
    const ra = providerRank(ma);
    const rb = providerRank(mb);
    if (ra !== rb) return ra - rb; // домашние провайдеры вперёд
    const pa = ma.providerLabel || "￿"; // без провайдера — в конец
    const pb = mb.providerLabel || "￿";
    if (pa !== pb) return pa.localeCompare(pb);
    return ma.label.localeCompare(mb.label);
  });
};
