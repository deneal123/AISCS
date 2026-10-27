import React, { useState } from 'react';
// Shared curated grammars stay in this lazy chunk, never the initial chat bundle.
import CodeSyntax from '@shared/controls/CodeSyntax';
import { Box, Button, Icon, Text } from '@chakra-ui/react';
import { FiCheck } from '@shared/icons';
import { colors, borderRadius } from '@theme/tokens';
import { copyText } from '@utils/clipboard';


/**
 * Подсветка код-блока. Вынесено в отдельный модуль и грузится ЛЕНИВО
 * (React.lazy из MessageRenderer): подсветка не попадает в основной чанк чата, а
 * подтягивается только когда в ответе реально появляется блок кода. До загрузки
 * MessageRenderer показывает plain-<pre> fallback. Неизвестный язык → без
 * подсветки (plain), но текст и «Копировать» работают.
 */
function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    if (await copyText(text)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  };
  return (
    <Button
      size="xs"
      variant="ghost"
      leftIcon={copied ? <Icon as={FiCheck} boxSize="12px" /> : undefined}
      color={copied ? colors.success : 'whiteAlpha.600'}
      _hover={{ color: 'white', bg: 'whiteAlpha.200' }}
      onClick={handleCopy}
      position="absolute"
      top={2}
      right={2}
      zIndex={1}
      fontSize="11px"
      h="22px"
      px={2}
    >
      {copied ? 'Скопировано' : 'Копировать'}
    </Button>
  );
}

export default function CodeBlock({ language, value }) {
  return (
    <Box
      position="relative"
      borderRadius={borderRadius.md}
      overflow="hidden"
      my={3}
      border={`1px solid ${colors.border.card}`}
    >
      <Box
        position="absolute"
        top={0}
        left={0}
        right={0}
        px={3}
        py={1.5}
        bg="rgba(0,0,0,0.55)"
        display="flex"
        alignItems="center"
        justifyContent="space-between"
        zIndex={1}
        borderBottom={`1px solid ${colors.border.subtle}`}
      >
        <Text fontSize="10.5px" color={colors.iris[300]} fontFamily="'JetBrains Mono', monospace" fontWeight="600" letterSpacing="0.04em" textTransform="lowercase">
          {language}
        </Text>
        <CopyButton text={value} />
      </Box>
      <CodeSyntax
        language={language}
        value={value}
        customStyle={{
          margin: 0,
          borderRadius: 0,
          background: colors.bg.inputStrong,
          paddingTop: '2.3rem',
          fontSize: '13px',
        }}
      />
    </Box>
  );
}
