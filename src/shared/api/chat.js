import { request } from './request';
import { mapChatUploadResponse, mapModelsResponse } from './dtoMappers';

export const createChatThread = (userId = null, options = {}) =>
  request({ method: 'post', url: '/api/chats/', data: userId ? { user_id: userId } : {}, ...options });

export const sendChatMessage = (threadId, message, userId = null, model = null, inputType = null, params = {}, options = {}) => {
  const { webSearch = false, deepResearch = false, fileContext = '', fileIds = [], routeOverride = null, attachments = [], confirmExpensiveRun = false, confirmOfferId = null } = params || {};
  return request({
    method: 'post',
    url: `/api/chats/${threadId}/message`,
    data: {
      text: message.trim(),
      ...(userId && { user_id: userId }),
      ...(model && { model }),
      ...(inputType && { input_type: inputType }),
      ...(webSearch && { web_search: true }),
      ...(deepResearch && { deep_research: true }),
      ...(fileContext && { file_context: fileContext }),
      ...(Array.isArray(fileIds) && fileIds.length && { file_ids: fileIds }),
      ...(routeOverride && { route_override: routeOverride }),
      ...(params.documentContext && { document_context: params.documentContext }),
      ...(Array.isArray(attachments) && attachments.length && { attachments }),
      ...(confirmExpensiveRun && { confirm_expensive_run: true }),
      ...(confirmOfferId && { confirm_offer_id: confirmOfferId }),
      ...(confirmOfferId && { confirmation_decision: params.confirmationDecision || 'accept' }),
    },
    ...options,
  });
};

export const getChatModelsCatalog = (options = {}) =>
  request({ method: 'get', url: '/api/chats/models/catalog', ...options });

// Личности (специализации агента) для селектора композера. Список короткий и меняется
// только правкой реестра в админке, поэтому кэш не нужен.
export const getChatPersonas = (options = {}) =>
  request({ method: 'get', url: '/api/chats/personas', ...options });

export const getChatProviderStatus = (options = {}) =>
  request({ method: 'get', url: '/api/chats/providers/status', ...options });

export const getChatModels = (options = {}) =>
  request({ method: 'get', url: '/api/chats/models', ...options }, mapModelsResponse);

// Каталог и список моделей за сессию не меняются, но это самые тяжёлые «статик»-
// ответы (сотни моделей), и они перезапрашивались при КАЖДОМ монтировании /chat —
// ушёл в биллинг, вернулся → снова. Кэшируем промис на время жизни вкладки;
// неудачный запрос кэш не занимает, чтобы можно было повторить.
let catalogPromise = null;
let modelsPromise = null;

export const getChatModelsCatalogCached = () => {
  if (!catalogPromise) {
    const pending = getChatModelsCatalog().catch((error) => {
      if (catalogPromise === pending) catalogPromise = null;
      throw error;
    });
    catalogPromise = pending;
  }
  return catalogPromise;
};

export const getChatModelsCached = () => {
  if (!modelsPromise) {
    const pending = getChatModels().catch((error) => {
      if (modelsPromise === pending) modelsPromise = null;
      throw error;
    });
    modelsPromise = pending;
  }
  return modelsPromise;
};

export const resetChatModelsCache = () => {
  catalogPromise = null;
  modelsPromise = null;
};

export const getChatHistory = (threadId, limit = 50, options = {}) =>
  request({ method: 'get', url: `/api/chats/${threadId}`, params: { per_page: limit.toString(), page: '1' }, ...options });

export const getUserChats = (userId, limit = 20, options = {}) =>
  request({ method: 'get', url: '/api/chats/', params: { per_page: limit.toString(), page: '1', ...(userId != null ? { user_id: userId } : {}) }, ...options });

export const deleteChatThread = (threadId, userId, options = {}) =>
  request({ method: 'delete', url: `/api/chats/${threadId}`, data: { user_id: userId }, ...options });

export const renameChatThread = (threadId, title, options = {}) =>
  request({ method: 'patch', url: `/api/chats/${threadId}`, data: { title }, ...options });

export const sendMessageFeedback = (threadId, contentKey, rating, options = {}) =>
  request({ method: 'post', url: `/api/chats/${threadId}/feedback`, data: { content_key: contentKey, rating }, ...options });

export const saveThreadTrace = (threadId, contentKey, trace, options = {}) =>
  request({ method: 'put', url: `/api/chats/${threadId}/trace`, data: { content_key: contentKey, trace }, ...options });

export const getThreadTrace = (threadId, options = {}) =>
  request({ method: 'get', url: `/api/chats/${threadId}/trace`, ...options });

