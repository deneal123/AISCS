import { useEffect, useRef, useState } from 'react';

const empty = () => ({ title: '', body: '', start: '1', end: '1' });
const initial = (scope) => ({ scope, form: empty(), errors: {} });

export function useWorkIssueDraft(threadId, path) {
  const scope = JSON.stringify([threadId, path]);
  const currentScope = useRef(scope);
  currentScope.current = scope;
  const [state, setState] = useState(() => initial(scope));
  const value = state.scope === scope ? state : initial(scope);

  useEffect(() => {
    setState((previous) => (previous.scope === scope ? previous : initial(scope)));
  }, [scope]);

  const update = (field, change) => {
    if (currentScope.current !== scope) return;
    setState((previous) => {
      const base = previous.scope === scope ? previous : initial(scope);
      return { ...base, [field]: typeof change === 'function' ? change(base[field]) : change };
    });
  };

  return {
    form: value.form,
    errors: value.errors,
    setForm: (change) => update('form', change),
    setErrors: (change) => update('errors', change),
    clearSubmitted: (submitted) => {
      if (currentScope.current !== scope) return;
      setState((previous) => (previous.scope === scope && previous.form === submitted
        ? initial(scope) : previous));
    },
  };
}
