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
  list: async (signal, offset = 0) => (await httpClient.get(`${root}/runs`, { signal, params: { offset, limit: 30 } })).data,
  get: async (id, signal) => (await httpClient.get(`${root}/runs/${id}`, { signal })).data,
  create: async (payload) => (await httpClient.post(`${root}/runs`, payload)).data,
  cancel: async (id) => (await httpClient.post(`${root}/runs/${id}/cancel`)).data,
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