export const uploadChatFile = (file, threadId = '', onProgress, options = {}) => {
  // transcriptionMode/Model — не axios-конфиг, а form-поля управления транскрипцией
  // аудио на бэке; вычленяем их из options, остальное уходит в request-конфиг.
  const { transcriptionMode, transcriptionModel, uploadIntentId, ...requestOptions } = options;
  const formData = new FormData();
  formData.append('file', file);
  formData.append('thread_id', threadId);
  if (transcriptionMode) formData.append('transcription_mode', transcriptionMode);
  if (transcriptionModel) formData.append('transcription_model', transcriptionModel);
  if (uploadIntentId) formData.append('upload_intent_id', uploadIntentId);
  return request(
    { method: 'post', url: '/api/chats/upload', data: formData, headers: { 'Content-Type': 'multipart/form-data' }, onUploadProgress: (e) => onProgress?.(Math.round((e.loaded * 100) / e.total)), timeout: 60000, ...requestOptions },
    mapChatUploadResponse,
  );
};

export const getTranscriptionConfig = (options = {}) =>
  request({ method: 'get', url: '/api/chats/transcription/config', ...options });

export const createFileUploadUrl = (fileName, contentType, mode = 'CHAT', options = {}) =>
  request({ method: 'post', url: `/api/service/files/v1/presign/${mode}`, data: { filename: fileName, content_type: contentType }, ...options });

export const getUserMemory = (userId, options = {}) =>
  request({ method: 'get', url: `/api/memory/${userId}`, ...options });

export const addMemoryFact = (userId, factType, factKey, factValue, options = {}) =>
  request({ method: 'post', url: `/api/memory/${userId}/facts`, data: { user_id: userId, fact_type: factType, fact_key: factKey, fact_value: factValue }, ...options });

export const deleteMemoryFact = (userId, factId, options = {}) =>
  request({ method: 'delete', url: `/api/memory/${userId}/facts/${factId}`, ...options });

// Полная очистка долговременной памяти: факты + семантическая память MemOS.
// Отвечает РАЗДЕЛЬНЫМ отчётом ({ facts_deleted, memos }), а не пустым 204: половины
// независимы, и «факты стёрли, MemOS не ответил» пользователю надо показать честно.
export const clearUserMemory = (userId, options = {}) =>
  request({ method: 'delete', url: `/api/memory/${userId}`, ...options });

export const searchMemory = (userId, query, options = {}) =>
  request({ method: 'get', url: `/api/memory/${userId}/search`, params: { q: query }, ...options });

// Дашборд семантической памяти MemOS (per-user): счётчики по типам узлов. Активен
// только при memos-провайдере; иначе {}. Вспомогательный к фактам, не критичный.
export const getUserMemoryDashboard = (userId, options = {}) =>
  request({ method: 'get', url: `/api/memory/${userId}/dashboard`, ...options });

// Граф знаний: личный корпус пользователя (документы + разобранные репозитории).
// Копится МЕЖДУ тредами — в отличие от файла в контексте треда, который жил один на тред.
// user_id в URL не нужен: граф берётся по авторизованному пользователю.
export const getGraphSummary = (options = {}) =>
  request({ method: 'get', url: '/api/graph/summary', ...options });

export const searchGraph = (query, options = {}) =>
  request({ method: 'get', url: '/api/graph/search', params: { q: query }, ...options });

export const deleteGraph = (options = {}) =>
  request({ method: 'delete', url: '/api/graph/', ...options });

// Интерактивный граф забираем ЗАПРОСОМ, а не ссылкой <a href>. Голая ссылка ушла бы на
// origin фронта (в dev это вообще не бэкенд — API живёт на REACT_APP_API_BASE_URL) и не
// донесла бы авторизацию. Отдаём HTML строкой, вызывающий открывает его как blob.
export const getGraphHtml = (options = {}) =>
  request({ method: 'get', url: '/api/graph/html', responseType: 'text', ...options });

/** @deprecated Use uploadChatFile */
export const uploadFileForChat = (file, threadId = '', options = {}) =>
  uploadChatFile(file, threadId, undefined, options);

export const webSearch = (query, numResults = 5, options = {}) =>
  request({ method: 'post', url: '/api/chats/web-search', data: null, params: { q: query, num_results: numResults }, ...options });

export const parseUrl = (url, options = {}) =>
  request({ method: 'post', url: '/api/chats/parse-url', data: null, params: { url }, ...options });

