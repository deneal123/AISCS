import { useEffect, useState } from 'react';
import { loadFlyKinematics } from './flyKinematics';

export default function useFlyKinematics(assetId, enabled) {
  const [state, setState] = useState({ source: null, data: null, error: '', loading: false });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController(), supported = Boolean(enabled && assetId?.startsWith('flybody-'));
    setState({ source: assetId, data: null, error: '', loading: supported });
    if (supported) loadFlyKinematics(controller.signal).then(data => {
      if (!controller.signal.aborted) setState({ source: assetId, data, error: '', loading: false });
    }).catch(() => {
      if (!controller.signal.aborted) setState({ source: assetId, data: null, loading: false, error: 'Не удалось загрузить суставы исходной модели. Тело и нейронная запись доступны.' });
    });
    return () => controller.abort();
  }, [assetId, enabled, attempt]);
  return { ...state, data: state.source === assetId && enabled ? state.data : null, retry: () => setAttempt(value => value + 1) };
}
