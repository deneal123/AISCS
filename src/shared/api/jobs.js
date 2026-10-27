import { request } from './request';
import { mapJobDto } from './dtoMappers';

export const startJob = ({ fileId, type = 'CHAT' } = {}, options = {}) =>
  request({
    method: 'post',
    url: '/api/jobs/v1/start',
    data: { file_id: fileId, type },
    ...options,
  }, mapJobDto);

export const fetchJobResult = (jobId, { signal } = {}) =>
  request({ method: 'get', url: `/api/jobs/v1/result/${jobId}`, signal }, mapJobDto);

export const getTaskStatus = (taskId, { signal, skipRetry = false } = {}) =>
  request({ method: 'get', url: `/api/jobs/v1/task/${taskId}/status`, signal, __skipRetry: skipRetry });

export const cancelTask = (taskId, { signal, skipRetry = false } = {}) =>
  request({ method: 'post', url: `/api/jobs/v1/task/${taskId}/cancel`, data: null, signal, __skipRetry: skipRetry });
