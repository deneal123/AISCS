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


/** Shared curated grammar owner; unknown and large source stays literal text. */
export const CODE_HIGHLIGHT_LIMIT = 65536;

export default function CodeSyntax({ language, value = '', showLineNumbers = false, customStyle = {} }) {
  const style = { margin: 0, borderRadius: 0, background: 'transparent', ...customStyle };
  if (!Object.prototype.hasOwnProperty.call(LANGUAGES, language) || value.length > CODE_HIGHLIGHT_LIMIT) {
    return <pre style={style}><code>{value || '\n'}</code></pre>;
  }
  return <SyntaxHighlighter language={language} style={vscDarkPlus} PreTag="div"
    showLineNumbers={showLineNumbers} lineNumberStyle={{ minWidth: '3em', paddingRight: '1.5em', userSelect: 'none' }}
    customStyle={style}>{value || '\n'}</SyntaxHighlighter>;
}
