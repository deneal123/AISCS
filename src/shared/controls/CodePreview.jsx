import { lazy, Suspense } from 'react';
import ErrorBoundary from '../ui/molecules/ErrorBoundary';

const CodeSyntax = lazy(() => import('./CodeSyntax'));

/** Literal source remains available if the optional grammar chunk cannot load. */
export default function CodePreview({ value = '', customStyle, ...props }) {
  const plain = <pre style={customStyle}><code>{value || '\n'}</code></pre>;
  return <ErrorBoundary fallback={plain}>
    <Suspense fallback={plain}>
      <CodeSyntax {...props} value={value} customStyle={customStyle} />
    </Suspense>
  </ErrorBoundary>;
}
