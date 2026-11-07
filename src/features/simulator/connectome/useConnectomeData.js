import { useEffect, useState } from 'react';
import { simulationApi } from '../api';
import { verifyConnectome } from './connectomeData';
import { applyBodyViewCorrection, loadMorphologyLandmarks } from './connectomeMorphology';
import { verifyFieldGraphEvents } from '../field/fieldGraphEvents';
import { verifyFieldProxyEvents } from '../field/fieldProxyEvents';
import { verifyCoupledEvents, verifyCoupledSourceEvents, verifyFragmentEvents } from '../recording/fragmentEvents';

export default function useConnectomeData(runId, description, fieldGraph = null) {
  const [result, setResult] = useState({ data: null, error: '', loading: false });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setResult({ runId, description, fieldGraph, data: null, error: '', loading: Boolean(runId && description) });
    if (runId && description) (async () => {
      try {
        const files = await simulationApi.artifacts(runId, controller.signal);
        const artifact = files.items.find(file => file.name === 'connectome.bin');
        if (!artifact) throw new Error('missing');
        const buffer = await simulationApi.readArtifact(runId, artifact.id, controller.signal);
        let data = applyBodyViewCorrection(await verifyConnectome(buffer, artifact, description));
        if (fieldGraph) {
          const fieldFiles = await simulationApi.artifacts(fieldGraph.id, controller.signal);
          const coupled = fieldGraph.result?.manifest?.kind === 'experimental-coupled-population';
          if (fieldGraph.result?.manifest?.kind === 'experimental-field-proxy') {
            const graphFile = fieldFiles.items.find(file => file.name === 'network-events.bin');
            const controlFile = fieldFiles.items.find(file => file.name === 'network-control-events.bin');
            const metaFile = fieldFiles.items.find(file => file.name === 'metadata.json');
            if (!graphFile || !metaFile || !controlFile) throw new Error('missing_field_graph');
            const [graph, meta, control] = await Promise.all([
              simulationApi.readArtifact(fieldGraph.id, graphFile.id, controller.signal),
              simulationApi.readArtifact(fieldGraph.id, metaFile.id, controller.signal),
              simulationApi.readArtifact(fieldGraph.id, controlFile.id, controller.signal),
            ]);
            data = await verifyFieldProxyEvents(data, graph, graphFile, meta, metaFile, fieldGraph, control, controlFile);
          } else if (coupled) {
            const graphFile = fieldFiles.items.find(file => file.name === 'coupled-events.bin');
            const expectedBytes = 8 * (data.node_ids.length + fieldGraph.result.preview.network_spikes);
            if (!graphFile || !Number.isSafeInteger(expectedBytes) || expectedBytes > 268435456
                || graphFile.bytes !== expectedBytes) throw new Error('missing_field_graph');
            const events = await simulationApi.readArtifact(fieldGraph.id, graphFile.id, controller.signal);
            data = await verifyCoupledEvents(data, events, graphFile, fieldGraph);
            const sourceEntry = fieldGraph.result.manifest.files.find(file => file.name === 'coupled-source-events.bin');
            if (sourceEntry) {
              const sourceFile = fieldFiles.items.find(file => file.name === sourceEntry.name);
              if (!sourceFile || sourceFile.bytes !== sourceEntry.bytes) throw new Error('missing_source_events');
              const sourceEvents = await simulationApi.readArtifact(fieldGraph.id, sourceFile.id, controller.signal);
              data = await verifyCoupledSourceEvents(data, sourceEvents, sourceFile, fieldGraph);
            }
          } else {
            const fragment = Array.isArray(fieldGraph.configuration?.source_ids);
            const graphFile = fieldFiles.items.find(file => file.name === (fragment ? 'fragment-events.bin' : 'graph.bin'));
            const metaFile = fieldFiles.items.find(file => file.name === (fragment ? 'model.json' : 'metadata.json'));
            if (!graphFile || !metaFile) throw new Error('missing_field_graph');
            const [graph, meta] = await Promise.all([
              simulationApi.readArtifact(fieldGraph.id, graphFile.id, controller.signal),
              simulationApi.readArtifact(fieldGraph.id, metaFile.id, controller.signal),
            ]);
            data = await (fragment ? verifyFragmentEvents : verifyFieldGraphEvents)(data, graph, graphFile, meta, metaFile, fieldGraph.configuration);
          }
        }
        let morphologyError = '';
        try { data = await loadMorphologyLandmarks(data, controller.signal); }
        catch { morphologyError = 'Не удалось восстановить положения нейронов без координат. Повторите загрузку морфологии.'; }
        if (!controller.signal.aborted) setResult({ runId, description, fieldGraph, data, loading: false, error: '', morphologyError });
      } catch {
        if (!controller.signal.aborted) setResult({ runId, description, fieldGraph, data: null, loading: false, error: 'Не удалось проверить коннектом и события этого опыта. Запись и файлы остаются доступны.' });
      }
    })();
    return () => controller.abort();
  }, [runId, description, fieldGraph, attempt]);
  const current = result.runId === runId && result.description === description && result.fieldGraph === fieldGraph;
  return { ...(current ? result : { data: null, error: '', morphologyError: '', loading: Boolean(runId && description) }), retry: () => setAttempt(value => value + 1) };
}
