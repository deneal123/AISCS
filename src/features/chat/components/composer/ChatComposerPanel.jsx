import React, { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { Box, HStack, IconButton, Text } from '@chakra-ui/react';
import { FiPaperclip, FiSend } from '@shared/icons';
import { colors, borderRadius, motion, shadows } from '@theme/tokens';
import { CHAT_FONT_FAMILY, CHAT_THEME } from '../../constants/theme';
import { COMPOSER_MAX_HEIGHT_PX, COMPOSER_MIN_HEIGHT_PX } from '../../constants/limits';
import ComposerShell from './ComposerShell';
import ComposerVoicePreview from './ComposerVoicePreview';
import ComposerVoiceControl from './ComposerVoiceControl';
import ComposerAttachments from './ComposerAttachments';
import ComposerModeSelector from './ComposerModeSelector';
import ComposerPersonaSelector from './ComposerPersonaSelector';
import ContextGauge from './ContextGauge';
import ModelSelector from '../ModelSelector';
import { MAX_ATTACHMENTS } from '../../hooks/useFileAttachment';

const IRIS = colors.iris[300]; // активный акцент-текст (было #9FB0FF литералом)
const EASE = motion.easeOut;

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
    onModelChange,
    contextInfo,
    onCompactContext,
    compacting,
    isAuthenticated,
    remainingRequests,
    attachments,
    onRemoveAttachment,
    onFileUpload,
    onOpenWork,
    isFileUploading,
    onVoiceToggle,
    isRecording,
    isVoiceTranscribing,
    recordElapsedSec,
    voiceText,
    onDiscardVoice,
    onEditVoice,
    fileInputRef,
  },
  ref,
) {
  // Есть распознанное голосовое, ожидающее отправки (превью над вводом) — тогда
  // Send активен даже при пустом textarea (голос подмешается в сообщение).
  const hasPendingVoice = !!(voiceText && voiceText.trim());
  const inputRef = useRef(null);
  const [height, setHeight] = useState(COMPOSER_MIN_HEIGHT_PX);
  const [hasText, setHasText] = useState(false);
  const frameRef = useRef(0);
  const onSubmitRef = useRef(onSubmit);
  onSubmitRef.current = onSubmit;
  const onStopRef = useRef(onStop);
  onStopRef.current = onStop;

  useImperativeHandle(ref, () => ({
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
    const onKey = (e) => { if (e.key === 'Escape') onStopRef.current?.(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isStreaming]);

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
    if (disabled || isFileUploading) return;
    const val = inputRef.current?.value.trim() ?? '';
    // Разрешаем отправку с пустым полем, если есть распознанное голосовое в
    // превью — оно подмешается в сообщение на стороне отправителя.
    if (!val && !hasPendingVoice) return;
    onSubmitRef.current(val);
  }, [disabled, isFileUploading, hasPendingVoice]);

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }, [handleSubmit]);

  const canSend = (hasText || hasPendingVoice) && !disabled && !isFileUploading;

  return (
    <Box flexShrink={0} px={{ base: 3, md: 6, lg: 8 }} pt={3} pb={{ base: 'calc(16px + env(safe-area-inset-bottom))', md: 4 }}
      borderTop={`1px solid ${CHAT_THEME.panelBorder}`}
      bg={CHAT_THEME.inputStickyBg} backdropFilter="blur(22px)">
      <Box maxW="960px" mx="auto">
        {/* Превью распознанного голоса — в той же колонке, что и ввод: выровнено
            идеально при любом сайдбаре (раньше жило в контейнере и разъезжалось). */}
        <ComposerVoicePreview text={voiceText} onDiscard={onDiscardVoice} onEdit={onEditVoice} />
        {/* Прикреплённые файлы — НАД полем ввода (рядом с голосовым превью), а не
            между вводом и кнопками режимов (там было тесно и неопрятно). */}
        <ComposerAttachments attachments={attachments} onRemove={onRemoveAttachment} onOpenWork={onOpenWork} />
        <ComposerShell busy={isStreaming}>
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

          <IconButton aria-label="Прикрепить файл" icon={<FiPaperclip />} size="sm" variant="ghost"
            position="absolute" left={{ base: 1.5, md: 2.5 }} top={{ base: '6px', md: '10px' }} zIndex={2}
            boxSize={{ base: '44px', md: '32px' }} minW={{ base: '44px', md: '32px' }}
            isLoading={isFileUploading}
            isDisabled={(attachments?.length || 0) >= MAX_ATTACHMENTS}
            title={
              (attachments?.length || 0) >= MAX_ATTACHMENTS
                ? `Максимум ${MAX_ATTACHMENTS} файлов`
                : 'Прикрепить файл'
            }
            color={attachments?.length ? IRIS : CHAT_THEME.textTertiary}
            _hover={{ color: CHAT_THEME.textPrimary, bg: CHAT_THEME.panelHover }}
            borderRadius={borderRadius.sm} onClick={() => fileInputRef.current?.click()} />

          <Box
            as="textarea"
            aria-label="Сообщение"
            ref={inputRef}
            onInput={handleInput}
            onKeyDown={handleKeyDown}
            placeholder="Напишите сообщение..."
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
              paddingLeft: '56px',
              paddingRight: '112px',
              paddingTop: '15px',
              paddingBottom: '15px',
              boxSizing: 'border-box',
              '&::placeholder': { color: CHAT_THEME.textTertiary },
              '&:disabled': { opacity: 0.6, cursor: 'not-allowed' },
            }}
          />

          <HStack position="absolute" right={{ base: 1.5, md: 2.5 }} bottom={{ base: '6px', md: '10px' }} spacing={1} zIndex={2} align="center">
            <ComposerVoiceControl recordingState={isRecording ? 'recording' : 'idle'} isTranscribing={isVoiceTranscribing} elapsedSec={recordElapsedSec} onToggle={onVoiceToggle} />
            {isStreaming ? (
              <IconButton aria-label="Остановить генерацию" title="Остановить (Esc)"
                icon={<Box boxSize="11px" bg="currentColor" borderRadius="3px" />}
                size="sm" boxSize={{ base: '44px', md: '32px' }} minW={{ base: '44px', md: '32px' }}
                bg={CHAT_THEME.panelActive} color={CHAT_THEME.textPrimary}
                borderRadius={borderRadius.sm}
                border={`1px solid ${CHAT_THEME.panelBorderStrong}`}
                _hover={{ bg: 'rgba(140,160,255,0.20)' }}
                transition={`all 160ms ${EASE}`}
                onClick={() => onStopRef.current?.()} />
            ) : (
              <IconButton aria-label="Отправить" icon={<FiSend />} size="sm" boxSize={{ base: '44px', md: '32px' }} minW={{ base: '44px', md: '32px' }}
                title={isFileUploading ? 'Дождитесь загрузки файла' : canSend ? 'Отправить (Enter)' : 'Введите сообщение'}
                bg={canSend ? CHAT_THEME.accent : 'rgba(255,255,255,0.08)'} color="white"
                borderRadius={borderRadius.sm}
                boxShadow={canSend ? shadows.sendGlow : 'none'}
                _hover={{ bg: canSend ? CHAT_THEME.accentHover : 'rgba(255,255,255,0.12)' }}
                _disabled={{ opacity: 0.4, cursor: 'not-allowed' }}
                transition={`all 160ms ${EASE}`}
                isDisabled={!canSend} onClick={handleSubmit} />
            )}
          </HStack>
        </ComposerShell>

        <HStack mt={2.5} spacing={2} justify="space-between" flexWrap="wrap" align="center">
          <HStack spacing={1.5} flexWrap="wrap">
            <ComposerModeSelector value={forcedRoute} onChange={onForcedRouteChange}
              multiIntentEnabled={multiIntentEnabled} onToggleMultiIntent={onToggleMultiIntent}
              planningEnabled={planningEnabled} onTogglePlanning={onTogglePlanning} />
            {/* Третья ось выбора: режим — ЧТО делать, модель — ЧЕМ думать, личность — КАК
                думать. Оси ортогональны, поэтому селектор отдельный и виден в любом режиме. */}
            <ComposerPersonaSelector personas={personas} value={personaIds} onChange={onPersonaIdsChange} />
          </HStack>

          <HStack spacing={2.5} align="center">
            {contextInfo?.hasWindow && (
              <ContextGauge
                pct={contextInfo.pct}
                tokens={contextInfo.tokens}
                windowTokens={contextInfo.windowTokens}
                modelWindow={contextInfo.modelWindow}
                bySection={contextInfo.bySection}
                threshold={contextInfo.threshold}
                onCompact={onCompactContext}
                busy={compacting}
              />
            )}
            <ModelSelector
              size="compact"
              placement="top-end"
              selectedModel={selectedModel}
              availableModels={availableModels}
              catalog={modelCatalog}
              onChange={onModelChange}
            />
            {!isAuthenticated && (
              <Text fontSize="12px" color={CHAT_THEME.textTertiary} whiteSpace="nowrap">
                {remainingRequests} запросов
              </Text>
            )}
          </HStack>
        </HStack>
      </Box>
    </Box>
  );
});

export default React.memo(ChatComposerPanel);
