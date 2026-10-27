import { useCallback, useEffect, useRef, useState } from 'react';
import { prepareIdeAgent } from '@api/ide';

/** Prepare the explicit repository target before the shared sender clears input. */
export function useIdeAgentSubmit({ threadId, active, context, send, onStop, setError }) {
  const [preparing, setPreparing] = useState(false);
  const pending = useRef(null);
  const scope = `${threadId}:${active}:${context?.repository_id}:${context?.generation}:${context?.blocked}`;
  const current = useRef(scope);
  current.current = scope;
  const cancel = useCallback(() => { pending.current?.abort(); pending.current = null; setPreparing(false); }, []);
  useEffect(() => { cancel(); return cancel; }, [scope, cancel]);
  const submit = useCallback(async text => {
    if (!active || !context?.generation || context.blocked || pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    setPreparing(true);
    try {
      const target = await prepareIdeAgent(threadId, context.repository_id, context.generation, controller.signal);
      if (controller.signal.aborted || current.current !== scope || pending.current !== controller) return;
      if (typeof target?.target_id !== 'string' || !/^[a-f0-9-]{36}$/.test(target.target_id)) throw new Error('invalid target');
      await send(text, { ideTargetId: target.target_id, ideRepository: context.repository_id, routeOverride: 'general' });
    } catch {
      if (!controller.signal.aborted && current.current === scope) setError('Не удалось подготовить запрос IDE. Текст сохранён. Проверьте среду и повторите отправку.');
    } finally {
      if (pending.current === controller) { pending.current = null; setPreparing(false); }
    }
  }, [active, context, threadId, send, scope, setError]);
  return { preparing, submit, cancelPreparation: cancel, stop: () => { cancel(); onStop?.(); } };
}
