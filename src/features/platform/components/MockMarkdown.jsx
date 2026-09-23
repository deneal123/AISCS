import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkBreaks from "remark-breaks";
import { Box } from "@chakra-ui/react";
import { colors } from "@theme/tokens";
import MockCodeBlock from "./MockCodeBlock";

// Локальная копия PROSE_SX чата (features/chat/page/proseStyles.js) — ESLint не даёт
// импортировать его напрямую. CHAT_THEME.textPrimary заменён на colors.fg[1] (= #FFFFFF);
// katex опущен (в примерах нет формул). Плюс аккуратные task-list чекбоксы для чек-листов.
const PROSE_SX = {
  maxWidth: "100%",
  overflowWrap: "anywhere",
  wordBreak: "break-word",
  "& > *": { background: "transparent", maxWidth: "100%" },
  "& p, & li, & span, & strong, & em, & del, & h1, & h2, & h3, & h4, & h5, & h6": {
    background: "transparent",
    backgroundColor: "transparent",
    overflowWrap: "anywhere",
    wordBreak: "break-word",
  },
  "& p": { margin: "0 0 0.8em 0", background: "transparent", overflowWrap: "anywhere" },
  "& p:last-child": { marginBottom: 0 },
  "& h1, & h2, & h3, & h4": {
    fontWeight: 700,
    letterSpacing: "-0.015em",
    lineHeight: 1.3,
    margin: "1.2em 0 0.5em",
    color: colors.fg[1],
  },
  "& h1:first-child, & h2:first-child, & h3:first-child": { marginTop: 0 },
  "& h1": { fontSize: "1.45em" },
  "& h2": { fontSize: "1.25em" },
  "& h3": { fontSize: "1.1em" },
  "& ul, & ol": { paddingLeft: "1.4em", margin: "0.4em 0 0.8em" },
  "& li": { marginBottom: "0.3em", lineHeight: 1.65 },
  "& li > p": { margin: "0.2em 0" },
  "& li::marker": { color: colors.blue[300] },
  "& ul.contains-task-list": { listStyle: "none", paddingLeft: "0.2em" },
  "& li.task-list-item": { marginBottom: "0.35em" },
  '& input[type="checkbox"]': {
    marginRight: "0.55em",
    accentColor: colors.accent.base,
    transform: "translateY(1px)",
  },
  "& strong": { fontWeight: 700, color: colors.fg[1] },
  "& em": { color: colors.fg[2], fontStyle: "italic" },
  "& code": {
    fontFamily: "'JetBrains Mono', 'SF Mono', Menlo, monospace",
    fontSize: "0.86em",
    background: colors.accent.soft,
    border: `1px solid ${colors.border.card}`,
    borderRadius: "6px",
    padding: "0.1em 0.42em",
    color: colors.iris[300],
    fontWeight: 500,
  },
  "& pre code": { background: "transparent", border: "none", padding: 0, color: "inherit", fontSize: "inherit" },
  "& a": { color: colors.iris[300], textDecoration: "underline", textUnderlineOffset: "3px", transition: "opacity 0.15s" },
  "& a:hover": { opacity: 0.8 },
  "& blockquote": {
    borderLeft: `3px solid ${colors.border.blue}`,
    paddingLeft: "1em",
    color: colors.fg[3],
    margin: "0.6em 0",
    fontStyle: "italic",
  },
  "& hr": { border: "none", borderTop: `1px solid ${colors.border.medium}`, margin: "1em 0" },
  "& table": { width: "100%", borderCollapse: "collapse", margin: "0.8em 0" },
  "& th, & td": { padding: "0.5em 0.75em", border: `1px solid ${colors.border.medium}`, textAlign: "left" },
  "& th": { background: colors.surface.tint3, fontWeight: 600 },
};

const MARKDOWN_COMPONENTS = {
  code: ({ node, className, children, ...props }) => {
    const match = /language-(\w+)/.exec(className || "");
    if (match) {
      const codeText = String(children ?? "").replace(/\n$/, "");
      return <MockCodeBlock language={match[1]} value={codeText} />;
    }
    return (
      <code className={className} {...props}>
        {children}
      </code>
    );
  },
};

/** Рендер markdown-ответа агента в prose-стилистике чата (для витрины /platform). */
export default function MockMarkdown({ content }) {
  if (!content) return null; // ответ-артефакт (изображение/pptx) без текста — не рисуем пустой пузырь
  return (
    <Box sx={PROSE_SX} fontSize={{ base: "14px", md: "14.5px" }} lineHeight="1.72" color={colors.fg[1]}>
      <ReactMarkdown components={MARKDOWN_COMPONENTS} remarkPlugins={[remarkGfm, remarkBreaks]}>
        {content}
      </ReactMarkdown>
    </Box>
  );
}
