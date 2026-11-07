import { useEffect, useState } from 'react';
import { simulationApi } from '../api';
import { maleCnsViewPosition } from './connectomeMorphology';

export function decodeSynapsePoints(record, page, manifest) {
  const partners = new Set(page.items.map(item => item.target_id || item.source_id));
  if (record.body_id !== page.nodeId || record.direction !== page.direction
      || record.graph_manifest_sha256 !== manifest || record.graph_offset !== page.offset
      || record.coordinate_frame !== 'male-cns-v1.0-native-8nm' || record.counts_match !== true
      || record.source_md5 !== '58efcf712f8c4d4de5f2ad51e97def76'
      || !Array.isArray(record.edge_counts) || record.edge_counts.length !== page.items.length
      || !Array.isArray(record.pairs) || record.pairs.length !== record.returned
      || !Number.isSafeInteger(record.total) || record.total < record.returned
      || record.returned > 10000 || record.truncated !== (record.total > record.returned)) throw new Error('synapse_identity');
  page.items.forEach((item, index) => {
    const edge = record.edge_counts[index];
    if (edge?.partner_id !== (item.target_id || item.source_id) || edge.graph_synapses !== item.synapse_count
        || edge.source_pairs !== edge.graph_synapses) throw new Error('synapse_edge');
  });
  const positions = new Float32Array(record.pairs.length * 3);
  const presynaptic = new Map();
  record.pairs.forEach((pair, index) => {
    const primary = page.direction === 'outgoing' ? 'pre' : 'post';
    const other = primary === 'pre' ? 'post' : 'pre';
    if (String(pair[`body_${primary}`]) !== page.nodeId || !partners.has(String(pair[`body_${other}`]))) throw new Error('synapse_partner');
    const xyz = ['x', 'y', 'z'].map(axis => pair[`${axis}_${primary}`]);
    if (!xyz.every(value => Number.isSafeInteger(value) && value >= 0 && value <= 250000)) throw new Error('synapse_coordinate');
    positions.set(maleCnsViewPosition(xyz.map(value => value * .008)), index * 3);
    const neuron = String(pair.body_pre);
    if (!presynaptic.has(neuron)) presynaptic.set(neuron, []);
    presynaptic.get(neuron).push(index);
  });
  return { positions, presynaptic, returned: record.returned, total: record.total, truncated: record.truncated };
}

export default function useSynapsePoints(runId, page, manifest) {
  const [state, setState] = useState({ data: null, loading: false, error: false });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setState({ runId, page, manifest, data: null, loading: Boolean(runId && page && manifest), error: false });
    if (!runId || !page || !manifest) return () => controller.abort();
    simulationApi.synapses(runId, page.nodeId, page.direction, page.offset, controller.signal)
      .then(record => decodeSynapsePoints(record, page, manifest))
      .then(data => { if (!controller.signal.aborted) setState({ runId, page, manifest, data, loading: false, error: false }); })
      .catch(() => { if (!controller.signal.aborted) setState({ runId, page, manifest, data: null, loading: false, error: true }); });
    return () => controller.abort();
  }, [runId, page, manifest, attempt]);
  const current = state.runId === runId && state.page === page && state.manifest === manifest;
  return { ...(current ? state : { data: null, loading: false, error: false }), retry: () => setAttempt(value => value + 1) };
}
