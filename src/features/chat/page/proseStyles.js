import { colors } from '@theme/tokens';
import { CHAT_THEME } from '../constants/theme';

export const PROSE_SX = {
  maxWidth: '100%',
  overflowWrap: 'anywhere',
  wordBreak: 'break-word',
  '& > *': { background: 'transparent', maxWidth: '100%' },
  '& p, & li, & span, & strong, & em, & del, & h1, & h2, & h3, & h4, & h5, & h6': {
    background: 'transparent',
    backgroundColor: 'transparent',
    overflowWrap: 'anywhere',
    wordBreak: 'break-word',
  },
  '& p': { margin: '0 0 0.8em 0', background: 'transparent', overflowWrap: 'anywhere' },
  '& p:last-child': { marginBottom: 0 },
  '& h1, & h2, & h3, & h4': {
    fontWeight: 700,
    letterSpacing: '-0.015em',
    lineHeight: 1.3,
    margin: '1.2em 0 0.5em',
    color: CHAT_THEME.textPrimary,
  },
  '& h1:first-child, & h2:first-child, & h3:first-child': { marginTop: 0 },
  '& h1': { fontSize: '1.45em' },
  '& h2': { fontSize: '1.25em' },
  '& h3': { fontSize: '1.1em' },
  '& ul, & ol': { paddingLeft: '1.4em', margin: '0.4em 0 0.8em' },
  '& li': { marginBottom: '0.3em', lineHeight: 1.65 },
  '& li > p': { margin: '0.2em 0' },
  '& li::marker': { color: colors.blue[300] },
  '& strong': { fontWeight: 700, color: CHAT_THEME.textPrimary },
  '& em': { color: colors.fg[2], fontStyle: 'italic' },
  // Инлайн-код: холодный iris-акцент (было rgba(252,165,165) — читалось как ошибка-красный).
  '& code': {
    fontFamily: "'JetBrains Mono', 'SF Mono', Menlo, monospace",
    fontSize: '0.86em',
    background: colors.accent.soft,
    border: `1px solid ${colors.border.card}`,
    borderRadius: '6px',
    padding: '0.1em 0.42em',
    color: colors.iris[300],
    fontWeight: 500,
  },
  // ⚠️ Код-БЛОК (```без языка → <pre><code>) обязан скроллиться ВНУТРИ, а не растягивать
  // сообщение. Без этого правила <pre> с white-space:pre и длинной строкой (англоязычный
  // промпт генератора картинок) распирал пузырь и давал горизонтальный скролл всей
  // страницы. Тот же приём, что у формул KaTeX ниже. Блоки С языком идут в CodeBlock
  // (свой контейнер), сюда попадает только plain-fence — потому оформляем его тут же.
  '& pre': {
    overflowX: 'auto',
    maxWidth: '100%',
    margin: '0.8em 0',
    padding: '0.9em 1em',
    borderRadius: '10px',
    background: colors.bg.inputStrong,
    border: `1px solid ${colors.border.card}`,
    fontSize: '13px',
    lineHeight: 1.5,
    // Внутри блока перенос НЕ навязываем: код читается построчно, длинное — под скролл.
    whiteSpace: 'pre',
  },
  '& pre code': {
    background: 'transparent',
    border: 'none',
    padding: 0,
    color: 'inherit',
    fontSize: 'inherit',
    // Внутри <pre> инлайн-правила переноса не действуют — иначе строки кода ломались бы.
    overflowWrap: 'normal',
    wordBreak: 'normal',
    fontFamily: "'JetBrains Mono', 'SF Mono', Menlo, monospace",
  },
  '& a': { color: colors.iris[300], textDecoration: 'underline', textUnderlineOffset: '3px', transition: 'opacity 0.15s' },
  '& a:hover': { opacity: 0.8 },
  '& blockquote': {
    borderLeft: `3px solid ${colors.border.blue}`,
    paddingLeft: '1em',
    color: colors.fg[3],
    margin: '0.6em 0',
    fontStyle: 'italic',
  },
  '& hr': { border: 'none', borderTop: `1px solid ${colors.border.medium}`, margin: '1em 0' },
  // ⚠️ Широкая таблица (много колонок) распирала бы сообщение так же, как длинный код.
  // react-markdown рендерит <table> без обёртки, поэтому оборачивать в CSS нечем —
  // делаем сам <table> блоком со своим горизонтальным скроллом (приём GitHub-разметки).
  '& table': {
    display: 'block',
    width: 'fit-content',
    maxWidth: '100%',
    overflowX: 'auto',
    borderCollapse: 'collapse',
    margin: '0.8em 0',
  },
  '& th, & td': {
    padding: '0.5em 0.75em',
    border: `1px solid ${colors.border.medium}`,
    textAlign: 'left',
  },
  '& th': { background: colors.border.default, fontWeight: 600 },
  // Широкие формулы KaTeX скроллятся по горизонтали, а не растягивают страницу.
  '& .katex-display': { overflowX: 'auto', overflowY: 'hidden', maxWidth: '100%', padding: '0.2em 0' },
  // KaTeX наследует currentColor — попадает в тёмную тему без отдельной палитры.
  '& .katex': { color: 'inherit' },
};
