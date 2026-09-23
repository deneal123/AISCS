import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams, useLocation } from 'react-router-dom';
import { useBreakpointValue } from '@chakra-ui/react';
import ChatPageLayout from './ChatPageLayout';
import { offerSendOptions } from '../model/offerAcceptance';
import { useChatTransport, useProfileAndAuthFlow, useSidebarState, useChatSideEffects } from '../hooks';
import { useLayoutControls } from '@app/providers';
import { useChatInitialization } from '../hooks/orchestration/useChatInitialization';
import { useChatThreadRouting } from '../hooks/orchestration/useChatThreadRouting';
import { useChatDrawersState } from '../hooks/orchestration/useChatDrawersState';
import { useChatStreamingLifecycle } from '../hooks/orchestration/useChatStreamingLifecycle';
import { useChatWorkSurface } from '../hooks/orchestration/useChatWorkSurface';
import { CHAT_UI_CONFIG } from '../config/uiConfig';
import { useTraceSessions } from '../hooks/useTraceSessions';
import { useChatDomainState } from '../hooks/useChatDomainState';
import { useMessageActions } from '../hooks/useMessageActions';
import { useRecentThreads } from '../hooks/useRecentThreads';
import { useChatUiSettings } from '../hooks/useChatUiSettings';
import { useVoiceRecorder } from '../hooks/useVoiceRecorder';
import { useFileAttachment } from '../hooks/useFileAttachment';
import { useMemoryPanel } from '../hooks/useMemoryPanel';
import { useGraphPanel } from '../hooks/useGraphPanel';
import { useOnboardingProgress } from '../hooks/useOnboardingProgress';
import { useChatMessageSender } from '../hooks/orchestration/useChatMessageSender';
import { useChatMemoryActions } from '../hooks/orchestration/useChatMemoryActions';
import { useChatCapabilities } from '../hooks/orchestration/useChatCapabilities';
import { useChatHistoryLifecycle } from '../hooks/orchestration/useChatHistoryLifecycle';
import { useChatContextCompaction } from '../hooks/orchestration/useChatContextCompaction';
import ChatSidebarPanel from '../components/ChatSidebarPanel';
import ChatPageAuxiliaryLayers from '../components/ChatPageAuxiliaryLayers';
import ChatPageSurfaceShell from '../components/ChatPageSurfaceShell';
import { useCommandPalette } from '../hooks/useCommandPalette';
import { usePinnedThreads } from '../hooks/usePinnedThreads';
import ChatBackdrop from '../components/ChatBackdrop';
import useDocumentTitle from '@shared/hooks/useDocumentTitle';
import { useChatMessagePresentation } from '../hooks/orchestration/useChatMessagePresentation';
import { useChatThreadCommands } from '../hooks/orchestration/useChatThreadCommands';