// --- рабочее место треда (песочница) -------------------------------------------------
// Дерево, превью и история читаются ПО ЗАПРОСУ, а не вместе с ответом: дерево на тысячу
// файлов и превью на мегабайт не должны ехать в каждом сообщении.
export const getWorkspaceTree = (threadId, path = '', options = {}) =>
  request({ method: 'get', url: `/api/chats/${threadId}/workspace`, params: { path }, ...options });

export const getWorkspaceFile = (threadId, path, options = {}) =>
  request({ method: 'post', url: `/api/chats/${threadId}/workspace/file`, data: { path }, ...options });

export const getWorkspaceHistory = (threadId, options = {}) =>
  request({ method: 'get', url: `/api/chats/${threadId}/workspace/history`, ...options });

export const getWorkspaceDiff = (threadId, ref, path = '', options = {}) =>
  request({ method: 'post', url: `/api/chats/${threadId}/workspace/diff`, data: { ref, path }, ...options });

const workspaceMutationOptions = (options = {}) => {
  const { actorSession, headers, ...requestOptions } = options;
  return {
    ...requestOptions,
    headers: {
      ...(headers || {}),
      ...(actorSession ? { 'X-Workspace-Session': actorSession } : {}),
    },
  };
};

export const revertWorkspace = (threadId, ref, expectedRevision, path = '', options = {}) =>
  request({ method: 'post', url: `/api/chats/${threadId}/workspace/revert`, data: { ref, expected_revision: expectedRevision, path }, ...workspaceMutationOptions(options) });

export const getWorkspaceRoom = (threadId, options = {}) =>
  request({ method: 'get', url: `/api/chats/${threadId}/workspace/room`, ...options });

export const getWorkHub = (threadId, options = {}) =>
  request({ method: 'get', url: `/api/chats/${threadId}/work`, ...options });

export const getAccountWorkLibrary = (options = {}) =>
  request({ method: 'get', url: '/api/chats/work-library', ...options });

export const activateWorkHub = (threadId, options = {}) =>
  request({ method: 'post', url: `/api/chats/${threadId}/work/activate`, ...options });

export const preparePdfWorkspace = (threadId, { retry = false } = {}) =>
  request({ method: 'post', url: `/api/chats/${threadId}/work/pdf/prepare`, data: retry ? { retry: true } : {} });

export const acquireWorkspaceLease = (threadId, path, options = {}) =>
  request({ method: 'post', url: `/api/chats/${threadId}/workspace/leases/acquire`, data: { path }, ...workspaceMutationOptions(options) });

export const renewWorkspaceLease = (threadId, path, fence, options = {}) =>
  request({ method: 'post', url: `/api/chats/${threadId}/workspace/leases/renew`, data: { path, fence }, ...workspaceMutationOptions(options) });

export const releaseWorkspaceLease = (threadId, path, fence, options = {}) =>
  request({ method: 'post', url: `/api/chats/${threadId}/workspace/leases/release`, data: { path, fence }, ...workspaceMutationOptions(options) });

export const writeWorkspaceFile = (threadId, path, content, expectedRevision, fence, options = {}) =>
  request({ method: 'post', url: `/api/chats/${threadId}/workspace/write`, data: { path, content, expected_revision: expectedRevision, fence }, ...workspaceMutationOptions(options) });

export const copyLibraryFileToWorkspace = (threadId, fileId, expectedRevision, fence, options = {}) => {
  const { documentPath, ...mutationOptions } = options;
  return request({ method: 'post', url: `/api/chats/${threadId}/work/library/${fileId}/copy`,
    data: { expected_revision: expectedRevision, fence, ...(documentPath ? { document_path: documentPath } : {}) },
    ...workspaceMutationOptions(mutationOptions) });
};

export const uploadFileToWorkspace = (threadId, file, expectedRevision, fence, onProgress, options = {}) => {
  const { uploadIntentId, libraryOnly = false, ...mutationOptions } = options;
  const { headers, ...requestOptions } = workspaceMutationOptions(mutationOptions);
  const formData = new FormData();
  formData.append('file', file);
  if (!libraryOnly) {
    formData.append('expected_revision', expectedRevision);
    formData.append('fence', String(fence));
  }
  if (uploadIntentId) formData.append('upload_intent_id', uploadIntentId);
  return request({
    method: 'post',
    url: `/api/chats/${threadId}/work/${libraryOnly ? 'library/upload' : 'upload'}`,
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data', ...headers },
    onUploadProgress: (event) => onProgress?.(event.total ? Math.round((event.loaded * 100) / event.total) : null),
    timeout: 60000,
    ...requestOptions,
  });
};

export const uploadFileToLibrary = (threadId, file, onProgress, options = {}) =>
  uploadFileToWorkspace(threadId, file, '', 0, onProgress, { ...options, libraryOnly: true });

