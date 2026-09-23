import React, { Suspense, lazy, memo, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkBreaks from 'remark-breaks';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { Box, Text } from '@chakra-ui/react';
import 'katex/dist/katex.min.css';

import { colors, borderRadius } from '@theme/tokens';
import { stripThinking, stripToolCallTags } from '../utils/thinking';

// Ленивый код-блок: тяжёлый Prism грузится отдельным чанком только при появлении кода.
const CodeBlock = lazy(() => import('./CodeBlock'));

/**
 * completeMarkdown — добавляет недостающие закрывающие маркеры,
 * чтобы стриминговый вывод модели парсился корректно (не «ломался»
 * на полпути). Закрывает неполные блоки кода, inline-код,
 * жирный и курсивный текст.
 */
function completeMarkdown(raw) {
  if (!raw || typeof raw !== 'string') return raw || '';

  // Ранний выход: нет backtick/asterisk/$ -> чинить нечего, не трогаем текст
  // (избегаем ложных правок валидного markdown и лишней работы на каждом чанке).
  if (!/[`*$]/.test(raw)) return raw;

  let text = raw;
  const lines = text.split('\n');
  let inFence = false;
  for (const line of lines) {
    if (/^\s*```/.test(line)) {
      inFence = !inFence;
    }
  }
  if (inFence) {
    text += (text.endsWith('\n') ? '' : '\n') + '```';
  }

  const withoutFences = text.replace(/```[\s\S]*?```/g, '');
  const inlineTicks = (withoutFences.match(/`/g) || []).length;
  if (inlineTicks % 2 === 1) {
    text += '`';
  }

  // Незакрытая блочная формула $$…: в середине стрима remark-math иначе съедает
  // весь хвост сообщения как одну (битую) формулу. Прячем её до закрытия —
  // формула «появится» целиком, когда дойдёт второй $$ (лучше пустоты, чем каша).
  const dollarBlocks = (withoutFences.match(/\$\$/g) || []).length;
  if (dollarBlocks % 2 === 1) {
    const idx = text.lastIndexOf('$$');
    if (idx !== -1) text = text.slice(0, idx);
  }

  const boldMatches = text.match(/\*\*/g) || [];
  if (boldMatches.length % 2 === 1) {
    text += '**';
  }

  const cleaned = text.replace(/\*\*[\s\S]*?\*\*/g, '');
  const singleAsterisks = (cleaned.match(/(^|[^*])\*(?!\*)/g) || []).length;
  if (singleAsterisks % 2 === 1) {
    text += '*';
  }

  return text;
}

/**
 * Перепарсивать markdown+KaTeX на КАЖДЫЙ токен дорого и дёргает вёрстку. Обновляем не
 * чаще раза в delayMs, но с трейлинг-флашем — финальное значение отрисуется всегда.
 * delayMs=0 — без троттлинга (готовое сообщение).
 */
function useThrottledValue(value, delayMs) {
  const [throttled, setThrottled] = useState(value);
  const lastRef = useRef(0);
  const timerRef = useRef(0);
  useEffect(() => {
    if (!delayMs) {
      window.clearTimeout(timerRef.current);
      setThrottled(value);
      return undefined;
    }
    const since = Date.now() - lastRef.current;
    if (since >= delayMs) {
      lastRef.current = Date.now();
      setThrottled(value);
      return undefined;
    }
    window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => {
      lastRef.current = Date.now();
      setThrottled(value);
    }, delayMs - since);
    return () => window.clearTimeout(timerRef.current);
  }, [value, delayMs]);
  return throttled;
}

/**
 * Модель отдаёт формулы в \[…\] и \(…\), а remark-math знает только $ / $$; вдобавок
 * CommonMark считает \[ экранированной скобкой, и без препроцессинга формулы не парсятся
 * вовсе. Конвертируем, НЕ трогая содержимое блоков кода и инлайн-кода.
 */
function normalizeMath(raw) {
  if (!raw || typeof raw !== 'string') return raw || '';

  // Ранний выход: ни одного мат-делимитера -> чинить нечего, не трогаем текст.
  if (!raw.includes('\\[') && !raw.includes('\\(')) return raw;

  // split с захватом разделителей: код-сегменты попадают на нечётные индексы.
  const segments = raw.split(/(```[\s\S]*?```|`[^`]*`)/g);
  return segments
    .map((seg, i) => {
      if (i % 2 === 1) return seg; // код-сегмент — оставляем как есть
      return seg
        .replace(/\\\[([\s\S]*?)\\\]/g, (_, body) => `$$${body}$$`)
        .replace(/\\\(([\s\S]*?)\\\)/g, (_, body) => `$${body}$`);
    })
    .join('');
}

// Plain-fallback код-блока, пока подтягивается ленивый CodeBlock (Prism).
function CodeFallback({ value }) {
  return (
    <Box
      as="pre"
      my={3}
      p={3}
      pt="2.3rem"
      borderRadius={borderRadius.md}
      border={`1px solid ${colors.border.card}`}
      bg={colors.bg.inputStrong}
      overflowX="auto"
      fontSize="13px"
      fontFamily="'JetBrains Mono', monospace"
      color={colors.fg[2]}
      whiteSpace="pre"
    >
      {value}
    </Box>
  );
}

function MessageRendererComponent({ content, isTyping }) {
  const markdownComponents = useMemo(() => ({
    // ⚠️ Код-блок С ЯЗЫКОМ рисует CodeBlock (своя рамка/фон/заголовок). react-markdown
    // при этом всё равно оборачивает его в <pre>, а PROSE-стили дают <pre> ещё одну
    // рамку — получалась «ячейка в ячейке». Здесь: для языкового блока отдаём CodeBlock
    // БЕЗ pre-обёртки; plain-fence (без языка) оставляем в <pre> (его оформляет PROSE).
    pre: ({ children }) => {
      const child = Array.isArray(children) ? children[0] : children;
      const cls = child?.props?.className || '';
      if (/language-\w/.test(cls)) {
        return <>{children}</>;
      }
      return <pre>{children}</pre>;
    },
    code: ({ node, inline, className, children, ...props }) => {
      const match = /language-(\w+)/.exec(className || '');
      const language = match ? match[1] : '';

      if (!inline && match) {
        // children может быть undefined на пустом код-фенсе в середине стрима
        // (completeMarkdown закрыл ещё пустой блок) → не рендерим строку "undefined".
        const codeText = String(children ?? '').replace(/\n$/, '');
        return (
          <Suspense fallback={<CodeFallback value={codeText} />}>
            <CodeBlock language={language} value={codeText} />
          </Suspense>
        );
      }

      return (
        <code className={className} {...props}>
          {children}
        </code>
      );
    },
  }), []);

  // Троттлим контент для парсинга ТОЛЬКО во время стрима; на готовом сообщении —
  // сразу финальный рендер (delayMs=0). Реже перепарсиваем → реже reflow
  // структурных блоков (заголовки/списки/формулы) → меньше «дёрганья» вёрстки.
  const throttled = useThrottledValue(content || '', isTyping ? 90 : 0);

  // Сначала вырезаем блоки <think>...</think> (рассуждения уходят в trace-панель),
  // затем нормализуем мат-делимитеры (\[ \] / \( \) -> $$ / $, т.к. remark-math
  // понимает только $), и лишь потом чиним возможный неполный markdown стрима.
  const safeContent = useMemo(
    () => completeMarkdown(normalizeMath(stripToolCallTags(stripThinking(throttled)))),
    [throttled],
  );

  // Мемоизируем сам вывод по safeContent: пока троттлированный контент не менялся,
  // ReactMarkdown/KaTeX НЕ перепарсиваются (даже если родитель ре-рендерит на токен).
  return useMemo(() => {
    try {
      return (
        <ReactMarkdown
          components={markdownComponents}
          remarkPlugins={[remarkGfm, remarkBreaks, remarkMath]}
          rehypePlugins={[rehypeKatex]}
        >
          {safeContent}
        </ReactMarkdown>
      );
    } catch (error) {
      console.warn('Markdown parsing error, falling back to plain text:', error);
      return (
        <Text color={colors.text.primary} lineHeight="1.6" whiteSpace="pre-wrap">
          {safeContent}
        </Text>
      );
    }
  }, [safeContent, markdownComponents]);
}

const MessageRenderer = memo(MessageRendererComponent);

export default MessageRenderer;
