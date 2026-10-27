import React, { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState } from 'react';
import { Box, HStack, Text } from '@chakra-ui/react';
import { FiPaperclip } from '@shared/icons';
import { colors } from '@theme/tokens';
import { CHAT_FONT_FAMILY, CHAT_THEME } from '../../constants/theme';
import { COMPOSER_MAX_HEIGHT_PX, COMPOSER_MIN_HEIGHT_PX } from '../../constants/limits';
import ComposerShell from './ComposerShell';
import ComposerVoicePreview from './ComposerVoicePreview';
import ComposerVoiceControl from './ComposerVoiceControl';
import ComposerSubmitControl from './ComposerSubmitControl';
import ComposerActionControl from './ComposerActionControl';
import ComposerAttachments from './ComposerAttachments';
import ComposerModeSelector from './ComposerModeSelector';
import ComposerPersonaSelector from './ComposerPersonaSelector';
import ContextGauge from './ContextGauge';
import ModelSelector from '../ModelSelector';
import ProviderAvailability from '../ProviderAvailability';
import { ChoicePanelGroup } from '@shared/controls/ChoicePanel';
import { MAX_ATTACHMENTS } from '../../hooks/useFileAttachment';
import { useResponsive } from '@hooks/useResponsive';
import { observeResizeFrame } from '@shared/utils/observeResizeFrame';

const IRIS = colors.iris[300]; // активный акцент-текст (было #9FB0FF литералом)

