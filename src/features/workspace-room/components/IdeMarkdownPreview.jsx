import { useMemo, useRef } from 'react';
import { Box, Text } from '@chakra-ui/react';
import { MessageRenderer, PROSE_SX } from '@features/chat';
import { colors } from '@theme/tokens';

function repositoryLink(path, href) {
  if (!href || /^[a-z][a-z0-9+.-]*:|^[#/\\]/i.test(href)) return null;
  const parts = path.split('/').slice(0, -1);
  try {
    for (const part of decodeURIComponent(href.split(/[?#]/)[0]).split('/')) {
      if (part === '..') { if (!parts.length) return null; parts.pop(); }
      else if (part && part !== '.') parts.push(part);
    }
  } catch { return null; }
  return parts.length ? parts.join('/') : null;
}

/** Repository bytes are not model output: no thinking-tag stripping or fence repair. */
export default function IdeMarkdownPreview({ file, onOpen }) {
  const rootRef = useRef(null);
  const components = useMemo(() => ({
    a: ({ href, children }) => {
      if (/^(https?:\/\/|mailto:)/i.test(href || '')) return <a href={href} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">{children}</a>;
      if (href?.startsWith('#')) return <a href={href} onClick={event => {
        event.preventDefault();
        let fragment;
        try { fragment = decodeURIComponent(href.slice(1)); } catch { return; }
        const heading = [...(rootRef.current?.querySelectorAll('[data-repository-anchor]') || [])]
          .find(node => node.dataset.repositoryAnchor === fragment);
        heading?.focus({ preventScroll: true });
        heading?.scrollIntoView?.({ block: 'start', inline: 'nearest', behavior: 'auto' });
      }}>{children}</a>;
      const destination = repositoryLink(file.path, href);
      return destination ? <a href={href} onClick={event => { event.preventDefault(); onOpen(destination); }}>{children}</a> : <span>{children}</span>;
    },
    // A README must not silently contact a remote tracking endpoint or resolve
    // an arbitrary relative URL against the signed-in application's origin.
    img: ({ alt }) => <Text as="span" fontSize="xs" color={colors.fg[3]} title="Автоматическая загрузка изображений из Markdown отключена">Изображение: {alt || 'без подписи'}</Text>,
  }), [file.path, onOpen]);
  return <Box ref={rootRef} p={4} fontSize="sm" lineHeight={1.7} sx={{ ...PROSE_SX,
    '& [data-repository-anchor]': { scrollMarginTop: 3,
      _focusVisible: { outline: `2px solid ${colors.border.focus}`, outlineOffset: '2px' } } }}>
    <MessageRenderer content={file.content || ''} variant="repository" components={components} />
  </Box>;
}
