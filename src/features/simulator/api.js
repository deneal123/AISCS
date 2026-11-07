import httpClient from '@api/httpClient';

const root = '/api/simulations/v1';
const saveBlob = (data, name) => {
  const url = URL.createObjectURL(data);
  const link = document.createElement('a');
  link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
export const simulationApi = {
  profile: async (signal) => (await httpClient.get('/api/application-profile', { signal })).data,
  eventsUrl: (id) => {
    const target = new URL(httpClient.defaults.baseURL || '/', window.location.origin);
    target.protocol = target.protocol === 'https:' ? 'wss:' : 'ws:';
    target.pathname = `${root}/runs/${id}/events`; target.search = ''; target.hash = '';
    return target.toString();
  },
  catalog: async (signal) => (await httpClient.get(`${root}/catalog`, { signal })).data,
  sceneTemplate: async (signal) => (await httpClient.get(`${root}/scene-template`, { signal })).data,
  list: async (signal, offset = 0) => (await httpClient.get(`${root}/runs`, { signal, params: { offset, limit: 30 } })).data,
  overview: async (id, signal) => (await httpClient.get(`${root}/runs/${id}/cns-overview`, { signal })).data,
  overviewChunk: async (id, name, signal) => (await httpClient.get(`${root}/runs/${id}/cns-overview/${name}`, { signal, responseType: 'arraybuffer' })).data,
  neuropil: async (id, signal) => (await httpClient.get(`${root}/runs/${id}/neuropil`, { signal })).data,
  neuropilChunk: async (id, name, signal) => (await httpClient.get(`${root}/runs/${id}/neuropil/${name}`, { signal, responseType: 'arraybuffer' })).data,
  get: async (id, signal) => (await httpClient.get(`${root}/runs/${id}`, { signal })).data,
  replays: async (id, signal) => (await httpClient.get(`${root}/runs/${id}/replays`, { signal })).data,
  fieldGraphRuns: async (signal) => (await httpClient.get(`${root}/field-graph-runs`, { signal })).data,
  createFieldGraph: async (payload) => (await httpClient.post(`${root}/field-graph-runs`, payload)).data,
  fragmentPopulationRuns: async (signal, parentRunId) => (await httpClient.get(`${root}/fragment-population-runs`, { signal, params: parentRunId ? { parent_run_id: parentRunId } : undefined })).data,
  createFragmentPopulation: async (payload) => (await httpClient.post(`${root}/fragment-population-runs`, payload)).data,
  createFieldProxyFromFragment: async (id, payload, signal) => (await httpClient.post(`${root}/runs/${id}/field-proxy`, payload, { signal, timeout: 150000 })).data,
  createFieldProxyDirect: async (id, payload, signal) => (await httpClient.post(`${root}/runs/${id}/field-proxy-direct`, payload, { signal, timeout: 150000 })).data,
  fieldProxyRuns: async (id, signal) => (await httpClient.get(`${root}/runs/${id}/field-proxy-runs`, { signal })).data,
  feedbackRuns: async (id, signal) => (await httpClient.get(`${root}/runs/${id}/population-feedback-runs`, { signal })).data,
  feedbackSource: async (id, signal) => (await httpClient.post(`${root}/runs/${id}/population-feedback-source`, {}, { signal, timeout: 150000 })).data,
  createFeedback: async (payload, signal) => (await httpClient.post(`${root}/population-feedback-runs`, payload, { signal, timeout: 150000 })).data,
  populationTargetCandidates: async (runId, node, signal) => (await httpClient.get(`${root}/runs/${runId}/population-target-candidates/${node}`, { signal, timeout: 150000 })).data,
  populationTargetRuns: async (runId, node, signal) => (await httpClient.get(`${root}/runs/${runId}/population-target-runs/${node}`, { signal })).data,
  preparePopulationTarget: async (runId, signal) => (await httpClient.post(`${root}/runs/${runId}/population-target-source`, {}, { signal, timeout: 150000 })).data,
  createPopulationTarget: async (payload) => (await httpClient.post(`${root}/population-target-runs`, payload, { timeout: 150000 })).data,
  rerecordPreview: async (id, payload, signal) => (await httpClient.post(`${root}/runs/${id}/rerecord-preview`, payload, { signal, timeout: 150000 })).data,
  spatialCandidates: async (id, payload, signal) => (await httpClient.post(`${root}/runs/${id}/spatial-candidates`, payload, { signal, timeout: 0 })).data,
  contactScreen: async (id, payload, signal) => (await httpClient.post(`${root}/runs/${id}/contact-screen`, payload, { signal, timeout: 0 })).data,
  contactPositions: async (id, payload, signal) => (await httpClient.post(`${root}/runs/${id}/contact-positions`, payload, { signal, timeout: 0 })).data,
  outgoing: async (id, node, offset, signal) => (await httpClient.get(`${root}/runs/${id}/neurons/${node}/outgoing`, { signal, params: { offset, limit: 20 } })).data,
  incoming: async (id, node, offset, signal) => (await httpClient.get(`${root}/runs/${id}/neurons/${node}/incoming`, { signal, params: { offset, limit: 20 } })).data,
  synapses: async (id, node, direction, offset, signal) => (await httpClient.get(`${root}/runs/${id}/neurons/${node}/${direction}/synapses`, { signal, timeout: 180000, params: { offset, limit: 20 } })).data,
  morphology: async (id, node, signal) => (await httpClient.get(`${root}/runs/${id}/neurons/${node}/morphology`, { signal })).data,
  create: async (payload) => (await httpClient.post(`${root}/runs`, payload)).data,
  cancel: async (id) => (await httpClient.post(`${root}/runs/${id}/cancel`)).data,
  removeFromHistory: async (id) => httpClient.delete(`${root}/runs/${id}`),
  artifacts: async (id, signal) => (await httpClient.get(`${root}/runs/${id}/artifacts`, { signal })).data,
  readArtifact: async (runId, artifactId, signal) => (await httpClient.get(`${root}/runs/${runId}/artifacts/${artifactId}`, { signal, responseType: 'arraybuffer' })).data,
  downloadManifest: async (id) => {
    const response = await httpClient.get(`${root}/runs/${id}/manifest`, { responseType: 'blob' });
    saveBlob(response.data, 'manifest.json');
  },
  download: async (runId, artifact) => {
    const response = await httpClient.get(`${root}/runs/${runId}/artifacts/${artifact.id}`, { responseType: 'blob' });
    saveBlob(response.data, artifact.name);
  },
};
