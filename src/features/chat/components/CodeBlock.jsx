import React, { useState } from 'react';
// PrismLight + курированный набор языков вместо `Prism` (тот тянул ВСЕ ~200
// языков, ~1MB). В бандл CodeBlock попадают только перечисленные ниже языки. Тему
// импортируем одним файлом (а не индексом styles/prism, который бандлит все ~40 тем).
//
// Именно PrismLight, а не PrismAsyncLight: async-вариант умеет догружать ЛЮБОЙ язык
// по требованию, из-за чего webpack заводил context на весь refractor и выплёвывал
// ~287 чанков-языков, которые никогда не грузятся (мы регистрируем все нужные ниже
// статически). Асинхронность здесь и не нужна — сам CodeBlock уже грузится лениво
// (React.lazy из MessageRenderer), т.е. подсветка и так вне основного чанка.
//
// Импорт ПРЯМОЙ, не через бочку `react-syntax-highlighter`: её index.js реэкспортит
// ВСЕ варианты (prism-async-light с refractor-context'ом и prism со всеми ~200
// языками), и одного этого хватало, чтобы чанки-языки продолжали генерироваться.
import SyntaxHighlighter from 'react-syntax-highlighter/dist/esm/prism-light';
import vscDarkPlus from 'react-syntax-highlighter/dist/esm/styles/prism/vsc-dark-plus';
import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash';
import c from 'react-syntax-highlighter/dist/esm/languages/prism/c';
import cpp from 'react-syntax-highlighter/dist/esm/languages/prism/cpp';
import csharp from 'react-syntax-highlighter/dist/esm/languages/prism/csharp';
import css from 'react-syntax-highlighter/dist/esm/languages/prism/css';
import diff from 'react-syntax-highlighter/dist/esm/languages/prism/diff';
import docker from 'react-syntax-highlighter/dist/esm/languages/prism/docker';
import go from 'react-syntax-highlighter/dist/esm/languages/prism/go';
import graphql from 'react-syntax-highlighter/dist/esm/languages/prism/graphql';
import java from 'react-syntax-highlighter/dist/esm/languages/prism/java';
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript';
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json';
import jsx from 'react-syntax-highlighter/dist/esm/languages/prism/jsx';
import kotlin from 'react-syntax-highlighter/dist/esm/languages/prism/kotlin';
import markdown from 'react-syntax-highlighter/dist/esm/languages/prism/markdown';
import markup from 'react-syntax-highlighter/dist/esm/languages/prism/markup';
import php from 'react-syntax-highlighter/dist/esm/languages/prism/php';
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python';
import ruby from 'react-syntax-highlighter/dist/esm/languages/prism/ruby';
import rust from 'react-syntax-highlighter/dist/esm/languages/prism/rust';
import sql from 'react-syntax-highlighter/dist/esm/languages/prism/sql';
import swift from 'react-syntax-highlighter/dist/esm/languages/prism/swift';
import tsx from 'react-syntax-highlighter/dist/esm/languages/prism/tsx';
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript';
import yaml from 'react-syntax-highlighter/dist/esm/languages/prism/yaml';
import { Box, Button, Icon, Text } from '@chakra-ui/react';
import { FiCheck } from '@shared/icons';
import { colors, borderRadius } from '@theme/tokens';
import { copyText } from '@utils/clipboard';

// Регистрируем язык под каноничным именем + распространёнными алиасами из ```-фенсов.
const LANGUAGES = {
  bash, sh: bash, shell: bash, zsh: bash,
  c, cpp, 'c++': cpp, csharp, cs: csharp, 'c#': csharp,
  css, diff, docker, dockerfile: docker, go, golang: go, graphql,
  java, javascript, js: javascript, json, jsx,
  kotlin, kt: kotlin, markdown, md: markdown, markup, html: markup, xml: markup,
  php, python, py: python, ruby, rb: ruby, rust, rs: rust,
  sql, swift, tsx, typescript, ts: typescript, yaml, yml: yaml,
};
Object.entries(LANGUAGES).forEach(([name, def]) => SyntaxHighlighter.registerLanguage(name, def));

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
      <SyntaxHighlighter
        style={vscDarkPlus}
        language={language}
        PreTag="div"
        customStyle={{
          margin: 0,
          borderRadius: 0,
          background: colors.bg.inputStrong,
          paddingTop: '2.3rem',
          fontSize: '13px',
        }}
      >
        {value}
      </SyntaxHighlighter>
    </Box>
  );
}
