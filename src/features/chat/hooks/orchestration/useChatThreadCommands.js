import { useCallback, useMemo } from 'react';
import { exportConversationMarkdown } from '../../utils/exportThread';

export function useChatThreadCommands({
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
  sidebarSearchActions,
  sidebarDisclosure,
  sideEffects,
  handleCancelJob,
  settingsDisclosure,
  openMemoryPanel,
  setSelectedModelOverride,
  requestGuardedAction,
}) {
  const { setSidebarSearch, setIsSidebarCollapsed } = sidebarSearchActions;
  const createNewChat = useCallback(() => {
    clearMessages();
    composerRef.current?.clearInput();
    setSidebarSearch('');
    clearAttachments();
    clearError();
    resetTraceSessions();
    setTracePanelsExpanded({});
    navigate(`/chat/${startFreshThread()}`);
  }, [
    clearAttachments,
    clearError,
    clearMessages,
    composerRef,
    navigate,
    resetTraceSessions,
    setSidebarSearch,
    setTracePanelsExpanded,
    startFreshThread,
  ]);
  const startNewChat = useCallback(() => {
    if (requestGuardedAction) {
      requestGuardedAction(createNewChat);
      return;
    }
    createNewChat();
  }, [createNewChat, requestGuardedAction]);

  const activeThreadTitle = useMemo(() => {
    if (!threadId) return '';
    const match = (recentThreads || [])
      .find((thread) => (thread?.thread_id || thread?.id || thread) === threadId);
    let title = match?.title || match?.name || '';
    title = typeof title === 'string' ? title.trim() : '';
    if (!title || title.toLowerCase() === 'chat') {
      const firstUser = messages.find((message) => (
        message?.type === 'user' && message?.content
      ));
      if (firstUser) title = String(firstUser.content).replace(/\n/g, ' ').slice(0, 80);
    }
    return title;
  }, [messages, recentThreads, threadId]);

  const exportConversation = useCallback(() => {
    const count = exportConversationMarkdown(visibleMessages, activeThreadTitle || 'Чат');
    if (count === 0) {
      sideEffects.notify({
        title: 'Нечего экспортировать',
        description: 'В этом чате пока нет сообщений.',
        status: 'info',
        duration: 2000,
      });
    }
  }, [activeThreadTitle, sideEffects, visibleMessages]);

  const handleFeedback = useCallback(async (contentKey, rating) => {
    if (!threadId || !contentKey) return;
    try {
      const { sendMessageFeedback } = await import('@api/chat');
      await sendMessageFeedback(threadId, contentKey, rating);
    } catch {
      // Feedback is non-critical and remains fail-open.
    }
  }, [threadId]);

  const handleRenameThread = useCallback(async (targetThreadId, title) => {
    const clean = (title || '').trim();
    if (!clean) return;
    setRecentThreads((previous) => previous.map((thread) => (
      typeof thread === 'object' && (thread?.thread_id || thread?.id) === targetThreadId
        ? { ...thread, title: clean }
        : thread
    )));
    try {
      const { renameChatThread } = await import('@api/chat');
      await renameChatThread(targetThreadId, clean);
    } catch {
      sideEffects.notify({
        title: 'Не удалось переименовать чат',
        status: 'warning',
        duration: 2500,
      });
    }
  }, [setRecentThreads, sideEffects]);

  const closeSidebar = sidebarDisclosure.onClose;
  const handleNavigateThread = useCallback(
    (targetThreadId) => sideEffects.goToThread(targetThreadId),
    [sideEffects],
  );
  const handleNavigateThreadAndClose = useCallback((targetThreadId) => {
    sideEffects.goToThread(targetThreadId);
    closeSidebar();
  }, [closeSidebar, sideEffects]);
  const handleNewChatAndClose = useCallback(() => {
    startNewChat();
    closeSidebar();
  }, [closeSidebar, startNewChat]);
  const handleToggleSidebar = useCallback(
    () => setIsSidebarCollapsed((previous) => !previous),
    [setIsSidebarCollapsed],
  );
  const handleStopStreaming = useCallback(
    () => handleCancelJob(currentJob?.celeryTaskId),
    [currentJob, handleCancelJob],
  );
  const handleDiscardVoice = useCallback(() => setVoiceText(''), [setVoiceText]);
  const handleEditVoice = useCallback(() => {
    composerRef.current?.appendInputValue(voiceText);
    setVoiceText('');
  }, [composerRef, setVoiceText, voiceText]);
  const paletteActions = useMemo(() => ({
    newChat: startNewChat,
    openSettings: settingsDisclosure.onOpen,
    openMemory: openMemoryPanel,
    selectModel: setSelectedModelOverride,
    goToThread: sideEffects.goToThread,
    exportChat: exportConversation,
  }), [
    exportConversation,
    openMemoryPanel,
    setSelectedModelOverride,
    settingsDisclosure.onOpen,
    sideEffects,
    startNewChat,
  ]);

  return {
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
  };
}
