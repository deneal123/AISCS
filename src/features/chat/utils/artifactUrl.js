import httpClient from '@api/httpClient';


// Durable generated files are referenced by opaque UserFile IDs. Legacy
// messages may still contain a storage key and keep using the old proxy.
export function resolveArtifactUrl(url, filename, fileId) {
  const base = (httpClient?.defaults?.baseURL || '').replace(/\/$/, '');
  if (fileId) {
    return `${base}/api/service/files/v1/${encodeURIComponent(fileId)}/download`;
  }
  if (!url || /^(https?:|data:|blob:)/i.test(url)) return url;
  const params = new URLSearchParams({ file_key: url });
  if (filename) params.set('filename', filename);
  return `${base}/api/chats/files/download?${params.toString()}`;
}
