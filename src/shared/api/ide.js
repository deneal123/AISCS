import { request } from './request';

const root = (threadId) => `/api/chats/${encodeURIComponent(threadId)}/ide/repositories`;
const repo = (threadId, repositoryId) => `${root(threadId)}/${encodeURIComponent(repositoryId)}`;
const readOptions = (signal) => ({ signal, timeout: 15000, __skipRetry: true });
const editOptions = (signal, actorSession) => ({ ...readOptions(signal), headers: { 'X-Workspace-Session': actorSession } });

export const executeIdeCommand = (threadId, repositoryId, data, actorSession) => request({
  method: 'post', url: `${repo(threadId, repositoryId)}/console`, data,
  ...editOptions(undefined, actorSession), timeout: 135000,
});
export const getIdeCommand = (threadId, repositoryId, executionId) => request({
  method: 'get', url: `${repo(threadId, repositoryId)}/console/${encodeURIComponent(executionId)}`,
  ...readOptions(),
});

export const getIdeAgentCommands = (threadId, repositoryId, generation, signal) => request({
  method: 'get', url: `${repo(threadId, repositoryId)}/agent-commands`,
  params: { generation }, ...readOptions(signal),
});

export const prepareIdeWorkspace = (threadId, repositoryId, signal, actorSession) => request({
  method: 'post', url: `/api/chats/${encodeURIComponent(threadId)}/ide/prepare`,
  data: repositoryId ? { repository_id: repositoryId } : {},
  ...editOptions(signal, actorSession), timeout: 75000,
});

export const prepareIdeAgent = (threadId, repositoryId, generation, signal) => request({
  method: 'post', url: `${repo(threadId, repositoryId)}/agent/target`, data: { generation }, ...readOptions(signal),
});

export const operateIdeGit = (threadId, repositoryId, data, signal, actorSession) => request({
  method: 'post', url: `${repo(threadId, repositoryId)}/git`, data, ...editOptions(signal, actorSession), timeout: 75000,
});

export const cloneIdeRepository = (threadId, data, signal, actorSession) => request({
  method: 'post', url: `/api/chats/${encodeURIComponent(threadId)}/ide/clones`, data,
  ...editOptions(signal, actorSession), timeout: 95000,
});
export const getIdeClone = (threadId, intentId, signal) => request({
  method: 'get', url: `/api/chats/${encodeURIComponent(threadId)}/ide/clones/${encodeURIComponent(intentId)}`,
  ...readOptions(signal),
});
export const getIdeCloneRecovery = (threadId, repositoryId, signal) => request({
  method: 'get', url: `${repo(threadId, repositoryId)}/clone-attempt`, ...readOptions(signal),
});

export const leaseIdeFile = (threadId, repositoryId, data, signal, actorSession) => request({
  method: 'post', url: `${repo(threadId, repositoryId)}/files/lease`, data, ...editOptions(signal, actorSession),
});
export const writeIdeFile = (threadId, repositoryId, data, signal, actorSession) => request({
  method: 'post', url: `${repo(threadId, repositoryId)}/files/write`, data, ...editOptions(signal, actorSession),
});
export const copyLibraryToIde = (threadId, repositoryId, fileId, data, signal, actorSession) => request({
  method: 'post', url: `${repo(threadId, repositoryId)}/library/${encodeURIComponent(fileId)}/copy`,
  data, ...editOptions(signal, actorSession), timeout: 45000,
});
export const moveIdeFile = (threadId, repositoryId, data, signal, actorSession) => request({
  method: 'post', url: `${repo(threadId, repositoryId)}/files/move`, data, ...editOptions(signal, actorSession),
});

export const listIdeRepositories = (threadId, offset = 0, signal) => request({
  method: 'get', url: root(threadId), params: { offset, limit: 30 }, ...readOptions(signal),
});
export const registerIdeRepository = (threadId, payload, signal) => request({
  method: 'post', url: root(threadId), data: payload, ...readOptions(signal),
});
export const provisionIdeRuntime = (threadId, repositoryId, signal) => request({
  method: 'post', url: `${repo(threadId, repositoryId)}/runtime`, data: {}, ...readOptions(signal),
});
export const getIdeRuntime = (threadId, repositoryId, signal) => request({
  method: 'get', url: `${repo(threadId, repositoryId)}/runtime`, ...readOptions(signal),
});
export const readIdeTree = (threadId, repositoryId, generation, signal) => request({
  method: 'post', url: `${repo(threadId, repositoryId)}/files/tree`,
  data: { path: '', ...(generation ? { generation } : {}) }, ...readOptions(signal),
});
export const readIdeFile = (threadId, repositoryId, path, generation, signal) => request({
  method: 'post', url: `${repo(threadId, repositoryId)}/files/read`,
  data: { path, generation }, ...readOptions(signal),
});

export const getIdeCheckpointCapabilities = (threadId, repositoryId, signal) => request({
  method: 'get', url: `${repo(threadId, repositoryId)}/checkpoints/capabilities`, ...readOptions(signal),
});
export const listIdeCheckpoints = (threadId, repositoryId, signal) => request({
  method: 'get', url: `${repo(threadId, repositoryId)}/checkpoints`, ...readOptions(signal),
});
export const getIdeCheckpoint = (threadId, repositoryId, checkpointId, signal) => request({
  method: 'get', url: `${repo(threadId, repositoryId)}/checkpoints/${encodeURIComponent(checkpointId)}`, ...readOptions(signal),
});
export const discardIdeCheckpoint = (threadId, repositoryId, checkpointId, signal) => request({
  method: 'post', url: `${repo(threadId, repositoryId)}/checkpoints/${encodeURIComponent(checkpointId)}/discard`,
  data: {}, ...readOptions(signal), timeout: 45000,
});
export const abandonIdeCheckpoint = (threadId, repositoryId, checkpointId, signal) => request({
  method: 'post', url: `${repo(threadId, repositoryId)}/checkpoints/${encodeURIComponent(checkpointId)}/abandon`,
  data: {}, ...readOptions(signal),
});
export const saveIdeCheckpoint = (threadId, repositoryId, data, signal, actorSession) => request({
  method: 'post', url: `${repo(threadId, repositoryId)}/checkpoints`, data,
  ...editOptions(signal, actorSession), timeout: 95000,
});
export const reconcileIdeCheckpoint = (threadId, repositoryId, checkpointId, signal) => request({
  method: 'post', url: `${repo(threadId, repositoryId)}/checkpoints/${encodeURIComponent(checkpointId)}/reconcile`,
  data: {}, ...readOptions(signal), timeout: 45000,
});
export const restoreIdeCheckpoint = (threadId, repositoryId, data, signal) => request({
  method: 'post', url: `${repo(threadId, repositoryId)}/restores`, data, ...readOptions(signal), timeout: 95000,
});
export const reconcileIdeRestore = (threadId, repositoryId, restoreId, signal) => request({
  method: 'post', url: `${repo(threadId, repositoryId)}/restores/${encodeURIComponent(restoreId)}/reconcile`,
  data: {}, ...readOptions(signal), timeout: 45000,
});
