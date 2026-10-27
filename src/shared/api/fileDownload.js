import httpClient from './httpClient';

// Resolve storage only on the backend after cookie authentication and ownership.
// Never accept a persisted presigned URL or storage key as a download fallback.
export function ownedFileDownloadUrl(fileId) {
  if (typeof fileId !== 'string' || !fileId.trim()) return null;
  const base = (httpClient?.defaults?.baseURL || '').replace(/\/$/, '');
  return `${base}/api/service/files/v1/${encodeURIComponent(fileId)}/download`;
}
