import { useEffect, useState } from 'react';

/**
 * Loads the optional capabilities that shape chat controls.
 *
 * Every source is fail-open: a missing persona, rich catalog, or transcription
 * sidecar must narrow its control without making the conversation unavailable.
 */
export function useChatCapabilities({ selectedModel, onInvalidModel }) {
  const [availableModels, setAvailableModels] = useState([]);
  const [modelCatalog, setModelCatalog] = useState({});
  const [personas, setPersonas] = useState([]);
  const [transcriptionConfig, setTranscriptionConfig] = useState(null);

  useEffect(() => {
    let cancelled = false;

    const loadPersonas = async () => {
      try {
        const { getChatPersonas } = await import('@api/chat');
        const data = await getChatPersonas();
        if (!cancelled) setPersonas(Array.isArray(data?.personas) ? data.personas : []);
      } catch {
        if (!cancelled) setPersonas([]);
      }
    };

    const loadModels = async () => {
      try {
        const { getChatModelsCatalogCached } = await import('@api/chat');
        const data = await getChatModelsCatalogCached();
        if (cancelled) return;
        const list = Array.isArray(data?.models) ? data.models : [];
        setAvailableModels(list.map((model) => model.id));
        setModelCatalog(Object.fromEntries(list.map((model) => [model.id, model])));
        return;
      } catch {
        // The simple catalog is the established compatibility fallback.
      }
      try {
        const { getChatModelsCached } = await import('@api/chat');
        const models = await getChatModelsCached();
        if (!cancelled) setAvailableModels(Array.isArray(models) ? models : []);
      } catch {
        if (!cancelled) setAvailableModels([]);
      }
    };

    loadModels();
    loadPersonas();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const { getTranscriptionConfig } = await import('@api/chat');
        const config = await getTranscriptionConfig();
        if (!cancelled) setTranscriptionConfig(config);
      } catch {
        // Provider transcription remains available without sidecar metadata.
      }
    };
    load();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (availableModels.length > 0 && selectedModel && !availableModels.includes(selectedModel)) {
      onInvalidModel('');
    }
  }, [availableModels, onInvalidModel, selectedModel]);

  return { availableModels, modelCatalog, personas, transcriptionConfig };
}
