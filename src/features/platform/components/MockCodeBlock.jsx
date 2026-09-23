import React, { useState, useRef, useEffect } from "react";
// Реплика чат-CodeBlock для витрины /platform (ESLint запрещает импорт @features/chat/*).
// PrismLight + узкий набор языков (в примерах только Python; пара про запас), тема одним файлом.
//
// Именно PrismLight ПРЯМЫМ импортом (см. тот же разбор в chat/CodeBlock): бочка
// react-syntax-highlighter реэкспортит prism-async-light, а тот заводит webpack-context
// на весь refractor → ~287 чанков-языков, которые никогда не грузятся (все нужные
// регистрируем статически ниже). Асинхронность не нужна: /platform — ленивый роут.
import SyntaxHighlighter from "react-syntax-highlighter/dist/esm/prism-light";
import vscDarkPlus from "react-syntax-highlighter/dist/esm/styles/prism/vsc-dark-plus";
import python from "react-syntax-highlighter/dist/esm/languages/prism/python";
import javascript from "react-syntax-highlighter/dist/esm/languages/prism/javascript";
import typescript from "react-syntax-highlighter/dist/esm/languages/prism/typescript";
import json from "react-syntax-highlighter/dist/esm/languages/prism/json";
import bash from "react-syntax-highlighter/dist/esm/languages/prism/bash";
import { Box, Button, Icon, Text } from "@chakra-ui/react";
import { FiCheck } from "@shared/icons";
import { colors, borderRadius } from "@theme/tokens";
import { copyText } from "@utils/clipboard";

const LANGUAGES = {
  python, py: python, javascript, js: javascript,
  typescript, ts: typescript, json, bash, sh: bash, shell: bash,
};
Object.entries(LANGUAGES).forEach(([name, def]) => SyntaxHighlighter.registerLanguage(name, def));

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef(null);
  useEffect(() => () => clearTimeout(timerRef.current), []);
  const handleCopy = async () => {
    if (await copyText(text)) {
      setCopied(true);
      clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCopied(false), 1500);
    }
  };
  return (
    <Button
      size="xs"
      variant="ghost"
      leftIcon={copied ? <Icon as={FiCheck} boxSize="12px" /> : undefined}
      color={copied ? colors.success : "whiteAlpha.600"}
      _hover={{ color: "white", bg: "whiteAlpha.200" }}
      onClick={handleCopy}
      position="absolute"
      top={2}
      right={2}
      zIndex={1}
      fontSize="11px"
      h="22px"
      px={2}
    >
      {copied ? "Скопировано" : "Копировать"}
    </Button>
  );
}

export default function MockCodeBlock({ language, value }) {
  return (
    <Box position="relative" borderRadius={borderRadius.md} overflow="hidden" my={3}
      border={`1px solid ${colors.border.card}`}>
      <Box position="absolute" top={0} left={0} right={0} px={3} py={1.5} bg={colors.bg.sticky}
        display="flex" alignItems="center" justifyContent="space-between" zIndex={1}
        borderBottom={`1px solid ${colors.border.subtle}`}>
        <Text fontSize="10.5px" color={colors.iris[300]} fontFamily="'JetBrains Mono', monospace"
          fontWeight="600" letterSpacing="0.04em" textTransform="lowercase">
          {language}
        </Text>
        <CopyButton text={value} />
      </Box>
      <SyntaxHighlighter
        style={vscDarkPlus}
        language={language}
        PreTag="div"
        customStyle={{
          margin: 0,
          borderRadius: 0,
          background: colors.bg.inputStrong,
          paddingTop: "2.3rem",
          fontSize: "13px",
        }}
      >
        {value}
      </SyntaxHighlighter>
    </Box>
  );
}
