import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Loads the optional capabilities that shape chat controls.
 *
 * Every source is fail-open: a missing persona, rich catalog, or transcription
 * sidecar must narrow its control without making the conversation unavailable.
 */
export function useChatCapabilities() {
  const [availableModels, setAvailableModels] = useState([]);
  const [modelCatalog, setModelCatalog] = useState({});
  const [personas, setPersonas] = useState([]);
  const [transcriptionConfig, setTranscriptionConfig] = useState(null);
  const [modelsStatus, setModelsStatus] = useState('loading');
  const [modelCatalogStatus, setModelCatalogStatus] = useState('loading');
  const generation = useRef(0);

  const loadModels = useCallback(async (refresh = false) => {
    const ticket = ++generation.current;
    setModelsStatus('loading');
    setModelCatalogStatus('loading');
    let api;
    try {
      api = await import('@api/chat');
    } catch {
      if (generation.current === ticket) {
        setModelsStatus('error');
        setModelCatalogStatus('error');
      }
      return;
    }
    if (generation.current !== ticket) return;
    if (refresh) api.resetChatModelsCache();
    try {
      const data = await api.getChatModelsCatalogCached();
      if (generation.current !== ticket) return;
      if (!Array.isArray(data?.models) || data.models.some((model) => typeof model?.id !== 'string' || !model.id.trim())) {
        throw new Error('catalog_invalid');
      }
      const list = data.models;
      setAvailableModels(list.map((model) => model.id));
      setModelCatalog(Object.fromEntries(list.map((model) => [model.id, model])));
      setModelsStatus('ready');
      setModelCatalogStatus('ready');
      return;
    } catch {
      if (generation.current !== ticket) return;
      setModelCatalogStatus('error');
    }
    try {
      const models = await api.getChatModelsCached();
      if (generation.current !== ticket) return;
      if (!Array.isArray(models) || models.some((model) => typeof model !== 'string' || !model.trim())) {
        throw new Error('catalog_invalid');
      }
      setAvailableModels(models);
      setModelCatalog(previous => Object.fromEntries(
        models.filter(id => Object.hasOwn(previous, id)).map(id => [id, previous[id]]),
      ));
      setModelsStatus('ready');
    } catch {
      if (generation.current === ticket) setModelsStatus('error');
    }
  }, []);
  const refreshModels = useCallback(() => loadModels(true), [loadModels]);

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

    loadModels();
    loadPersonas();
    return () => { cancelled = true; generation.current += 1; };
  }, [loadModels]);

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

  return { availableModels, modelCatalog, modelsStatus, modelCatalogStatus, refreshModels, personas, transcriptionConfig };
}