/** Composes chat domain state; focused hooks and shells own feature lifecycles. */
function ChatPageContainer() {
  const { setVariant, setFooterVisible } = useLayoutControls();
  useEffect(() => {
    setVariant('full');
    setFooterVisible(false);
  }, [setVariant, setFooterVisible]);

  const location = useLocation();
  const { threadId: routeThreadId } = useParams();
  const init = useChatInitialization(routeThreadId);
  const { threadId, initialMessage, initialManualModel, initialInputType, initialWebSearch, initialDeepResearch, initialFileContext, selectedModelOverride } = init.state;
  const { setSelectedModelOverride, startFreshThread } = init.actions;
  const navigate = useNavigate();
  useChatThreadRouting({
    routeThreadId,
    initialMessage,
    threadId,
    search: location.search,
    navigate,
  });
  const sideEffects = useChatSideEffects({ navigate });

  const {
    isAuthenticated, user, logout, incrementRequests, remainingRequests, profileDisclosure, profileData, setProfileData, profileMemoryCount, setProfileMemoryCount, isProfileLoading, resolveSessionUserId, isAuthModalOpen, onAuthModalClose, showAuthModal, modalData, AuthModal, ensureGuestLimit,
  } = useProfileAndAuthFlow();

  const drawers = useChatDrawersState(profileDisclosure);
  const { sidebarDisclosure, memoryDisclosure, graphDisclosure, settingsDisclosure, memoryFacts, memoryDashboard } = drawers.state;
  const { setMemoryFacts, setMemoryDashboard } = drawers.actions;
  const commandPalette = useCommandPalette();
  const { pinnedIds, togglePin } = usePinnedThreads();
  const {
    activeSurface,
    workMounted,
    navigationPending,
    cancelSurfaceRef,
    changeSurface,
    openWorkSurface,
    setWorkspaceDirty,
    requestGuardedAction,
    registerWorkspaceLifecycle,
    cancelSurfaceChange,
    confirmSurfaceChange,
  } = useChatWorkSurface({ location, navigate });
  useDocumentTitle(activeSurface === 'work' ? 'Работа' : 'Чат');

  // Open profile drawer when navigated with ?profile=open — снимаем ТОЛЬКО query,
  // сохраняя текущий путь (тред /chat/:id не сбрасывается в новый чат).
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    if (params.get('profile') === 'open') {
      profileDisclosure.onOpen();
      params.delete('profile');
      const search = params.toString();
      navigate(`${location.pathname}${search ? `?${search}` : ''}`, { replace: true });
    }
  }, [location.search, location.pathname, navigate, profileDisclosure]);


  const [hasInitialized, setHasInitialized] = useState(false);
  const { state: domainState, actions: domainActions } = useChatDomainState();
  const { messages, loading: isLoading, error, currentJob } = domainState;
  const { setLoading: setIsLoading, setError, clearError, addMessage, clearMessages, clearThread, replaceMessages, loadHistory, setCurrentJob, clearCurrentJob } = domainActions;
  const [forcedRoute, setForcedRoute] = useState(null);
  const { availableModels, modelCatalog, personas, transcriptionConfig } = useChatCapabilities({
    selectedModel: selectedModelOverride,
    onInvalidModel: setSelectedModelOverride,
  });
  // Распознанный голос держим как аккуратное превью над композером (а не сырым
  // текстом в textarea); на отправке он подмешивается в сообщение.
  const [voiceText, setVoiceText] = useState('');
  const composerRef = useRef(null);

  const clearInput = useCallback(() => composerRef.current?.clearInput(), []);

  const { settings: chatUiSettings, setSettings: setChatUiSettings, resetUiSettings: resetPersistedUiSettings } = useChatUiSettings({ initialWebSearch, initialDeepResearch });
  const { multiIntentEnabled, planningEnabled, personaIds, memoryEnabled, ldrModel, ldrStrategy, showTracePanel, transcriptionMode, transcriptionModel } = chatUiSettings;
  // 🔴 Выводим из режима, а не храним: тоггл и режим резолвились в одну категорию, то
  // есть были двумя способами включить одно. Хранить флаг дальше нельзя — сохранённое
  // `true` осталось бы без органа управления и включало бы поиск на каждом сообщении.
  const webSearchEnabled = forcedRoute === 'web_search';
  const deepResearchEnabled = forcedRoute === 'deep_research';
  const messagesEndRef = useRef(null);
  const messagesScrollRef = useRef(null);
  const isCompactTrace = useBreakpointValue(CHAT_UI_CONFIG.trace.compactBreakpoint) ?? false;
  const {
    traceSessions,
    tracePanelsExpanded,
    setTracePanelsExpanded,
    traceSessionByAnchor,
    activeOrLatestTraceSession,
    liveTraceSession,
    startTraceSession,
    appendTraceEvent,
    updateTraceProgress,
    markConfirmationAccepted,
    finalizeTraceSession,
    resetTraceSessions,
    restoreSessions,
  } = useTraceSessions({ showTracePanel });
  const {
    loading: isHistoryLoading,
    error: historyError,
    reload: reloadHistory,
  } = useChatHistoryLifecycle({
    routeThreadId,
    initialMessage,
    isAuthenticated,
    showTracePanel,
    clearThread,
    loadHistory,
    restoreSessions,
  });
  const {
    recentThreads,
    setRecentThreads,
    deletingThreadId,
    upsertRecentThread,
    handleDeleteThread,
    isLoadingThreads,
    threadsError,
    reloadThreads,
  } = useRecentThreads({
    navigate,
    resolveSessionUserId,
    threadId,
    setMessages: replaceMessages,
    isAuthenticated,
    requestGuardedAction,
  });
  const { sidebarSearch, setSidebarSearch, isSidebarCollapsed, setIsSidebarCollapsed, filteredRecentThreads } = useSidebarState({ recentThreads });

  const { attachments, isUploading: isFileUploading, removeAttachment, clearAttachments, consumeUserDetached, fileInputRef, handleFileUpload } = useFileAttachment({ appendTraceEvent, sideEffects, transcriptionMode, transcriptionModel });
  const { isRecording, isTranscribing: isVoiceTranscribing, elapsedSec: recordElapsedSec, toggleRecording } = useVoiceRecorder({ onTranscript: (text) => setVoiceText(text), appendTraceEvent, sideEffects, transcriptionMode, transcriptionModel });


  // WebSocket carries only a bounded room invalidation.  The drawer re-fetches
  // all workspace content through REST and never accepts files/issues from it.
  const [workspaceInvalidationVersion, setWorkspaceInvalidationVersion] = useState(0);
  const handleWorkspaceInvalidated = useCallback(() => {
    setWorkspaceInvalidationVersion((version) => version + 1);
  }, []);
  const sendControlRef = useRef(null);
  const {
    compacting,
    compactedAfterId,
    compactedSummary,
    contextInfo,
    compact: handleCompactContext,
    onCompacted: handleContextCompacted,
  } = useChatContextCompaction({
    messages,
    isLoading,
    notify: sideEffects.notify,
    sendControlRef,
  });

  const streamingLifecycle = useChatStreamingLifecycle({
    isLoading,
    setIsLoading,
    setError,
    appendTraceEvent,
    updateTraceProgress,
    markConfirmationAccepted,
    finalizeTraceSession,
    addMessage,
    appendStreamChunk: domainActions.updateLastAgentChunk,
    completeLastAgentMessage: domainActions.completeLastAgentMessage,
    finalizeStreamWithContent: domainActions.finalizeStreamWithContent,
    setCurrentJob,
    clearCurrentJob,
    setInputValue: clearInput,
    onContextCompacted: handleContextCompacted,
    onWorkspaceInvalidated: handleWorkspaceInvalidated,
  });
  const { wsCallbacks } = streamingLifecycle.actions;

  const {
    connectionState,
    sendMessage: wsSendMessage,
    sendControl: wsSendControl,
    cancelJob,
    useWebSocket,
  } = useChatTransport({ threadId, callbacks: wsCallbacks });
  sendControlRef.current = wsSendControl;

  // 🔴 СТОП ГАСИТ ИНТЕРФЕЙС СРАЗУ, СЕТЬ — ПОТОМ. Прежний порядок ждал ответа ручки
  // отмены (потолок 30 с) и только в `finally` снимал спиннер: на мёртвом прогоне
  // кнопка выглядела не нажатой. Человек жмёт «стоп» именно тогда, когда исполнителя
  // может уже не быть, — и ждать подтверждения от него как раз нельзя.
  //
  // ⚠️ Трейс ЗАКРЫВАЕТСЯ здесь же. Без этого панель оставалась в «Готовлю ответ…»
  // навсегда: спиннер композера гасился, а сессия трейса никем не финализировалась —
  // ровно то, что видел владелец («стоп не останавливает»).
  const handleCancelJob = useCallback(async (celeryTaskId) => {
    setIsLoading(false);
    clearCurrentJob();
    appendTraceEvent({ kind: 'error', title: 'Остановлено пользователем', detail: 'Работа прервана кнопкой «стоп»' });
    finalizeTraceSession('error');
    try {
      await cancelJob(celeryTaskId);
    } catch {
      sideEffects.notify({
        title: 'Ошибка отмены',
        description: 'Не удалось отменить задачу. Попробуйте ещё раз.',
        status: 'warning',
        duration: 3000,
      });
    }
  }, [appendTraceEvent, cancelJob, clearCurrentJob, finalizeTraceSession, setIsLoading, sideEffects]);

  const {
    handleScroll: handleMessagesScroll,
    atBottom: isAtBottom,
    scrollToBottom: scrollMessagesToBottom,
    registerContentRef: registerMessagesContentRef,
    lastUsedModel,
    visibleMessages,
    providerStatus,
  } = useChatMessagePresentation({
    messages,
    isLoading,
    scrollRef: messagesScrollRef,
    showTracePanel,
    traceSessions,
    activeOrLatestTraceSession,
    setTracePanelsExpanded,
    threadId,
    isAuthenticated,
  });

  const handleSendMessageRef = useRef(null);
  const handleSendMessageStable = useCallback((...args) => handleSendMessageRef.current?.(...args), []);
  const { copyMessage, regenerateMessage, editMessage } = useMessageActions({ messages, replaceMessages, handleSendMessageRef });

  const { handleSendMessage } = useChatMessageSender({
    addMessage,
    appendTraceEvent,
    attachments,
    isFileUploading: isFileUploading || isRecording || isVoiceTranscribing,
    voiceText,
    onVoiceConsumed: () => setVoiceText(''),
    clearError,
    clearAttachments,
    consumeUserDetached,
    forcedRoute,
    composerRef,
    connectionState,
    deepResearchEnabled,
    ensureGuestLimit,
    finalizeTraceSession,
    incrementRequests,
    initialFileContext,
    initialInputType,
    initialManualModel,
    isAuthenticated,
    resolveSessionUserId,
    selectedModelOverride,
    setError,
    setIsLoading,
    setSidebarSearch,
    showAuthModal,
    sideEffects,
    startTraceSession,
    threadId,
    upsertRecentThread,
    useWebSocket,
    webSearchEnabled,
    multiIntentEnabled,
    planningEnabled,
    personaIds,
    memoryEnabled,
    ldrModel,
    ldrStrategy,
    wsSendMessage,
  });

  useEffect(() => {
    handleSendMessageRef.current = handleSendMessage;
  }, [handleSendMessage]);

  useEffect(() => {
    if (!initialMessage || !threadId || hasInitialized || connectionState === 'connecting') {
      return;
    }

    handleSendMessage(initialMessage);
    sideEffects.goToThread(threadId, { replace: true });
    setHasInitialized(true);
  }, [
    connectionState,
    handleSendMessage,
    hasInitialized,
    initialMessage,
    sideEffects,
    threadId,
  ]);

  const openMemoryPanel = useMemoryPanel({
    isAuthenticated,
    memoryDisclosure,
    resolveSessionUserId,
    setMemoryFacts,
    setMemoryDashboard,
    setProfileMemoryCount,
    showAuthModal,
    sideEffects,
  });

  const { openGraphPanel, loadGraphSummary, searchGraphHandler, deleteGraphHandler, openGraphHtmlHandler } = useGraphPanel({
    isAuthenticated,
    graphDisclosure,
    showAuthModal,
    sideEffects,
  });

  const {
    searchMemoryFacts,
    addMemoryFact: addMemoryFactHandler,
    deleteMemoryFact: deleteMemoryFactHandler,
    clearAllMemory: clearAllMemoryHandler,
  } = useChatMemoryActions({
    resolveSessionUserId,
    setMemoryFacts,
    setMemoryDashboard,
    setProfileMemoryCount,
    notify: sideEffects.notify,
  });

  // Решение «режимом или инструментом» живёт в `model/offerAcceptance` — там его есть чем
  // проверить, а внутри контейнера мутация «слать всё маршрутом» оставалась зелёной.
  const runOfferedMode = useCallback((offer, prompt, anchorMessageId, traceSessionId) => {
    const mode = offer?.mode;
    const text = String(prompt || '').trim();
    if (!mode) return;
    const options = {
      ...offerSendOptions(offer),
      anchorMessageId,
      traceSessionId,
    };
    if (options.confirmOfferId) {
      handleSendMessageRef.current?.('', options);
      return;
    }
    if (text) handleSendMessageRef.current?.(text, options);
  }, []);

  const resetUiSettings = useCallback(() => {
    resetPersistedUiSettings();
    sideEffects.notify({
      title: 'Настройки сброшены',
      status: 'success',
      duration: 1600,
    });
  }, [resetPersistedUiSettings, sideEffects]);

  // ⚠️ Взаимного гашения с веб-поиском/ресёрчем больше нет: те стали ЗНАЧЕНИЯМИ режима,
  // а стратегии видны только в «Авто», где ни один из них не выбран. Гасить нечего.
  const onToggleMultiIntent = useCallback(() => setChatUiSettings(
    (p) => ({ ...p, multiIntentEnabled: !p.multiIntentEnabled }),
  ), [setChatUiSettings]);
  // Планирование — вторая стратегия «Авто», рядом с мульти-интентом. Выключенное
  // состояние это АВТО, а не «никогда»: план строится сам на сложных задачах. Включение
  // означает «строй всегда» и заодно экономит вызов-оценку сложности.
  // Взаимоисключения с мульти-интентом нет и здесь: при декомпозиции план не строится
  // (гейт `not subtasks` в `processor_steps`), то есть конфликт разрешён на бэкенде.
  const onTogglePlanning = useCallback(() => setChatUiSettings(
    (p) => ({ ...p, planningEnabled: !p.planningEnabled }),
  ), [setChatUiSettings]);
  // Личности — не тоггл, а набор: селектор сам следит за потолком и отдаёт готовый
  // список. Здесь только сохраняем (он поедет с каждым сообщением).
  const onPersonaIdsChange = useCallback(
    (ids) => setChatUiSettings((p) => ({ ...p, personaIds: Array.isArray(ids) ? ids : [] })),
    [setChatUiSettings],
  );
  const handleTraceToggle = useCallback(
    (id, expanded) => setTracePanelsExpanded((prev) => ({ ...prev, [id]: expanded })),
    [setTracePanelsExpanded],
  );

  // Онбординг-прогресс (лёгкая геймификация) — отмечаем РЕАЛЬНЫЕ действия.
  const onboarding = useOnboardingProgress(resolveSessionUserId?.() || null);
  const { markDone: markOnboarding } = onboarding;
  useEffect(() => {
    if (messages.length > 0) markOnboarding('first_message');
  }, [messages.length, markOnboarding]);
  useEffect(() => {
    if (webSearchEnabled) markOnboarding('web_search');
  }, [webSearchEnabled, markOnboarding]);
  useEffect(() => {
    if ((profileMemoryCount || 0) > 0 || memoryFacts.length > 0) markOnboarding('memory');
  }, [profileMemoryCount, memoryFacts.length, markOnboarding]);

  const {
    startNewChat,
    activeThreadTitle,
    handleFeedback,
    handleRenameThread,
    handleNavigateThread,
    handleNavigateThreadAndClose,
    handleNewChatAndClose,
    handleToggleSidebar,
    handleStopStreaming,
    handleDiscardVoice,
    handleEditVoice,
    paletteActions,
  } = useChatThreadCommands({
    threadId,
    messages,
    visibleMessages,
    recentThreads,
    setRecentThreads,
    currentJob,
    voiceText,
    setVoiceText,
    composerRef,
    navigate,
    startFreshThread,
    clearMessages,
    clearAttachments,
    clearError,
    resetTraceSessions,
    setTracePanelsExpanded,
    sidebarSearchActions: { setSidebarSearch, setIsSidebarCollapsed },
    sidebarDisclosure,
    sideEffects,
    handleCancelJob,
    settingsDisclosure,
    openMemoryPanel,
    setSelectedModelOverride,
    requestGuardedAction,
  });

  // Единый рендер сайдбара для десктопа и мобильного Drawer — устраняет дубль
  // и дрейф списка пропсов (closeAfter закрывает Drawer после навигации/нового чата).
  const renderSidebar = (collapsed, closeAfter, inDrawer = false) => (
    <ChatSidebarPanel
      isSidebarCollapsed={collapsed}
      inDrawer={inDrawer}
      filteredRecentThreads={filteredRecentThreads}
      isLoadingThreads={isLoadingThreads}
      threadsError={threadsError}
      onRetryThreads={reloadThreads}
      threadId={threadId}
      sidebarSearch={sidebarSearch}
      setSidebarSearch={setSidebarSearch}
      deletingThreadId={deletingThreadId}
      handleDeleteThread={handleDeleteThread}
      onNavigateThread={closeAfter ? handleNavigateThreadAndClose : handleNavigateThread}
      onRenameThread={handleRenameThread}
      pinnedIds={pinnedIds}
      onTogglePin={togglePin}
      onNewChat={closeAfter ? handleNewChatAndClose : startNewChat}
      onOpenMemory={openMemoryPanel}
      onOpenGraph={openGraphPanel}
      onOpenSettings={settingsDisclosure.onOpen}
    />
  );

  return (
    <ChatPageLayout>
      <ChatBackdrop />
      <ChatPageSurfaceShell
        sidebar={{ render: renderSidebar, collapsed: isSidebarCollapsed }}
        header={{
          onOpenMobileSidebar: sidebarDisclosure.onOpen,
          onToggleSidebar: handleToggleSidebar,
          threadTitle: activeThreadTitle,
          connectionState,
          onOpenSettings: settingsDisclosure.onOpen,
          surface: activeSurface,
          onSurfaceChange: changeSurface,
        }}
        work={{
          mounted: workMounted,
          active: activeSurface === 'work',
          props: {
            threadId,
            invalidationVersion: workspaceInvalidationVersion,
            notify: sideEffects.notify,
            onCancelRun: () => handleCancelJob(currentJob?.celeryTaskId),
            onDirtyChange: setWorkspaceDirty,
            onRequestNavigation: requestGuardedAction,
            onRegisterDraftLifecycle: registerWorkspaceLifecycle,
          },
        }}
        chat={{
          composerRef,
          messages: {
            scrollRef: messagesScrollRef,
            endRef: messagesEndRef,
            handleScroll: handleMessagesScroll,
            atBottom: isAtBottom,
            scrollToBottom: scrollMessagesToBottom,
            registerContentRef: registerMessagesContentRef,
            error,
            providerStatus,
            connectionState,
            visibleMessages,
            isHistoryLoading,
            historyError,
            onRetryHistory: reloadHistory,
            lastUsedModel,
            availableModels,
            copyMessage,
            regenerateMessage,
            editMessage,
            onFeedback: isAuthenticated ? handleFeedback : undefined,
            onRunMode: runOfferedMode,
            isLoading,
            compactedAfterId,
            compactedSummary,
            showTracePanel,
            traceSessionByAnchor,
            tracePanelsExpanded,
            isCompactTrace,
            onTraceToggle: handleTraceToggle,
            currentJob,
            activeTraceSession: liveTraceSession,
            onCancelJob: handleCancelJob,
            personas,
            personaIds,
            onPersonaIdsChange,
            onboarding,
            onOpenWork: openWorkSurface,
          },
          composer: {
            onSubmit: handleSendMessageStable,
            onStop: handleStopStreaming,
            isStreaming: isLoading,
            disabled: isLoading || compacting,
            multiIntentEnabled,
            planningEnabled,
            onToggleMultiIntent,
            onTogglePlanning,
            personas,
            personaIds,
            onPersonaIdsChange,
            forcedRoute,
            onForcedRouteChange: setForcedRoute,
            selectedModel: selectedModelOverride,
            availableModels,
            modelCatalog,
            onModelChange: setSelectedModelOverride,
            contextInfo,
            onCompactContext: handleCompactContext,
            compacting,
            isAuthenticated,
            remainingRequests,
            attachments,
            onRemoveAttachment: removeAttachment,
            onFileUpload: handleFileUpload,
            onOpenWork: openWorkSurface,
            isFileUploading,
            onVoiceToggle: toggleRecording,
            isRecording,
            isVoiceTranscribing,
            recordElapsedSec,
            voiceText,
            onDiscardVoice: handleDiscardVoice,
            onEditVoice: handleEditVoice,
            fileInputRef,
          },
        }}
      />

      {/* Мобильный сайдбар — единственный дровер, который не использовал общий
          анти-jank пресет @theme/drawer: голый оверлей + полупрозрачный (0.72) фон
          панели заставляли композитить прозрачность поверх страницы на каждом кадре
          слайда. Тёмный скрим + почти непрозрачный фон дают тот же вид без этого. */}
      <ChatPageAuxiliaryLayers
        sidebar={{ disclosure: sidebarDisclosure, render: renderSidebar }}
        palette={{
          state: commandPalette,
          recentThreads,
          models: availableModels,
          actions: paletteActions,
        }}
        auth={{
          Component: AuthModal,
          isOpen: isAuthModalOpen,
          onClose: onAuthModalClose,
          modalData,
        }}
        surface={{
          pending: navigationPending,
          cancelRef: cancelSurfaceRef,
          onCancel: cancelSurfaceChange,
          onConfirm: confirmSurfaceChange,
        }}
        memory={{
          disclosure: memoryDisclosure,
          facts: memoryFacts,
          dashboard: memoryDashboard,
          onSearch: searchMemoryFacts,
          onDeleteFact: deleteMemoryFactHandler,
          onAddFact: addMemoryFactHandler,
          onClearAll: clearAllMemoryHandler,
        }}
        graph={{
          disclosure: graphDisclosure,
          loadSummary: loadGraphSummary,
          onSearch: searchGraphHandler,
          onDelete: deleteGraphHandler,
          onOpenHtml: openGraphHtmlHandler,
        }}
        settings={{
          disclosure: settingsDisclosure,
          props: {
            showTracePanel,
            multiIntentEnabled,
            planningEnabled,
            memoryEnabled,
            ldrModel,
            ldrStrategy,
            modelCatalog,
            transcriptionConfig,
            transcriptionMode,
            transcriptionModel,
            setChatUiSettings,
            onReset: resetUiSettings,
          },
        }}
        profile={{
          disclosure: profileDisclosure,
          props: {
            profileData,
            setProfileData,
            profileMemoryCount,
            isLoading: isProfileLoading,
            user,
            threadCount: recentThreads.length,
            memoryFallbackCount: memoryFacts.length,
            availableModels,
            modelCatalog,
            preferredModel: chatUiSettings.preferredModel,
            onPreferredModelChange: (id) => setChatUiSettings(
              (previous) => ({ ...previous, preferredModel: id }),
            ),
            onOpenSettings: settingsDisclosure.onOpen,
            onLogout: logout,
          },
        }}
      />
    </ChatPageLayout>
  );
}

export default ChatPageContainer;