// Isolated, uncontrolled composer — typing never re-renders ChatPageContainer
const ChatComposerPanel = forwardRef(function ChatComposerPanel(
  {
    onSubmit,
    onStop,
    isStreaming,
    disabled,
    multiIntentEnabled,
    onToggleMultiIntent,
    planningEnabled,
    onTogglePlanning,
    personas = [],
    personaIds = [],
    onPersonaIdsChange,
    forcedRoute,
    onForcedRouteChange,
    selectedModel,
    availableModels,
    modelCatalog,
    modelStatus = 'ready',
    onRetryModels,
    onModelChange,
    contextInfo,
    onCompactContext,
    compacting,
    isAuthenticated,
    remainingRequests,
    attachments,
    onRemoveAttachment,
    onFileUpload,
    onOpenLibrary,
    isFileUploading,
    onVoiceToggle,
    isRecording,
    isRequestingPermission,
    isVoiceTranscribing,
    recordElapsedSec,
    voiceText,
    onDiscardVoice,
    onEditVoice,
    fileInputRef,
    documentMode = false,
    workbenchMode = false,
    visible = true,
    hintPaused = false,
  },
  ref,
) {
  // Есть распознанное голосовое, ожидающее отправки (превью над вводом) — тогда
  // Send активен даже при пустом textarea (голос подмешается в сообщение).
  const hasPendingVoice = !!(voiceText && voiceText.trim());
  const { isMobile } = useResponsive();
  const inputRef = useRef(null);
  const [height, setHeight] = useState(COMPOSER_MIN_HEIGHT_PX);
  const [hasText, setHasText] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const containerRef = useRef(null);
  const [compactControls, setCompactControls] = useState(false);
  const refreshLayout = useCallback(() => {
    const element = containerRef.current;
    if (!element || !element.getClientRects().length) return;
    const style = getComputedStyle(element);
    const width = element.clientWidth - parseFloat(style.paddingLeft || 0) - parseFloat(style.paddingRight || 0);
    if (width > 0) setCompactControls(width < 600);
  }, []);
  useLayoutEffect(() => { if (visible) refreshLayout(); }, [visible, refreshLayout]);
  useEffect(() => {
    const element = containerRef.current;
    if (!element || typeof ResizeObserver === 'undefined') return undefined;
    // Read the current host, not an entry queued before a peer-surface move.
    return observeResizeFrame(element, refreshLayout);
  }, [refreshLayout]);
  const unavailableModel = modelStatus === 'ready' && selectedModel && Array.isArray(availableModels)
    && !availableModels.includes(selectedModel);
  const frameRef = useRef(0);
  const onSubmitRef = useRef(onSubmit);
  onSubmitRef.current = onSubmit;
  const onStopRef = useRef(onStop);
  onStopRef.current = onStop;

  useImperativeHandle(ref, () => ({
    refreshLayout,
    clearInput() {
      if (inputRef.current) {
        inputRef.current.value = '';
        setHasText(false);
        recalcHeight();
      }
    },
    setInputValue(val) {
      if (inputRef.current) {
        inputRef.current.value = val;
        setHasText(!!val.trim());
        recalcHeight();
        inputRef.current.focus();
      }
    },
    // Дописать текст к текущему вводу (для голосового → композер: транскрипт
    // становится текстом сообщения, а не вложением).
    appendInputValue(val) {
      if (inputRef.current && val) {
        const cur = inputRef.current.value || '';
        const sep = cur && !/\s$/.test(cur) ? ' ' : '';
        inputRef.current.value = cur + sep + val;
        setHasText(!!inputRef.current.value.trim());
        recalcHeight();
        inputRef.current.focus();
      }
    },
    focus() {
      inputRef.current?.focus();
    },
    getInputValue() {
      return inputRef.current?.value || '';
    },
  }));

  useEffect(() => () => { if (frameRef.current) cancelAnimationFrame(frameRef.current); }, []);

  // Esc останавливает генерацию, даже если textarea disabled (фокус недоступен) —
  // слушаем на уровне окна только пока идёт стрим.
  useEffect(() => {
    if (!isStreaming) return undefined;
    const onKey = (e) => { if (e.key === 'Escape' && !e.defaultPrevented && !pickerOpen) onStopRef.current?.(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isStreaming, pickerOpen]);

  const recalcHeight = useCallback(() => {
    if (frameRef.current) cancelAnimationFrame(frameRef.current);
    frameRef.current = requestAnimationFrame(() => {
      const el = inputRef.current;
      if (!el) return;
      el.style.height = 'auto';
      const next = Math.min(COMPOSER_MAX_HEIGHT_PX, Math.max(COMPOSER_MIN_HEIGHT_PX, el.scrollHeight));
      setHeight((prev) => (prev === next ? prev : next));
      el.style.height = `${next}px`;
    });
  }, []);

  const handleInput = useCallback((e) => {
    setHasText(!!e.target.value.trim());
    recalcHeight();
  }, [recalcHeight]);

  const handleSubmit = useCallback(() => {
    // Файл ещё загружается — не отправляем (иначе file_context уйдёт пустым);
    // отправка разблокируется, как только загрузка завершится.
    if (disabled || isFileUploading || unavailableModel) return;
    const val = inputRef.current?.value.trim() ?? '';
    // Разрешаем отправку с пустым полем, если есть распознанное голосовое в
    // превью — оно подмешается в сообщение на стороне отправителя.
    if (!val && !hasPendingVoice) return;
    onSubmitRef.current(val);
  }, [disabled, isFileUploading, hasPendingVoice, unavailableModel]);

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent?.isComposing && e.keyCode !== 229) {
      e.preventDefault();
      handleSubmit();
    }
  }, [handleSubmit]);

  const canSend = (hasText || hasPendingVoice) && !disabled && !isFileUploading && !unavailableModel;
  // Parent loading covers admission/dispatch as well as streaming; IDE preparation
  // disables the same composer before its asynchronous repository check begins.
  const inputReady = visible && !isStreaming && !disabled && !isFileUploading && !unavailableModel;

  return (
    <Box ref={containerRef} data-composer-container data-toast-protected-actions flexShrink={0}
      px={workbenchMode ? 3 : { base: 3, md: 6, lg: 8 }} pt={3} pb={{ base: 'calc(12px + var(--app-safe-bottom, 0px))', md: 'calc(8px + var(--app-safe-bottom, 0px))' }}
      borderTop={`1px solid ${CHAT_THEME.panelBorder}`}
      bg={CHAT_THEME.inputStickyBg} backdropFilter="blur(22px)">
      <Box maxW="960px" mx="auto">
        {/* Превью распознанного голоса — в той же колонке, что и ввод: выровнено
            идеально при любом сайдбаре (раньше жило в контейнере и разъезжалось). */}
        <ComposerVoicePreview text={voiceText} onDiscard={onDiscardVoice} onEdit={onEditVoice} />
        {/* Прикреплённые файлы — НАД полем ввода (рядом с голосовым превью), а не
            между вводом и кнопками режимов (там было тесно и неопрятно). */}
        <ComposerAttachments attachments={attachments} onRemove={onRemoveAttachment} onOpenLibrary={onOpenLibrary} />
        <ComposerShell ready={inputReady && !hintPaused && !pickerOpen && !isRecording && !isRequestingPermission && !isVoiceTranscribing && !compacting}>
          {/* multiple: до 8 файлов за раз. Форматы расширены — сайдкары научились
              читать таблицы (xlsx/ods), презентации (pptx) и архивы с кодом (zip →
              карта репозитория). */}
          <input type="file" multiple ref={fileInputRef} style={{ display: 'none' }}
            // 🔴 КОДОВЫЕ РАСШИРЕНИЯ ОБЯЗАНЫ БЫТЬ ЗДЕСЬ. Backend их давно умеет
            // (`upload_file_use_case._CODE_EXTENSIONS` → `file_type="code"`), а выбрать
            // такой файл было НЕЧЕМ: в списке стояли документы, таблицы, картинки, аудио
            // и `.zip`. Способность есть, двери к ней нет — жалоба «.py вообще нельзя
            // прикрепить». Соответствие двух списков сверяет
            // `scripts/check_attachment_types.py` суперпроекта.
            accept=".txt,.md,.pdf,.doc,.docx,.odt,.rtf,.xls,.xlsx,.ods,.ppt,.pptx,.odp,.csv,.json,.zip,.png,.jpg,.jpeg,.gif,.webp,.mp3,.wav,.ogg,.m4a,.webm,.py,.js,.jsx,.ts,.tsx,.java,.go,.rs,.cpp,.cc,.c,.h,.hpp,.cs,.rb,.php,.sql,.sh,.bash,.kt,.swift,.scala,.yaml,.yml,.toml,.ini"
            onChange={onFileUpload} />

          <ComposerActionControl aria-label="Прикрепить файл" icon={FiPaperclip}
            position="absolute" left={{ base: 1.5, md: 2.5 }} top="6px" zIndex={2}
            isLoading={isFileUploading}
            isDisabled={(attachments?.length || 0) >= MAX_ATTACHMENTS}
            title={
              (attachments?.length || 0) >= MAX_ATTACHMENTS
                ? `Максимум ${MAX_ATTACHMENTS} файлов`
                : 'Прикрепить файл'
            }
            color={attachments?.length ? IRIS : CHAT_THEME.textTertiary}
            onClick={() => fileInputRef.current?.click()} />

          <Box
            as="textarea"
            rows={1}
            aria-label="Сообщение"
            ref={inputRef}
            onInput={handleInput}
            onKeyDown={handleKeyDown}
            onFocus={(event) => event.currentTarget.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })}
            placeholder={isMobile || compactControls ? 'Сообщение…' : 'Напишите сообщение...'}
            disabled={disabled}
            style={{ height: `${height}px` }}
            sx={{
              minH: `${COMPOSER_MIN_HEIGHT_PX}px`,
              maxH: `${COMPOSER_MAX_HEIGHT_PX}px`,
              overflowY: height >= COMPOSER_MAX_HEIGHT_PX ? 'auto' : 'hidden',
              resize: 'none',
              width: '100%',
              display: 'block',
              color: CHAT_THEME.textPrimary,
              fontSize: '15px',
              fontWeight: '450',
              fontFamily: CHAT_FONT_FAMILY,
              lineHeight: '1.6',
              outline: 'none',
              border: 'none',
              background: 'transparent',
              paddingLeft: isMobile || compactControls ? '48px' : '64px',
              paddingRight: isMobile || compactControls ? '96px' : '116px',
              paddingTop: '15px',
              paddingBottom: '15px',
              boxSizing: 'border-box',
              '&::placeholder': { color: CHAT_THEME.textTertiary },
              '&:disabled': { opacity: 0.6, cursor: 'not-allowed' },
            }}
          />

          <HStack position="absolute" right={{ base: 1.5, md: 2.5 }} bottom="6px" spacing={1} zIndex={2} align="center">
            <ComposerVoiceControl recordingState={isRequestingPermission ? 'requesting' : isRecording ? 'recording' : 'idle'} isTranscribing={isVoiceTranscribing} elapsedSec={recordElapsedSec} onToggle={onVoiceToggle} />
            <ComposerSubmitControl streaming={isStreaming} canSend={canSend} uploading={isFileUploading}
              onSend={handleSubmit} onStop={() => onStopRef.current?.()} />
          </HStack>
        </ComposerShell>

        <ChoicePanelGroup onOpenChange={setPickerOpen} compact={compactControls} enabled={visible}>
          <Box data-composer-settings role="group" aria-label="Настройки сообщения" display="flex"
            mt="4px" gap={compactControls ? '6px' : { base: 1.5, md: 2.5 }} justifyContent={compactControls ? 'center' : { base: 'center', md: 'flex-start' }}
            flexWrap="nowrap" alignItems="center" minW={0}>
              <Box flex="0 0 auto" minW={0}>
                <ComposerModeSelector value={forcedRoute} onChange={onForcedRouteChange} mobileIconOnly documentMode={documentMode}
                  multiIntentEnabled={multiIntentEnabled} onToggleMultiIntent={onToggleMultiIntent}
                  planningEnabled={planningEnabled} onTogglePlanning={onTogglePlanning} />
              </Box>
              {/* Третья ось выбора: режим — ЧТО делать, модель — ЧЕМ думать, личность — КАК
                  думать. Оси ортогональны, поэтому селектор отдельный и виден в любом режиме. */}
              {personas.length > 0 && <Box flex={{ base: '0 0 auto', md: '0 1 auto' }} minW={0}>
                <ComposerPersonaSelector personas={personas} value={personaIds} onChange={onPersonaIdsChange} mobileIconOnly />
              </Box>}
              <Box minW={0} flex="0 1 auto" display="flex" maxW="100%" marginInlineStart={compactControls ? 0 : { base: 0, md: 'auto' }}>
                <ModelSelector
                  mobileIconOnly
                  selectedModel={selectedModel}
                  availableModels={availableModels}
                  catalog={modelCatalog}
                  modelStatus={modelStatus}
                  onRetry={onRetryModels}
                  onChange={onModelChange}
                />
              </Box>
              {contextInfo?.hasWindow && (
                <Box data-composer-context flex="0 0 auto" display="flex" alignItems="center">
                  <ContextGauge
                    compact={compactControls}
                    pct={contextInfo.pct}
                    tokens={contextInfo.tokens}
                    windowTokens={contextInfo.windowTokens}
                    modelWindow={contextInfo.modelWindow}
                    bySection={contextInfo.bySection}
                    threshold={contextInfo.threshold}
                    onCompact={onCompactContext}
                    busy={compacting}
                  />
                </Box>
              )}
              {isMobile && <ProviderAvailability compact />}
              {!isAuthenticated && (
                <Text fontSize="12px" color={CHAT_THEME.textTertiary} whiteSpace="nowrap">
                  {remainingRequests} запросов
                </Text>
              )}
          </Box>
        </ChoicePanelGroup>
        {unavailableModel && <Text fontSize="12px" color={colors.warning} mt={2}>Выбранная модель недоступна. Выберите другую или Авто, чтобы отправить сообщение.</Text>}
      </Box>
    </Box>
  );
});

export default React.memo(ChatComposerPanel);
