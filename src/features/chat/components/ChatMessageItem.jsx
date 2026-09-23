import { memo, useCallback, useEffect, useRef, useState } from 'react';
import { keyframes } from '@emotion/react';
import { Badge, Box, Button, HStack, Icon, IconButton, Image, Menu, MenuButton, MenuDivider, MenuItem, MenuList, Text, Tooltip } from '@chakra-ui/react';
import { FiCheck, FiCopy, FiDownload, FiEdit2, FiFolder, FiRotateCcw, FiSearch, FiThumbsDown, FiThumbsUp, FiX, FiZap } from '@shared/icons';
import ActionLink from '@shared/controls/ActionLink';
import AppTextarea from '@shared/controls/AppTextarea';
import { colors, borderRadius, motion, shadows } from '@theme/tokens';
import MessageRenderer from './MessageRenderer';
import MessageAttachments from './MessageAttachments';
import MessageSources from './MessageSources';
import { parseModelMeta, resolveMessageModelLabel } from '../utils/modelSelector';
import { feedbackKey } from '../utils/feedbackKey';
import { CHAT_FONT_FAMILY, CHAT_THEME } from '../constants/theme';
import { PROSE_SX } from '../page/proseStyles';
import { stripThinking } from '../utils/thinking';
import { resolveArtifactUrl } from '../utils/artifactUrl';

const dotPulse = keyframes`
  0%, 80%, 100% { opacity: 0.35; transform: scale(0.92); }
  40% { opacity: 1; transform: scale(1); }
`;

// Мягкое появление сообщения (fade + подъём) один раз на mount.
const messageIn = keyframes`
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
`;

// Мигающая каретка в хвосте стримингового текста.
const caretBlink = keyframes`
  0%, 45% { opacity: 1; }
  50%, 95% { opacity: 0; }
  100% { opacity: 1; }
`;

// Каретка добавляется как ::after к последнему блоку прозы — рендерится ИНЛАЙН
// в конце последней строки стрима (а не с новой строки).
const STREAM_CARET_SX = {
  '& > *:last-child::after': {
    content: '""',
    display: 'inline-block',
    width: '2px',
    height: '1.05em',
    marginLeft: '2px',
    verticalAlign: '-0.15em',
    borderRadius: '1px',
    background: colors.blue[300],
    animation: `${caretBlink} 1.05s steps(1) infinite`,
  },
};

// Готовая комбинация «проза + каретка»: спред в рендере создавал новый объект на
// КАЖДЫЙ токен стрима, и Emotion заново хешировал ~29 селекторов PROSE_SX.
const PROSE_STREAMING_SX = { ...PROSE_SX, ...STREAM_CARET_SX };
const EMPTY_SX = {};

const ACTION_REVEAL_SX = { '&:focus-within': { opacity: 1 } };

