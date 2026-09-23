import React from 'react';
import { Icon, Link, Text, Wrap, WrapItem } from '@chakra-ui/react';
import { FiExternalLink, FiGlobe } from '@shared/icons';
import { colors, typography } from '@theme/tokens';
import { CHAT_THEME } from '../constants/theme';

function domainOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return String(url || '').replace(/^https?:\/\//, '').split('/')[0];
  }
}

/** Чипы источников: прочитанные из сообщения ссылки (URL-preview / прозрачность). */
export default function MessageSources({ sources }) {
  if (!Array.isArray(sources) || sources.length === 0) return null;
  return (
    <Wrap spacing={1.5} mt={2} align="center" justify="flex-end">
      <WrapItem>
        <Text
          fontSize="10.5px"
          fontWeight="600"
          color={CHAT_THEME.textTertiary}
          textTransform="uppercase"
          letterSpacing="0.06em"
          fontFamily={typography.fontFamily.mono}
        >
          Прочитано
        </Text>
      </WrapItem>
      {sources.map((s, i) => (
        <WrapItem key={`${s.url}_${i}`}>
          <Link
            href={s.url}
            isExternal
            display="inline-flex"
            alignItems="center"
            gap={1}
            px={2}
            py="2px"
            borderRadius="full"
            fontSize="11px"
            fontWeight="500"
            color={s.ok ? colors.blue[300] : CHAT_THEME.textTertiary}
            bg={CHAT_THEME.panelHover}
            border={`1px solid ${CHAT_THEME.panelBorder}`}
            opacity={s.ok ? 1 : 0.6}
            _hover={{ bg: CHAT_THEME.panelActive, textDecoration: 'none', borderColor: colors.accent.subtleBorder }}
            title={s.title || s.url}
          >
            <Icon as={FiGlobe} boxSize="10px" />
            {domainOf(s.url)}
            <Icon as={FiExternalLink} boxSize="9px" opacity={0.6} />
          </Link>
        </WrapItem>
      ))}
    </Wrap>
  );
}