export const getWorkspaceIssues = (threadId, options = {}) =>
  request({ method: 'get', url: `/api/chats/${threadId}/workspace/issues`, ...options });

export const createWorkspaceIssue = (threadId, payload, options = {}) =>
  request({ method: 'post', url: `/api/chats/${threadId}/workspace/issues`, data: payload, ...options });

export const updateWorkspaceIssue = (threadId, issueId, payload, options = {}) =>
  request({ method: 'patch', url: `/api/chats/${threadId}/workspace/issues/${issueId}`, data: payload, ...options });

export const controlWorkspaceRun = (threadId, action, options = {}) =>
  request({ method: 'post', url: `/api/chats/${threadId}/workspace/control`, data: { action }, ...options });

export const getDocumentProfiles = (threadId, options = {}) =>
  request({ method: 'get', url: `/api/chats/${threadId}/workspace/document-profiles`, ...options });

export const createDocumentProject = (threadId, payload, options = {}) => request({
    method: 'post',
    url: `/api/chats/${threadId}/workspace/documents`,
    data: payload,
    ...workspaceMutationOptions(options),
  });

export const getDocumentProject = (threadId, path, options = {}) => request({
  method: 'post',
  url: `/api/chats/${threadId}/workspace/documents/status`,
  data: { path },
  ...options,
});

export const saveDocumentDraft = (threadId, payload, options = {}) => request({
  method: 'post', url: `/api/chats/${threadId}/workspace/documents/authoring/edit`, data: payload,
  ...workspaceMutationOptions(options),
});

export const getDocumentProposal = (threadId, proposalId, options = {}) => request({
  method: 'get', url: `/api/chats/${threadId}/workspace/documents/proposals/${proposalId}`, ...options,
});

export const getDocumentAuthoringState = (threadId, path, options = {}) => request({
  method: 'post',
  url: `/api/chats/${threadId}/workspace/documents/authoring`,
  data: { path },
  ...options,
});

export const getDocumentSources = (threadId, path, options = {}) => request({
  method: 'post', url: `/api/chats/${threadId}/workspace/documents/sources`, data: { path }, ...options,
});

export const applyDocumentProfile = (threadId, payload, options = {}) => request({
  method: 'post',
  url: `/api/chats/${threadId}/workspace/documents/profile`,
  data: payload,
  ...workspaceMutationOptions(options),
});

export const applyDocumentVendorOverlay = (threadId, fileId, payload, options = {}) => request({
  method: 'post',
  url: `/api/chats/${threadId}/workspace/documents/vendor/${fileId}`,
  data: payload,
  ...workspaceMutationOptions(options),
});

export const activateDocumentVendorProfile = (
  threadId,
  packageId,
  payload,
  options = {},
) => request({
  method: 'post',
  url: `/api/chats/${threadId}/workspace/documents/vendor/${packageId}/activate`,
  data: payload,
  ...workspaceMutationOptions(options),
});

export const startDocumentBuild = (threadId, payload, options = {}) => request({
  method: 'post',
  url: `/api/chats/${threadId}/workspace/documents/builds`,
  data: payload,
  ...workspaceMutationOptions(options),
});

export const getDocumentBuild = (threadId, buildId, options = {}) => request({
  method: 'post',
  url: `/api/chats/${threadId}/workspace/documents/builds/${buildId}`,
  data: {},
  ...options,
});

export const cancelDocumentBuild = (threadId, buildId, fence, options = {}) => request({
  method: 'post',
  url: `/api/chats/${threadId}/workspace/documents/builds/${buildId}/cancel`,
  data: { fence },
  ...workspaceMutationOptions(options),
});

export const publishDocumentArtifact = (threadId, buildId, artifactId, options = {}) =>
  request({
    method: 'post',
    url: `/api/chats/${threadId}/workspace/documents/builds/${buildId}/artifacts/${artifactId}/publish`,
    data: {},
    ...options,
  });

export const downloadDocumentArtifact = (threadId, buildId, artifactId, options = {}) =>
  request({
    method: 'post',
    url: `/api/chats/${threadId}/workspace/documents/builds/${buildId}/artifacts/${artifactId}`,
    data: {},
    responseType: 'blob',
    ...options,
  });

// Обзор файлов аккаунта: какой файл в каких диалогах появлялся. Только на чтение и
// ОТДЕЛЬНО от рабочего каталога треда — тот временный, этот накопительный.
export const getFilesOverview = (options = {}) =>
  request({ method: 'get', url: '/api/files-overview', ...options });