function formatTokens(n) {
  if (!n || n <= 0) return '0';
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`;
  return String(n);
}

function isImageArtifact(url, metadata) {
  if (metadata?.route === 'image_gen' || metadata?.input_type === 'image') return true;
  // Записи generated_files несут явные подсказки; presigned-URL расширения не имеет.
  if (metadata?.kind === 'image' || String(metadata?.mime_type || '').startsWith('image/')) return true;
  const clean = String(url || '').split('?')[0].toLowerCase();
  return /\.(png|jpe?g|gif|webp|bmp|svg)$/.test(clean);
}

// s3://<bucket>/<key> и голые ключи хранилища браузер напрямую скачать не может —
// проксируем через бэкенд-эндпоинт (кука-авторизация → 307 на presigned URL).
/** Сгенерированный артефакт (изображение инлайн / прочий файл — кнопка скачивания). */
function MessageArtifact({ url, fileId, metadata }) {
  if (!url && !fileId) return null;
  const resolved = resolveArtifactUrl(url, metadata?.filename, fileId);
  if (isImageArtifact(url, metadata)) {
    return (
      <Box mt={3} borderRadius={borderRadius.md} overflow="hidden" border={`1px solid ${CHAT_THEME.panelBorder}`} maxW="440px" bg="rgba(0,0,0,0.2)">
        <Image src={resolved} alt={metadata?.filename || 'Сгенерированное изображение'} maxW="100%" display="block" loading="lazy" />
      </Box>
    );
  }
  return (
    <ActionLink
      href={resolved}
      isExternal
      mt={3}
      size="sm"
      leftIcon={<Icon as={FiDownload} />}
      variant="unstyled"
      display="inline-flex"
      alignItems="center"
      h="34px"
      px={3}
      color={CHAT_THEME.textPrimary}
      bg={CHAT_THEME.panelHover}
      border={`1px solid ${CHAT_THEME.panelBorder}`}
      borderRadius={borderRadius.sm}
      _hover={{ bg: CHAT_THEME.panelActive, textDecoration: 'none' }}
    >
      {metadata?.filename || 'Скачать файл'}
    </ActionLink>
  );
}

/** Время выполнения: секунды с одним знаком до минуты, дальше «м с». */
function formatDuration(ms) {
  const sec = ms / 1000;
  if (sec < 60) return `${sec < 10 ? sec.toFixed(1) : Math.round(sec)} с`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return s ? `${m} м ${s} с` : `${m} м`;
}

// Инструменты с надбавкой — человеческим языком. Незнакомый ключ показываем как есть:
// набор задаётся ценообразованием на бэкенде и может пополниться без выката фронта.
const TOOL_LABELS = {
  web_search: 'веб-поиск',
  deep_research: 'глубокое исследование',
  image_gen: 'генерацию изображения',
  pptx_gen: 'сборку презентации',
  audio_transcribe: 'расшифровку аудио',
  // Поиск, который модель вызвала САМА по ходу обычного ответа, — не тот же режим, что
  // «Веб-поиск» в меню. Без своей подписи в счёте показалось бы машинное
  // `web_search_tool`, а с подписью маршрута человек решил бы, что включился режим.
  web_search_tool: 'поиск в интернете по ходу ответа',
};

/** Компактный чип потребления сообщения: токены + кредиты + время выполнения. */
function UsageChip({ usage }) {
  if (!usage || !(usage.total > 0 || usage.duration_ms > 0)) return null;
  // Отвечала НЕ та модель, которую выбрал человек: его провайдер лёг, запрос ушёл
  // соседу. Молчать об этом нельзя — человек видел свой выбор и чужой счёт.
  const substituted = usage.actual_model && usage.actual_model !== usage.model;
  // Надбавка за инструмент — ФИКСИРОВАННАЯ сумма за работу, а не за токены, и она
  // может перевешивать весь токенный счёт (замер: 834 кредита за веб-поиск против 733
  // за токены). Без этой строки пара «2.9k т. · 1567 кр.» читалась как непонятно
  // дорогие токены, и объяснить счёт было нечем.
  const surcharge = usage.surcharge_credits > 0
    ? `Из них ${usage.surcharge_credits} кр. — надбавка за ${
      (usage.surcharged_tools || []).map((t) => TOOL_LABELS[t] || t).join(', ') || 'инструменты'
    } (плата за работу, не за токены)`
    : null;
  const tip = [
    `Промпт: ${usage.prompt ?? 0}`,
    `Ответ: ${usage.completion ?? 0}`,
    usage.duration_ms > 0 ? `Время: ${formatDuration(usage.duration_ms)}` : null,
    usage.model ? `Модель: ${usage.model}` : null,
    surcharge,
    // ⚠️ Имя модели НЕ равно имени провайдера. Каталоги агрегаторов вендор-префиксные:
    // `openai/gpt-4o-mini` у нас обслуживает RouterAI, а не OpenAI. Живая жалоба: человек
    // выключил всех провайдеров кроме двух, увидел в подписи «openai/…» и решил, что
    // выключенный провайдер всё равно работает. Говорим это прямо, иначе префикс в имени
    // читается как обход настроек.
    substituted
      ? 'Префикс в имени модели — это вендор в каталоге провайдера, а не сам провайдер: '
        + '«openai/…» может обслуживать RouterAI.'
      : null,
    substituted
      ? `Отвечала: ${usage.actual_model} — ваш провайдер был недоступен. `
        + 'Списано по цене выбранной вами модели.'
      : null,
  ].filter(Boolean).join('  ·  ');
  const parts = [
    usage.total > 0 ? `${formatTokens(usage.total)} т.` : null,
    usage.credits > 0 ? `${usage.credits} кр.` : null,
    usage.duration_ms > 0 ? formatDuration(usage.duration_ms) : null,
    substituted ? 'замена модели' : null,
  ].filter(Boolean);
  return (
    <Tooltip label={tip} placement="bottom-start" openDelay={200} hasArrow>
      <HStack
        spacing={1.5}
        px={2}
        h="24px"
        borderRadius={borderRadius.sm}
        bg={substituted ? colors.warningSoft : CHAT_THEME.panelHover}
        border={`1px solid ${substituted ? colors.warningBorder : CHAT_THEME.panelBorder}`}
        cursor="default"
      >
        <Text fontSize="11px" fontFamily="'JetBrains Mono', monospace" color={CHAT_THEME.textSecondary} whiteSpace="nowrap">
          {parts.join(' · ')}
        </Text>
      </HStack>
    </Tooltip>
  );
}

/** Одно сообщение чата (пользователь или агент) со служебными действиями. */
function ChatMessageItem({ message, isLastMessage, isFirstInGroup = true, lastUsedModel, availableModels, copyMessage, regenerateMessage, editMessage, onFeedback, isLoading, onOpenWork }) {
  const isUser = message.type === 'user';
  // Видимая часть (без <think>): пока стримятся только рассуждения, тело пустое —
  // в этом случае показываем «печатает», а не пустой пузырь.
  const visibleContent = isUser ? message.content : stripThinking(message.content);
  const isStreamingBody = !isUser && message.isTyping && !!visibleContent;
  const modelLabel = isUser ? null : resolveMessageModelLabel(message, lastUsedModel);
  const agentName = message.metadata?.agent_name;
  const _ts = message.timestamp ? new Date(message.timestamp) : null;
  const timeStr = _ts && !Number.isNaN(_ts.getTime())
    ? _ts.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : '';

  // Фидбэк 👍/👎 — инициализируем из message.feedback (восстановлено из истории).
  const [feedback, setFeedback] = useState(message.feedback || null);
  const rateMessage = useCallback((rating) => {
    if (!onFeedback) return;
    const next = feedback === rating ? null : rating; // повторный клик снимает оценку
    setFeedback(next);
    onFeedback(feedbackKey(message.content), next);
  }, [feedback, onFeedback, message.content]);

  const [copied, setCopied] = useState(false);
  const copiedTimerRef = useRef(null);
  useEffect(() => () => {
    if (copiedTimerRef.current) clearTimeout(copiedTimerRef.current);
  }, []);
  const handleCopy = useCallback(() => {
    // Копируем видимый ответ без служебных <think>-рассуждений.
    copyMessage(stripThinking(message.content));
    setCopied(true);
    if (copiedTimerRef.current) clearTimeout(copiedTimerRef.current);
    copiedTimerRef.current = setTimeout(() => setCopied(false), 1600);
  }, [copyMessage, message.content]);

  // Инлайн-правка пользовательского хода.
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState('');
  const editRef = useRef(null);
  const startEdit = useCallback(() => {
    setEditValue(message.content || '');
    setIsEditing(true);
  }, [message.content]);
  const cancelEdit = useCallback(() => setIsEditing(false), []);
  const submitEdit = useCallback(() => {
    const next = editValue.trim();
    setIsEditing(false);
    if (next && next !== (message.content || '').trim()) {
      editMessage?.(message.id, next);
    }
  }, [editValue, editMessage, message.content, message.id]);
  // Авто-рост высоты редактора под контент (до потолка со скроллом) — иначе при
  // фикс. minH текст обрезался и вылезал скролл-стрелками.
  const autosizeEdit = useCallback(() => {
    const el = editRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
  }, []);
  useEffect(() => {
    if (isEditing && editRef.current) {
      const el = editRef.current;
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
      autosizeEdit();
    }
  }, [isEditing, autosizeEdit]);
  const handleEditKeyDown = useCallback((e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitEdit(); }
    else if (e.key === 'Escape') { e.preventDefault(); cancelEdit(); }
  }, [submitEdit, cancelEdit]);

  return (
    <Box
      display="flex"
      justifyContent={isUser ? 'flex-end' : 'flex-start'}
      w="100%"
      animation={`${messageIn} 0.32s ${motion.easeOut}`}
      sx={{ '@media (prefers-reduced-motion: reduce)': { animation: 'none' } }}
    >
      <Box role="group" maxW={{ base: '96%', md: '80%', lg: '72%' }} w={isUser ? 'fit-content' : '100%'} minW={0}>
        {!isUser && isFirstInGroup && (
          <HStack spacing={2.5} mb={2} pl={1} align="center">
            <Box
              boxSize="28px"
              flexShrink={0}
              borderRadius={borderRadius.sm}
              bg={CHAT_THEME.accentSoft}
              border={`1px solid ${colors.accent.subtleBorder}`}
              boxShadow={shadows.glowSubtle}
              display="flex"
              alignItems="center"
              justifyContent="center"
            >
              <Icon as={FiZap} boxSize="14px" color={colors.blue[300]} />
            </Box>
            <Text fontSize="13px" fontWeight="650" color={CHAT_THEME.textPrimary} letterSpacing="-0.005em">
              {modelLabel}
            </Text>
            {agentName && (
              <Badge
                px={2}
                py={0.5}
                borderRadius="full"
                fontSize="10px"
                fontWeight="600"
                textTransform="none"
                background={colors.accent.subtle}
                color={colors.blue[300]}
                border={`1px solid ${colors.accent.subtleBorder}`}
              >
                {agentName}
              </Badge>
            )}
            <Text fontSize="11px" color={CHAT_THEME.textTertiary} fontWeight="500">
              {timeStr}
            </Text>
          </HStack>
        )}

        {isUser && isEditing ? (
          <Box
            bg={CHAT_THEME.userBubble}
            border={`1px solid ${CHAT_THEME.inputBorderFocus}`}
            borderRadius={borderRadius.lg}
            p={2}
            w="100%"
            minW={0}
            maxW="100%"
          >
            <AppTextarea
              ref={editRef}
              value={editValue}
              onChange={(e) => { setEditValue(e.target.value); autosizeEdit(); }}
              onKeyDown={handleEditKeyDown}
              variant="unstyled"
              w="100%"
              minH="40px"
              maxH="240px"
              overflowY="auto"
              px={2}
              py={1}
              fontSize={{ base: '14px', md: '14.5px' }}
              lineHeight="1.5"
              color={CHAT_THEME.textPrimary}
              fontFamily={CHAT_FONT_FAMILY}
              resize="none"
            />
            <HStack justify="flex-end" spacing={2} mt={2}>
              <Button size="xs" variant="ghost" color={CHAT_THEME.textSecondary}
                leftIcon={<Icon as={FiX} boxSize="12px" />}
                _hover={{ bg: CHAT_THEME.panelHover, color: CHAT_THEME.textPrimary }}
                onClick={cancelEdit}>Отмена</Button>
              <Button size="xs" bg={CHAT_THEME.accent} color="white"
                boxShadow={shadows.sendGlow}
                _hover={{ bg: CHAT_THEME.accentHover }}
                onClick={submitEdit}>Отправить</Button>
            </HStack>
          </Box>
        ) : (
          <Box
            px={isUser ? { base: 4, md: 5 } : { base: 0, md: 1 }}
            py={isUser ? { base: 3, md: 3.5 } : 0}
            borderRadius={isUser ? `${borderRadius.lg} ${borderRadius.lg} ${borderRadius.sm} ${borderRadius.lg}` : 'none'}
            bg={isUser ? CHAT_THEME.userBubble : 'transparent'}
            border={isUser ? `1px solid ${CHAT_THEME.userBubbleBorder}` : 'none'}
            boxShadow={isUser ? shadows.glowUser : 'none'}
            fontSize={{ base: '14px', md: '14.5px' }}
            lineHeight="1.72"
            color={CHAT_THEME.textPrimary}
            transition={`transform 160ms ${motion.easeOut}`}
            _groupHover={isUser ? { transform: 'translateY(-1px)' } : undefined}
            aria-live={isStreamingBody ? 'polite' : undefined}
            sx={isUser ? EMPTY_SX : isStreamingBody ? PROSE_STREAMING_SX : PROSE_SX}
          >
            {isUser ? (
              <>
                {message.attachments?.length ? (
                  <MessageAttachments attachments={message.attachments} onOpenWork={onOpenWork} />
                ) : null}
                <Text
                  color={colors.text.primary}
                  whiteSpace="pre-wrap"
                  fontWeight="500"
                  lineHeight="1.6"
                >
                  {message.content}
                </Text>
              </>
            ) : (
              <>
                <MessageRenderer
                  content={message.content}
                  isTyping={message.isTyping}
                  typingProgress={message.typingProgress}
                  messageType={message.type}
                />
                {message.metadata?.pptx_b64 && (
                  <Button
                    mt={3}
                    size="sm"
                    leftIcon={<Icon as={FiDownload} />}
                    bg={CHAT_THEME.accent}
                    color="white"
                    fontWeight="600"
                    borderRadius={borderRadius.sm}
                    boxShadow={shadows.sendGlow}
                    _hover={{ bg: CHAT_THEME.accentHover }}
                    _active={{ bg: colors.blue[700] }}
                    onClick={() => {
                      const bytes = Uint8Array.from(atob(message.metadata.pptx_b64), (c) => c.charCodeAt(0));
                      const blob = new Blob([bytes], { type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' });
                      const url = URL.createObjectURL(blob);
                      const a = document.createElement('a');
                      a.href = url;
                      a.download = message.metadata.filename || 'presentation.pptx';
                      a.click();
                      URL.revokeObjectURL(url);
                    }}
                  >
                    Скачать презентацию (.pptx)
                  </Button>
                )}
                {(() => {
                  // Мульти-интент может дать НЕСКОЛЬКО артефактов (напр. 2 картинки) —
                  // рисуем ВСЕ из generated_files, а не только первый message.file_url
                  // (аудит A4: раньше показывался лишь один, хотя оплачены все).
                  const files = Array.isArray(message.metadata?.generated_files)
                    ? message.metadata.generated_files
                    : [];
                  if (files.length > 0) {
                    return files.map((f, i) => (
                      <MessageArtifact
                        key={f.file_id || f.file_key || i}
                        url={f.file_url}
                        fileId={f.file_id}
                        metadata={{ filename: f.filename, kind: f.kind, mime_type: f.mime_type }}
                      />
                    ));
                  }
                  return message.file_url && !message.metadata?.pptx_b64 ? (
                    <MessageArtifact url={message.file_url} metadata={message.metadata} />
                  ) : null;
                })()}
                {message.metadata?.document_project_saved === true
                  && ['draft_ready', 'failed'].includes(message.metadata?.document_outcome) && (
                  <HStack
                    mt={3}
                    spacing={2}
                    flexWrap="wrap"
                    aria-label="Действия с сохранённым PDF-проектом"
                  >
                    <Button
                      size="sm"
                      variant="outline"
                      leftIcon={<Icon as={FiFolder} />}
                      borderColor={CHAT_THEME.panelBorder}
                      color={CHAT_THEME.textPrimary}
                      onClick={onOpenWork}
                      isDisabled={!onOpenWork}
                    >
                      {message.metadata?.document_failure_code === 'evidence_incomplete'
                        ? 'Добавить источники в Работе'
                        : 'Открыть в Работе'}
                    </Button>
                    {message.metadata?.document_failure_code === 'evidence_incomplete' && (
                      <Button
                        size="sm"
                        variant="outline"
                        leftIcon={<Icon as={FiSearch} />}
                        borderColor={CHAT_THEME.panelBorder}
                        color={CHAT_THEME.textPrimary}
                        onClick={() => regenerateMessage(
                          message.id,
                          undefined,
                          'research_pdf_document',
                        )}
                        isDisabled={isLoading || !regenerateMessage}
                      >
                        Исследовать источники и подготовить финал
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="ghost"
                      leftIcon={<Icon as={FiRotateCcw} />}
                      color={CHAT_THEME.textSecondary}
                      onClick={() => regenerateMessage(message.id)}
                      isDisabled={isLoading || !regenerateMessage}
                    >
                      Повторить с черновика
                    </Button>
                  </HStack>
                )}
              </>
            )}
          </Box>
        )}

        {/* 🔴 ПРЕДЛОЖЕНИЕ ДОРОГОГО РЕЖИМА ПЕРЕЕХАЛО В ТРЕЙС (`TraceEventRow`), и здесь
            его больше НЕТ — оно не дублируется, а живёт в одном месте. Под ответом
            карточка висела вечно: человек либо жал кнопку задним числом, когда ответ уже
            прочитан, либо она просто мозолила глаза. В ходе работы решение имеет смысл —
            там оно и предлагается, с серверным отсчётом.

            Молчание = отказ, и отказ ВИДЕН: строка «отклонён по таймауту» в трейсе плюс
            детерминированная приписка к ответу («режим не запускался»). Обычный путь
            запустить режим у человека остаётся — селектор режима в композере. */}
        {/* Чипы источников рисуются у ОБЕИХ сторон: у пользователя это ссылки, которые
            он прислал, у ассистента — те, что он прочитал сам. Раньше условие было
            `isUser`, и найденное веб-поиском не показывалось нигде — человек не мог ни
            перейти по источнику, ни понять, откуда взят факт. */}
        {!isEditing && message.metadata?.sources && (
          <MessageSources sources={message.metadata.sources} />
        )}
        {isUser && !isEditing && (
          <HStack
            justify="flex-end"
            spacing={1}
            mt={1.5}
            pr={1}
            opacity={0}
            _groupHover={{ opacity: 1 }}
            transition={`opacity 140ms ${motion.easeOut}`}
            sx={ACTION_REVEAL_SX}
          >
            <Tooltip label="Редактировать" placement="top" openDelay={400} hasArrow>
              <IconButton
                aria-label="Редактировать сообщение"
                icon={<FiEdit2 />}
                size="xs"
                variant="ghost"
                color={CHAT_THEME.textSecondary}
                borderRadius={borderRadius.sm}
                _hover={{ bg: CHAT_THEME.panelHover, color: CHAT_THEME.textPrimary }}
                onClick={startEdit}
                isDisabled={isLoading}
              />
            </Tooltip>
            <Text color={CHAT_THEME.textTertiary} fontSize="11px" fontWeight="500">
              {timeStr}
            </Text>
          </HStack>
        )}
        {!isUser && message.isTyping && !visibleContent && (
          <HStack spacing="5px" mt={1} pl={1}>
            {[0, 1, 2].map((i) => (
              <Box
                key={i}
                w="7px"
                h="7px"
                borderRadius="full"
                bg="rgba(45, 91, 255,0.7)"
                sx={{
                  animation: `${dotPulse} 1.4s ease-in-out infinite`,
                  animationDelay: `${i * 0.18}s`,
                }}
              />
            ))}
          </HStack>
        )}
        {!isUser && !message.isTyping && message.content && (
          <HStack
            spacing={1}
            mt={2}
            pl={1}
            opacity={isLastMessage ? 1 : 0}
            _groupHover={{ opacity: 1 }}
            transition={`opacity 140ms ${motion.easeOut}`}
            sx={ACTION_REVEAL_SX}
          >
            <Tooltip label={copied ? 'Скопировано!' : 'Копировать'} placement="top" openDelay={400} hasArrow>
              <IconButton
                aria-label="Скопировать ответ"
                icon={copied ? <FiCheck /> : <FiCopy />}
                size="xs"
                variant="ghost"
                color={copied ? colors.success : CHAT_THEME.textSecondary}
                borderRadius={borderRadius.sm}
                _hover={{ bg: CHAT_THEME.panelHover, color: copied ? colors.success : CHAT_THEME.textPrimary }}
                onClick={handleCopy}
              />
            </Tooltip>
            {onFeedback && (
              <>
                <Tooltip label="Хороший ответ" placement="top" openDelay={400} hasArrow>
                  <IconButton aria-label="Хороший ответ" icon={<FiThumbsUp />} size="xs" variant="ghost"
                    color={feedback === 'up' ? colors.success : CHAT_THEME.textSecondary}
                    borderRadius={borderRadius.sm}
                    sx={feedback === 'up' ? { '& svg': { fill: 'currentColor' } } : undefined}
                    _hover={{ bg: CHAT_THEME.panelHover, color: feedback === 'up' ? colors.success : CHAT_THEME.textPrimary }}
                    onClick={() => rateMessage('up')} />
                </Tooltip>
                <Tooltip label="Плохой ответ" placement="top" openDelay={400} hasArrow>
                  <IconButton aria-label="Плохой ответ" icon={<FiThumbsDown />} size="xs" variant="ghost"
                    color={feedback === 'down' ? colors.warning : CHAT_THEME.textSecondary}
                    borderRadius={borderRadius.sm}
                    sx={feedback === 'down' ? { '& svg': { fill: 'currentColor' } } : undefined}
                    _hover={{ bg: CHAT_THEME.panelHover, color: feedback === 'down' ? colors.warning : CHAT_THEME.textPrimary }}
                    onClick={() => rateMessage('down')} />
                </Tooltip>
              </>
            )}
            {isLastMessage && (
              <Menu placement="top-start" isLazy autoSelect={false}>
                <MenuButton
                  as={IconButton}
                  aria-label="Перегенерировать ответ"
                  icon={<FiRotateCcw />}
                  size="xs"
                  variant="ghost"
                  color={CHAT_THEME.textSecondary}
                  borderRadius={borderRadius.sm}
                  _hover={{ bg: CHAT_THEME.panelHover, color: CHAT_THEME.textPrimary }}
                  isDisabled={isLoading}
                />
                <MenuList
                  bg={CHAT_THEME.sidebarBg}
                  borderColor={CHAT_THEME.panelBorder}
                  borderRadius={borderRadius.md}
                  minW="230px"
                  maxH="320px"
                  overflowY="auto"
                  py={1}
                  zIndex={30}
                  sx={{ backdropFilter: 'blur(22px)' }}
                >
                  <MenuItem bg="transparent" _hover={{ bg: CHAT_THEME.panelHover }} _focus={{ bg: CHAT_THEME.panelHover }}
                    color={CHAT_THEME.textPrimary} fontSize="13px" onClick={() => regenerateMessage(message.id)}>
                    <Icon as={FiRotateCcw} boxSize="13px" mr={2} /> Перегенерировать
                  </MenuItem>
                  {(availableModels && availableModels.length > 0) && (
                    <>
                      <MenuDivider borderColor={CHAT_THEME.panelBorder} />
                      <Text px={3} py={1} fontSize="10.5px" fontWeight="600" textTransform="uppercase"
                        letterSpacing="0.06em" color={CHAT_THEME.textTertiary}>
                        На другой модели
                      </Text>
                      <MenuItem bg="transparent" _hover={{ bg: CHAT_THEME.panelHover }} _focus={{ bg: CHAT_THEME.panelHover }}
                        color={CHAT_THEME.textPrimary} fontSize="13px" onClick={() => regenerateMessage(message.id, '')}>
                        Auto
                      </MenuItem>
                      {availableModels.map((m) => {
                        const meta = parseModelMeta(m);
                        return (
                          <MenuItem key={m} bg="transparent" _hover={{ bg: CHAT_THEME.panelHover }} _focus={{ bg: CHAT_THEME.panelHover }}
                            color={CHAT_THEME.textPrimary} fontSize="13px" onClick={() => regenerateMessage(message.id, m)}>
                            {meta.providerLabel ? `${meta.providerLabel} · ${meta.label}` : meta.label}
                          </MenuItem>
                        );
                      })}
                    </>
                  )}
                </MenuList>
              </Menu>
            )}
            {message.metadata?.usage ? <UsageChip usage={message.metadata.usage} /> : null}
          </HStack>
        )}
      </Box>
    </Box>
  );
}

export default memo(ChatMessageItem);
